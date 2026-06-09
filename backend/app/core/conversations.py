"""Per-task conversation enumeration — the tree the conversation viewer renders.

`_task_conversations(item_id)` returns the task's iterations and, per iteration, the
stages (implement / validate) × agent-runs (conversation streams) with metadata. Each
agent's ``stream`` value is EXACTLY the relative path (no ``.jsonl`` suffix) that the B2
endpoint ``GET /api/iter/{dir}/conversation?stream=...`` accepts, so the two round-trip.

Disk layout (see app/orchestrator/fsm.py::_snapshot_revision + app/core/validators.py):
- Implementer: ``output.primary.jsonl`` (canonical/latest), ``output.primary.r{N}.jsonl``
  (archived revisions), optional ``output.fallback.jsonl``.
- Validators/arbiters/final, canonical: ``validation/layer1/<lens>.jsonl``,
  ``validation/layer2/arbiter-<i>.jsonl``, ``validation/layer3/final.jsonl`` (each with a
  parsed-verdict sibling ``.json``: layer1/2 field ``verdict``, layer3 field ``gate``).
- Archived revisions: ``validation.r{N}/layer1/<lens>.jsonl`` etc.

Everything is best-effort: a malformed file or missing sibling never raises — per-file
work is wrapped so one bad stream can't abort the whole enumeration.
"""

from __future__ import annotations

import json
import logging
import pathlib
import re
import time
from typing import Any

from app.core.events import _sum_usage
from app.core.helpers import _load_json
from app.core.state import _read_state, _state_dir

log = logging.getLogger("hephaestus.backend.conversations")

_PRIMARY_REV_RE = re.compile(r"^output\.primary\.r(\d+)\.jsonl$")
_VALIDATION_REV_RE = re.compile(r"^validation\.r(\d+)$")

# Read no more than this many non-empty lines when peeking for a model id.
_MODEL_PEEK_LINES = 40


def _count_lines(path: pathlib.Path) -> int:
    """Cheap count of non-empty lines in a JSONL file. Never raises → 0 on error."""
    n = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.strip():
                    n += 1
    except Exception:
        log.debug("_count_lines failed for %s", path, exc_info=True)
        return 0
    return n


