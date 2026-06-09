"""Repo scan (map-reduce) management — ported from dashboard/server.py:966-1088.

Start scans, list scan dirs, check status, load results, and import
scan proposals into the work queue.
"""

from __future__ import annotations

import json
import logging
import pathlib
import re
import sys
import time
from typing import TYPE_CHECKING, Any, cast

from app.config import filter_env_bits
from app.core.decisions import _append_decision
from app.core.decompose import decompose_proposals
from app.core.helpers import _DEFAULT_ACCEPTANCE_ADHOC, _load_json
from app.core.state import _read_state, _state_dir, _StateLock, _write_state
from app.core.ws_shim import get_active_profile
from app.services import project_memory

if TYPE_CHECKING:
    from app.core.decompose import _DecomposeRunner

log = logging.getLogger("hephaestus.backend.scan")

# Dir that contains the importable ``app`` package (…/backend). The worker is launched
# as ``python -m app.core.scan_run`` from HERE so ``app`` resolves regardless of the
# repo cwd (the package isn't necessarily pip-installed in the venv). app/core/scan.py
# -> parents[2] == backend.
_BACKEND_DIR = pathlib.Path(__file__).resolve().parents[2]


def _scans_dir() -> pathlib.Path:
    """Scans live under the *active workspace* state dir (<repo>/.hephaestus/state/scans),
    mirroring state.py's _state_dir(); falls back to the legacy global state dir."""
    return _state_dir() / "scans"


def _build_runner(ws: object | None = None) -> _DecomposeRunner | None:
    """Construct AgentRunner if available; None otherwise.

    Carries the workspace engine/env/profiles so decomposition honours the planner
    role's engine profile (e.g. Claude for planning).
    """
    try:
        from app.core.process import ProcessManager
        from app.services.opencode_runner import AgentRunner

        runner = AgentRunner(
            ProcessManager(),
            engine=getattr(ws, "engine", "opencode"),
            env=getattr(ws, "engine_env", {}),
            profiles=getattr(ws, "engine_profiles", []),
        )
        # AgentRunner.run satisfies _DecomposeRunner structurally; its ref param is
        # narrower (AgentRef) than the Protocol's `ref: object`, so cast explicitly.
        return cast("_DecomposeRunner", runner)
    except Exception as exc:
        log.warning("_build_runner: AgentRunner unavailable (%s)", exc)
        return None


def _try_broadcast_state_safe() -> None:
    try:
        from app.core.queue import _try_broadcast_state
        _try_broadcast_state()
    except Exception:
        log.debug("_try_broadcast_state_safe: broadcast failed", exc_info=True)
        pass


def _next_scan_dir(base: pathlib.Path) -> tuple[str, pathlib.Path]:
    """Allocate the next scan-N directory under base."""
    base.mkdir(parents=True, exist_ok=True)
    nums = [
        int(m.group(1))
        for d in base.glob("scan-*")
        if d.is_dir() and (m := re.match(r"scan-(\d+)$", d.name))
    ]
    name = f"scan-{(max(nums) + 1) if nums else 1}"
    sd = base / name
    sd.mkdir(parents=True, exist_ok=True)
    return name, sd


