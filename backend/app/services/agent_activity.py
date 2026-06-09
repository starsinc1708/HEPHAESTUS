"""Agent activity aggregator — ported verbatim from dashboard/server.py:855-962.

Detects which agent ran in each iter dir and builds a collaboration graph
across all iter-* and scan-* directories.
"""

from __future__ import annotations

import logging
import pathlib
import re
import time
from typing import Any, cast

from app.core.helpers import _load_json
from app.core.state import _read_state

log = logging.getLogger("hephaestus.backend.agent_activity")


def _detect_implementer_agent(d: pathlib.Path) -> tuple[str | None, str | None]:
    """Look at the first ~5 lines of output.primary.jsonl to find which agent ran.
    opencode prints 'agent X not found. Falling back to default agent' or session events
    that include agent name. Defensive."""
    for stream_name in ("output.primary.jsonl", "output.fallback.jsonl"):
        p = d / stream_name
        if not p.exists():
            continue
        try:
            for line in p.read_text(errors="replace").splitlines()[:30]:
                m = re.search(r'agent[\s"]+([A-Za-z0-9_-]+)["\s]', line)
                if m:
                    name = m.group(1)
                    if name not in ("default", "found"):
                        return name, ("primary" if stream_name == "output.primary.jsonl" else "fallback")
        except Exception:
            pass
    # nothing — fall back to "default agent"
    return ("default", "primary") if (d / "output.primary.jsonl").exists() else (None, None)


def _agent_activity() -> dict[str, Any]:
    """Walk all iter-* + scan-* dirs. Build a graph of agent collaborations.
    Returns: { agents: [...], edges: [...], timeline: [...] }
    """
    from app.core.scan import _scans_dir

    scans_dir = _scans_dir()

    agents: dict[
        str, dict[str, Any]
    ] = {}  # name -> { name, roles: {role: count}, invocations, first_seen, last_seen, models: [], tasks: [] }
    edges: dict[tuple[str, str, str], int] = {}  # (src, dst, kind) -> count
    timeline: list[dict[str, Any]] = []

    def add_agent(
        name: str | None,
        role: str,
        when: str | None,
        task: str | None = None,
        model: str | None = None,
        outcome: str | None = None,
    ) -> None:
        if not name:
            return
        a = agents.setdefault(
            name,
            {
                "name": name,
                "roles": {},
                "invocations": 0,
                "first_seen": when,
                "last_seen": when,
                "tasks": [],
            },
        )
        a["roles"][role] = a["roles"].get(role, 0) + 1
        a["invocations"] += 1
        if when:
            if not a["first_seen"] or when < a["first_seen"]:
                a["first_seen"] = when
            if not a["last_seen"] or when > a["last_seen"]:
                a["last_seen"] = when
        if task:
            a["tasks"].append({"task": task, "role": role, "outcome": outcome, "when": when})

    def add_edge(src: str | None, dst: str | None, kind: str) -> None:
        if not src or not dst or src == dst:
            return
        k = (src, dst, kind)
        edges[k] = edges.get(k, 0) + 1

    # ------- iter-* dirs -------
    for d in sorted(scans_dir.parent.glob("iter-*")):
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(d.stat().st_mtime))
        # find item_id + outcome from state
        item_id = None
        outcome = None
        for it in _read_state().get("items", []):
            if it.get("lastIter") == d.name:
                item_id = it.get("id")
                outcome = it.get("status")
                break
        impl_agent, _stream = _detect_implementer_agent(d)
        if impl_agent:
            add_agent(impl_agent, "implementer", when, task=d.name, outcome=outcome)
        # reviewers from reviews/*.verdict.json
        rev_dir = d / "reviews"
        reviewers: list[dict[str, Any]] = []
        if rev_dir.exists():
            for vf in sorted(rev_dir.glob("*.verdict.json")):
                v = cast("dict[str, Any]", _load_json(vf) or {})
                rname = v.get("reviewer")
                tier = v.get("tier") or "tier1"
                if not rname:
                    continue
                role = {"tier1": "tier-1 reviewer", "tier2": "tier-2 reviewer", "final": "final reviewer"}.get(
                    tier, "reviewer"
                )
                add_agent(rname, role, when, task=d.name, outcome=v.get("verdict"))
                if impl_agent:
                    add_edge(impl_agent, rname, "implementer→" + tier)
                reviewers.append({"agent": rname, "tier": tier, "verdict": v.get("verdict")})
        timeline.append(
            {
                "type": "iter",
                "id": d.name,
                "when": when,
                "item_id": item_id,
                "implementer": impl_agent,
                "reviewers": reviewers,
                "outcome": outcome,
            }
        )

    # ------- scan-* dirs -------
    # Scanner/reducer outputs are raw agent JSONL event streams (.jsonl), not
    # {agent, findings} objects — extract the agent text and parse the blocks.
    from app.core.scan_run import _agent_text, parse_findings_block, parse_proposals_block

    for sd in sorted(scans_dir.glob("scan-*")):
        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(sd.stat().st_mtime))
        scanners: list[dict[str, Any]] = []
        reducers: list[dict[str, Any]] = []
        for f in sorted(sd.glob("scanner-*.findings.jsonl")):
            aname = f.name.split(".")[0]  # "scanner-0"
            add_agent(aname, "scanner", when, task=sd.name)
            scanners.append({"agent": aname, "findings": len(parse_findings_block(_agent_text(f)))})
        for f in sorted(sd.glob("reducer-*.proposals.jsonl")):
            aname = f.name.split(".")[0]  # "reducer-0"
            add_agent(aname, "reducer", when, task=sd.name)
            reducers.append({"agent": aname, "proposals": len(parse_proposals_block(_agent_text(f)))})
            # scanner→reducer edges (every scanner feeds every reducer)
            for s in scanners:
                add_edge(s["agent"], aname, "scanner→reducer")
        timeline.append(
            {
                "type": "scan",
                "id": sd.name,
                "when": when,
                "scanners": scanners,
                "reducers": reducers,
            }
        )

    return {
        "agents": sorted(agents.values(), key=lambda x: -x["invocations"]),
        "edges": [
            {"source": s, "target": t, "kind": k, "weight": w}
            for (s, t, k), w in sorted(edges.items(), key=lambda x: -x[1])
        ],
        "timeline": sorted(timeline, key=lambda x: x.get("when", ""), reverse=True),
    }