def _peek_model(path: pathlib.Path) -> str | None:
    """Peek the first model id from a JSONL stream. Reads up to ~40 non-empty lines,
    json.loads each, returns the first non-empty str of
    obj['message']['model'] / obj.get('model') / obj['part']['model']. Never raises."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            seen = 0
            for raw in f:
                line = raw.strip()
                if not line:
                    continue
                seen += 1
                if seen > _MODEL_PEEK_LINES:
                    break
                try:
                    obj = json.loads(line)
                except Exception:
                    log.debug("failed to parse conversation line in _peek_model", exc_info=True)
                    continue
                if not isinstance(obj, dict):
                    continue
                candidates: list[Any] = []
                msg = obj.get("message")
                if isinstance(msg, dict):
                    candidates.append(msg.get("model"))
                candidates.append(obj.get("model"))
                part = obj.get("part")
                if isinstance(part, dict):
                    candidates.append(part.get("model"))
                for c in candidates:
                    if isinstance(c, str) and c:
                        return c
    except Exception:
        log.debug("_peek_model failed for %s", path, exc_info=True)
        return None
    return None


def _verdict_from_sibling(jsonl_path: pathlib.Path, *, field: str) -> str:
    """Read the parsed-verdict sibling (``<stem>.json``) and return its `field` as a str.
    Missing sibling / malformed file → "". Never raises."""
    sibling = jsonl_path.with_suffix(".json")
    if not sibling.exists():
        return ""
    obj = _load_json(sibling)
    if isinstance(obj, dict):
        v = obj.get(field)
        if isinstance(v, str):
            return v
        if v is not None:
            return str(v)
    return ""


def _agent_record(
    iter_dir: pathlib.Path,
    jsonl_path: pathlib.Path,
    *,
    stream: str,
    role: str,
    revision: int,
    current: bool,
    status: str,
) -> dict[str, Any]:
    """Build one agent-run dict. Best-effort metadata (messages/cost/model)."""
    try:
        messages = _count_lines(jsonl_path)
    except Exception:
        log.debug("failed to count lines for %s", jsonl_path, exc_info=True)
        messages = 0
    try:
        cost_usd = round(float(_sum_usage(jsonl_path).get("cost_usd", 0.0)), 5)
    except Exception:
        log.debug("failed to sum cost for %s", jsonl_path, exc_info=True)
        cost_usd = 0.0
    try:
        model = _peek_model(jsonl_path)
    except Exception:
        log.debug("failed to peek model for %s", jsonl_path, exc_info=True)
        model = None
    return {
        "stream": stream,
        "role": role,
        "revision": revision,
        "current": current,
        "model": model,
        "status": status,
        "messages": messages,
        "costUsd": cost_usd,
    }


def _implement_stage(d: pathlib.Path, item: dict[str, Any]) -> dict[str, Any]:
    """Implementer runs across revisions: archived ``output.primary.r{N}`` (current=False,
    status needs_revision) + canonical ``output.primary`` (current=True, status=item.status)
    + optional ``output.fallback`` (treated as a current implementer run)."""
    item_status = str(item.get("status") or "")
    agents: list[dict[str, Any]] = []
    max_archived = -1
    # Archived primary revisions.
    for p in d.glob("output.primary.r*.jsonl"):
        m = _PRIMARY_REV_RE.match(p.name)
        if not m:
            continue
        try:
            n = int(m.group(1))
        except ValueError:
            log.debug("failed to parse revision number from %s", p.name, exc_info=True)
            continue
        max_archived = max(max_archived, n)
        try:
            agents.append(
                _agent_record(
                    d, p, stream=f"output.primary.r{n}", role="implementer",
                    revision=n, current=False, status="needs_revision",
                )
            )
        except Exception:
            log.warning("implement archive enumerate failed for %s", p, exc_info=True)
    # Canonical primary (latest revision).
    canonical_rev = (max_archived + 1) if max_archived >= 0 else 0
    primary = d / "output.primary.jsonl"
    if primary.exists():
        try:
            agents.append(
                _agent_record(
                    d, primary, stream="output.primary", role="implementer",
                    revision=canonical_rev, current=True, status=item_status,
                )
            )
        except Exception:
            log.warning("implement canonical enumerate failed for %s", primary, exc_info=True)
    # Fallback (used when primary refused) — same revision as canonical primary.
    fallback = d / "output.fallback.jsonl"
    try:
        if fallback.exists() and fallback.stat().st_size > 0:
            agents.append(
                _agent_record(
                    d, fallback, stream="output.fallback", role="implementer",
                    revision=canonical_rev, current=True, status=item_status,
                )
            )
    except Exception:
        log.warning("implement fallback enumerate failed for %s", fallback, exc_info=True)
    # archives before canonical: sort by (revision, current).
    agents.sort(key=lambda a: (a["revision"], a["current"]))
    return {"stage": "implement", "agents": agents}


def _validation_root_agents(
    d: pathlib.Path, root: pathlib.Path, *, revision: int, current: bool
) -> list[dict[str, Any]]:
    """Enumerate the agent-runs inside ONE validation root (canonical ``validation`` or an
    archived ``validation.r{N}``). Maps only ``.jsonl`` files to streams."""
    agents: list[dict[str, Any]] = []
    # layer1: validator lenses
    l1 = root / "layer1"
    if l1.is_dir():
        for p in sorted(l1.glob("*.jsonl")):
            try:
                stem = p.name[: -len(".jsonl")]
                status = _verdict_from_sibling(p, field="verdict")
                agents.append(
                    _agent_record(
                        d, p, stream=f"{root.name}/layer1/{stem}",
                        role=f"validator:{stem}", revision=revision, current=current, status=status,
                    )
                )
            except Exception:
                log.warning("validation layer1 enumerate failed for %s", p, exc_info=True)
    # layer2: arbiters
    l2 = root / "layer2"
    if l2.is_dir():
        for p in sorted(l2.glob("arbiter-*.jsonl")):
            try:
                stem = p.name[: -len(".jsonl")]
                status = _verdict_from_sibling(p, field="verdict")
                agents.append(
                    _agent_record(
                        d, p, stream=f"{root.name}/layer2/{stem}",
                        role="arbiter", revision=revision, current=current, status=status,
                    )
                )
            except Exception:
                log.warning("validation layer2 enumerate failed for %s", p, exc_info=True)
    # layer3: final gate
    l3 = root / "layer3"
    if l3.is_dir():
        for p in sorted(l3.glob("*.jsonl")):
            try:
                stem = p.name[: -len(".jsonl")]
                status = _verdict_from_sibling(p, field="gate")
                agents.append(
                    _agent_record(
                        d, p, stream=f"{root.name}/layer3/{stem}",
                        role="final", revision=revision, current=current, status=status,
                    )
                )
            except Exception:
                log.warning("validation layer3 enumerate failed for %s", p, exc_info=True)
    return agents


def _validate_stage(d: pathlib.Path) -> dict[str, Any]:
    """Validate runs in revision order: archived ``validation.r0``, ``validation.r1``, …
    then canonical ``validation`` (current=True)."""
    agents: list[dict[str, Any]] = []
    # Archived validation roots, in revision order.
    archived: list[tuple[int, pathlib.Path]] = []
    for p in d.glob("validation.r*"):
        if not p.is_dir():
            continue
        m = _VALIDATION_REV_RE.match(p.name)
        if not m:
            continue
        try:
            archived.append((int(m.group(1)), p))
        except ValueError:
            log.debug("failed to parse validation revision number from %s", p.name, exc_info=True)
            continue
    archived.sort(key=lambda t: t[0])
    max_archived = -1
    for n, root in archived:
        max_archived = max(max_archived, n)
        agents.extend(_validation_root_agents(d, root, revision=n, current=False))
    # Canonical validation root.
    canonical_rev = (max_archived + 1) if max_archived >= 0 else 0
    canonical = d / "validation"
    if canonical.is_dir():
        agents.extend(_validation_root_agents(d, canonical, revision=canonical_rev, current=True))
    return {"stage": "validate", "agents": agents}


def _iter_created_at(d: pathlib.Path) -> str:
    """ISO timestamp from run-tag mtime if present, else the dir mtime."""
    try:
        rt = d / "run-tag"
        mtime = rt.stat().st_mtime if rt.exists() else d.stat().st_mtime
    except Exception:
        log.debug("_iter_created_at stat failed for %s", d, exc_info=True)
        mtime = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(mtime))


def _enumerate_iter(d: pathlib.Path, item: dict[str, Any]) -> dict[str, Any]:
    """Build the iteration dict: createdAt + implement/validate stages + attempts."""
    implement = _implement_stage(d, item)
    validate = _validate_stage(d)
    # attempts = number of implementer runs (one per revision attempt).
    attempts = len(implement["agents"])
    stages: list[dict[str, Any]] = []
    if implement["agents"]:
        stages.append(implement)
    if validate["agents"]:
        stages.append(validate)
    return {
        "dir": d.name,
        "createdAt": _iter_created_at(d),
        "attempts": attempts,
        "stages": stages,
    }


def _task_conversations(item_id: str) -> dict[str, Any]:
    """Enumerate a task's iterations × stages × agent-runs (conversation streams).

    Returns ``{"ok": True, "itemId": ..., "iterations": [...]}`` or, when the task id is
    unknown, ``{"ok": False, "error": "task not found"}``.
    """
    s = _read_state()
    item = next((it for it in s.get("items", []) if it.get("id") == item_id), None)
    if item is None:
        return {"ok": False, "error": "task not found"}

    iterations: list[dict[str, Any]] = []
    sd = _state_dir()
    if sd.exists():
        for d in sorted(sd.glob("iter-*")):
            if not d.is_dir():
                continue
            # MIRROR app/core/iters.py::_task_view matching: item.lastIter == d.name, OR
            # (fallback) commit-msg.txt exists and contains the item id.
            matches = item.get("lastIter") == d.name
            if not matches:
                cm = d / "commit-msg.txt"
                if cm.exists():
                    try:
                        if item_id in cm.read_text(errors="replace"):
                            matches = True
                    except Exception:
                        log.debug("failed to read commit-msg.txt in %s", d, exc_info=True)
                        pass
            if not matches:
                continue
            try:
                iterations.append(_enumerate_iter(d, item))
            except Exception:
                log.warning("enumerate iter failed for %s", d, exc_info=True)
    return {"ok": True, "itemId": item_id, "iterations": iterations}