def _scan_start(opts: dict[str, Any]) -> dict[str, Any]:
    from app.core.process import ProcState, pm
    from app.core.state import _atomic_write

    if pm.status("scan").state == ProcState.RUNNING:
        return {"ok": False, "error": "a scan is already running"}

    # The scan runs against the registry's active workspace (real repo + agents/engine).
    ws = None
    try:
        from app.core.workspaces import registry

        ws = registry.active()
    except Exception:  # noqa: BLE001 — registry optional; handled below
        log.debug("_scan_start: workspace registry unavailable", exc_info=True)
        ws = None
    if ws is None:
        return {"ok": False, "error": "no active repository — select one in Settings"}

    try:
        from app.config import _config_overrides

        cfg = _config_overrides()
    except Exception:
        log.debug("_scan_start: failed to read config overrides", exc_info=True)
        cfg = {}
    env_bits: dict[str, Any] = dict(cfg)
    try:
        scanners_val = int(opts.get("scanners") or 6)
        if scanners_val < 1 or scanners_val > 50:
            return {"ok": False, "error": "scanners must be between 1 and 50"}
        env_bits["SCANNERS"] = str(scanners_val)
    except (ValueError, TypeError):
        return {"ok": False, "error": "scanners must be an integer"}
    try:
        reviewers_val = int(opts.get("reviewers") or 2)
        if reviewers_val < 1 or reviewers_val > 50:
            return {"ok": False, "error": "reviewers must be between 1 and 50"}
        env_bits["REVIEWERS"] = str(reviewers_val)
    except (ValueError, TypeError):
        return {"ok": False, "error": "reviewers must be an integer"}
    scope = (opts.get("scope") or "").strip()
    if not scope:
        return {"ok": False, "error": "scope is required"}
    # Sanitize scope — must be space-separated dir names. Refuse shell metacharacters.
    if not re.match(r"^[A-Za-z0-9_./\- ]{1,200}$", scope):
        return {"ok": False, "error": "scope contains forbidden characters"}
    env_bits["SCOPE"] = scope
    env_bits["HEPHAESTUS_WORKSPACE_ID"] = ws.id
    env_bits = filter_env_bits(env_bits)
    # PYTHONPATH isn't a config key (filtered out above) — set it after filtering so the
    # spawned `python -m app.core.scan_run` can import `app` even if cwd weren't backend.
    env_bits["PYTHONPATH"] = str(_BACKEND_DIR)

    # Allocate scan-N under the active workspace, persist the request + an initial status
    # the dashboard can poll immediately, then spawn the real map-reduce worker.
    dirname, sd = _next_scan_dir(_scans_dir())
    _atomic_write(sd / "request.json", json.dumps(
        {"scope": scope, "scanners": scanners_val, "reviewers": reviewers_val}, ensure_ascii=False))
    _atomic_write(sd / "status.json", json.dumps({
        "phase": "queued", "detail": "starting worker…",
        "scanners": scanners_val, "reviewers": reviewers_val,
        "scanners_done": 0, "reducers_done": 0, "scope": scope,
        "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, ensure_ascii=False, indent=2))

    cmd = [sys.executable, "-m", "app.core.scan_run", "--dir", dirname]
    try:
        pm.start("scan", cmd, cwd=str(_BACKEND_DIR), env=env_bits,
                 output_path=str(sd / "scan.log"))  # sync (R1) — cwd=backend so `app` imports
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    return {
        "ok": True,
        "session": "scan",
        "dir": dirname,
        "scanners": scanners_val,
        "reviewers": reviewers_val,
        "scope": scope,
    }


def _scan_running() -> bool:
    from app.core.process import ProcState, pm

    return pm.status("scan").state == ProcState.RUNNING


def _scan_list() -> list[dict[str, Any]]:
    scans_dir = _scans_dir()
    if not scans_dir.exists():
        return []
    out: list[dict[str, Any]] = []
    for d in sorted(scans_dir.glob("scan-*"), reverse=True):
        st_raw = _load_json(d / "status.json")
        st: dict[str, Any] = st_raw if isinstance(st_raw, dict) else {}
        res = _load_json(d / "results.json")
        out.append(
            {
                "dir": d.name,
                "phase": st.get("phase", "unknown"),
                "detail": st.get("detail", ""),
                "scanners": st.get("scanners"),
                "reviewers": st.get("reviewers"),
                "updatedAt": st.get("updatedAt"),
                "n_proposals": (res.get("n_unique") if isinstance(res, dict) else None),
            }
        )
    return out


def _scan_latest() -> pathlib.Path | None:
    scans_dir = _scans_dir()
    if not scans_dir.exists():
        return None
    dirs = sorted(scans_dir.glob("scan-*"), reverse=True)
    return dirs[0] if dirs else None


def _scan_status() -> dict[str, Any]:
    d = _scan_latest()
    if not d:
        return {"running": _scan_running(), "scan_dir": None, "phase": "idle"}
    st_raw = _load_json(d / "status.json")
    st: dict[str, Any] = st_raw if isinstance(st_raw, dict) else {"phase": "unknown"}
    st["running"] = _scan_running()
    st["scan_dir"] = d.name
    # status.json carries authoritative counts written by the worker per phase; only
    # fall back to counting output files (note: worker writes .jsonl) when absent.
    st.setdefault("scanners_done", len(list(d.glob("scanner-*.findings.jsonl"))))
    st.setdefault("reducers_done", len(list(d.glob("reducer-*.proposals.jsonl"))))
    # Worker gone but never reached a terminal phase and produced no results -> it crashed
    # (e.g. import/launch error). Surface as error instead of a phantom in-progress state.
    if not st["running"] and st.get("phase") in {"queued", "chunking", "mapping", "reducing"} \
            and not (d / "results.json").exists():
        st["phase"] = "error"
        st.setdefault("error", "worker exited before completion — see log")
        st["detail"] = "worker stopped — see log"
    return st


def _scan_log(dirname: str, max_lines: int = 200) -> dict[str, Any]:
    """Tail of the worker's captured stdout/stderr (scan.log) for the live log view."""
    if not dirname.startswith("scan-") or ".." in dirname or "/" in dirname:
        return {"ok": False, "error": "invalid scan dir name"}
    p = _scans_dir() / dirname / "scan.log"
    if not p.exists():
        return {"ok": True, "lines": []}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "lines": text.splitlines()[-max_lines:]}


def _scan_results(dirname: str) -> dict[str, Any]:
    d = _scans_dir() / dirname
    if not d.exists() or not dirname.startswith("scan-"):
        return {"ok": False, "error": "not found"}
    res = _load_json(d / "results.json")
    if not res:
        return {"ok": False, "error": "results not ready yet"}
    res_dict: dict[str, Any] = res if isinstance(res, dict) else {}
    return {"ok": True, **res_dict}


_SCAN_ACCEPTANCE_BY_CAT: dict[str, str] = {
    "bug": (
        "Add a regression test that reproduces the cited file:line "
        "and fails without the production fix. Verify must pass."
    ),
    "security": (
        "Add a test that exercises the previously-unsafe path "
        "(e.g. asserts validation rejects bad input). Verify must pass."
    ),
    "perf": (
        "Add a measurement, counter test, or assert that the new path "
        "no longer triggers the inefficient code. Verify must pass."
    ),
    "quality": (
        "Implement the proposal. Verify must pass. If behavior changed, "
        "add a test that pins the new behavior."
    ),
    "test": (
        "The change itself is the test addition. Verify must pass. "
        "The new test must fail when reverted against the existing production code."
    ),
    "docs": "Update the named documentation. No test required if no behavior changed. Verify must pass.",
    "locked-decision": (
        "Bring the code back into compliance with the named locked decision. "
        "Add a test that asserts the invariant."
    ),
}


def _scan_import(dirname: str, ids: list[str]) -> dict[str, Any]:
    """Pull selected proposals from a scan's results.json and append them to the work queue."""
    from app.core.queue import add_proposals_to_queue

    if not dirname.startswith("scan-") or ".." in dirname or "/" in dirname:
        return {"ok": False, "error": "invalid scan dir name"}
    d = _scans_dir() / dirname
    res = _load_json(d / "results.json")
    if not res:
        return {"ok": False, "error": "results not available"}
    res_dict: dict[str, Any] = res if isinstance(res, dict) else {}
    added: list[str] = []
    added_proposals: list[dict[str, Any]] = []
    skipped: list[str] = []
    invalid_count = 0

    # Collect proposals to import, determine which are new vs skipped
    candidates: list[dict[str, Any]] = []
    existing_ids_pre: set[str | None] = set()
    with _StateLock():
        s_pre = _read_state()
        existing_ids_pre = {it.get("id") for it in s_pre.get("items", [])}

    for p in res_dict.get("proposals", []):
        if not p.get("id") or not p.get("title") or not p.get("proposal"):
            invalid_count += 1
            continue
        pid = p.get("id")
        if ids and pid not in ids:
            continue
        if pid in existing_ids_pre:
            skipped.append(pid)
            continue
        # Synthesize an acceptance criterion from the category
        cat = p.get("category") or "quality"
        acceptance = p.get("acceptance") or _SCAN_ACCEPTANCE_BY_CAT.get(cat, _DEFAULT_ACCEPTANCE_ADHOC)
        # Build an enriched proposal that carries the acceptance override so the
        # helper can pick it up directly (it uses p.get("acceptance") first).
        enriched: dict[str, Any] = dict(p)
        enriched["acceptance"] = acceptance
        candidates.append(enriched)

    # Delegate the core append (with standard field mapping) to the shared helper.
    add_proposals_to_queue(candidates, source=f"scan:{dirname}")

    # Second pass: patch in scan-specific extra fields that the generic helper doesn't set.
    if candidates:
        candidate_ids = {c["id"] for c in candidates}
        with _StateLock():
            s2 = _read_state()
            for it in s2.get("items", []):
                if it.get("id") not in candidate_ids:
                    continue
                # Find the matching proposal to read scan-specific fields from.
                for c in candidates:
                    if c["id"] == it["id"]:
                        cat = c.get("category") or "quality"
                        it["plan_file"] = f"SCAN-{dirname}"
                        it["plan_section"] = ""
                        it["wave"] = "SCAN"
                        it["category"] = cat
                        it["severity"] = c.get("severity")
                        it["source_scan"] = dirname
                        it["agreement_count"] = c.get("agreement_count")
                        # Remove the generic 'source' key added by helper; source_scan is canonical.
                        it.pop("source", None)
                        added.append(it["id"])
                        # Rebuild the original proposal shape for decompose.
                        orig = {k: v for k, v in c.items()}
                        added_proposals.append(orig)
                        break
            _write_state(s2)
    if invalid_count:
        log.warning("_scan_import: %d proposals skipped due to missing required fields", invalid_count)

    # Decompose freshly-added proposals into Task graph fields (depends_on/order/conflict).
    ws = get_active_profile()
    decomposed: list[str] = []
    if added_proposals:
        import asyncio

        runner = _build_runner(ws)
        try:
            tasks = asyncio.run(
                decompose_proposals(ws, added_proposals, scan_dir=dirname, runner=runner)
            )
        except Exception as exc:
            log.warning("_scan_import: decompose failed (%s) — 1:1 order only", exc)
            tasks = [
                {"id": p["id"], "dependsOn": [], "epicId": None, "parent": None,
                 "orderIndex": i, "conflictGroup": None}
                for i, p in enumerate(added_proposals)
            ]
        graph_by_id = {t["id"]: t for t in tasks}
        with _StateLock():
            s2 = _read_state()
            for it in s2.get("items", []):
                g = graph_by_id.get(it.get("id"))
                if g:
                    it["dependsOn"] = g.get("dependsOn", [])
                    it["orderIndex"] = g.get("orderIndex", 0)
                    it["conflictGroup"] = g.get("conflictGroup")
                    it["epicId"] = g.get("epicId")
                    it["parent"] = g.get("parent")
                    decomposed.append(it["id"])
            existing2 = {it.get("id") for it in s2.get("items", [])}
            for t in tasks:
                if t["id"] not in existing2 and t.get("parent"):
                    s2["items"].append({
                        "id": t["id"], "title": t.get("title", t["id"]),
                        "proposal": t.get("proposal", ""), "status": "pending", "attempts": 0,
                        "branch": None, "touches": t.get("touches", []), "source_scan": dirname,
                        "dependsOn": t.get("dependsOn", []), "orderIndex": t.get("orderIndex", 0),
                        "conflictGroup": t.get("conflictGroup"), "epicId": t.get("epicId"),
                        "parent": t.get("parent"),
                    })
            _write_state(s2)
        try:
            project_memory.update_after_scan(ws, scan_dir=dirname, proposals=added_proposals)
        except Exception as exc:
            log.warning("_scan_import: memory update failed (%s)", exc)
    _try_broadcast_state_safe()

    _append_decision(
        "human", "scan-import", dirname, "ok",
        f"+{len(added)} skipped:{len(skipped)} invalid:{invalid_count}",
    )
    return {"ok": True, "added": added, "skipped": skipped, "decomposed": decomposed}


def _scans_import_by_ids(ids: list[str], *, dirname: str | None = None) -> dict[str, Any]:
    """Import selected scan findings (by id) into the work queue — the v1 entry point.

    - With ``dirname``: delegate straight to ``_scan_import`` (full field mapping +
      decompose + idempotent skip-existing).
    - Without ``dirname``: resolve each id by searching every scan's ``results.json``
      (newest first), group the ids by their owning scan, and import per scan.

    Idempotent (``_scan_import`` skips ids already on the board) and never raises on
    empty/missing input: an empty ``ids`` list yields ``{"ok": True, added/skipped: []}``;
    a bad/missing ``dirname`` returns ``_scan_import``'s ``{"ok": False, ...}`` (the route
    maps that to 404).
    """
    clean_ids = [i for i in ids if i]
    if not clean_ids:
        return {"ok": True, "added": [], "skipped": []}

    if dirname:
        return _scan_import(dirname, clean_ids)

    # No dirname: resolve ids across all scans (newest first), grouping by owning scan.
    wanted: set[str] = set(clean_ids)
    by_dir: dict[str, list[str]] = {}
    for entry in _scan_list():
        if not wanted:
            break
        d = entry.get("dir")
        if not isinstance(d, str):
            continue
        res = _load_json(_scans_dir() / d / "results.json")
        if not isinstance(res, dict):
            continue
        here: list[str] = []
        for p in res.get("proposals", []):
            pid = p.get("id")
            if isinstance(pid, str) and pid in wanted:
                here.append(pid)
        if here:
            by_dir[d] = here
            wanted -= set(here)

    added: list[str] = []
    skipped: list[str] = []
    for d, dids in by_dir.items():
        r = _scan_import(d, dids)
        added.extend(r.get("added", []))
        skipped.extend(r.get("skipped", []))
    return {"ok": True, "added": added, "skipped": skipped}
