"""Decomposer — proposals → Task-dicts with depends_on / order_index / conflict_group (D5)."""
from __future__ import annotations

import json
import logging
import pathlib
import re
from typing import TYPE_CHECKING, Any, Protocol

from app.core.task_graph import assign_conflict_groups, build_graph, detect_cycles, topo_order

if TYPE_CHECKING:
    from app.models.workspace import AgentRef, RepoProfile


class _DecomposeRunner(Protocol):
    async def run(self, ref: object, *, prompt_file: pathlib.Path, cwd: str,
                  output_path: pathlib.Path, timeout_sec: int) -> object: ...

log = logging.getLogger("hephaestus.backend.decompose")

_BLOCK_RE = re.compile(r"DECOMPOSE_BEGIN\s*(\{.*?\})\s*DECOMPOSE_END", re.DOTALL)


def _parse_decompose_block(text: str) -> dict[str, Any] | None:
    """Find the LAST DECOMPOSE_BEGIN..END, json.loads the middle. Bad/absent → None."""
    matches = list(_BLOCK_RE.finditer(text))
    if not matches:
        return None
    raw = matches[-1].group(1)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "tasks" not in data:
        return None
    return data


def _fallback_projection(proposals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """1:1 projection: each proposal → Task without depends_on/epic. order_index = tail."""
    out: list[dict[str, Any]] = []
    for i, p in enumerate(proposals):
        out.append(
            {
                "id": p["id"],
                "dependsOn": [],
                "epicId": None,
                "parent": None,
                "orderIndex": i,
            }
        )
    return out


def _expand_tasks(proposals: list[dict[str, Any]], llm_tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge LLM output with proposals by id; expand epics into parent + subtasks."""
    by_pid = {p["id"]: p for p in proposals}
    llm_by_id = {t.get("id"): t for t in llm_tasks if t.get("id")}
    result: list[dict[str, Any]] = []
    for pid, prop in by_pid.items():
        spec = llm_by_id.get(pid, {})
        if spec.get("epic") and spec.get("subtasks"):
            subs = spec["subtasks"]
            parent_touches: list[str] = []
            for sub in subs:
                parent_touches.extend(sub.get("touches", []) or [])
            result.append(
                {"id": pid, "dependsOn": [], "epicId": None, "parent": None, "touches": parent_touches,
                 "complexity": spec.get("complexity")}
            )
            for sub in subs:
                sub_id = f"{pid}-{sub['id']}"
                dep = [f"{pid}-{d}" for d in (sub.get("dependsOn") or [])]
                result.append(
                    {
                        "id": sub_id,
                        "dependsOn": dep,
                        "epicId": pid,
                        "parent": pid,
                        "touches": sub.get("touches", []) or [],
                        "title": sub.get("title", sub_id),
                        "proposal": sub.get("proposal", ""),
                        "complexity": sub.get("complexity"),
                    }
                )
        else:
            result.append(
                {
                    "id": pid,
                    "dependsOn": list(spec.get("dependsOn") or []),
                    "epicId": None,
                    "parent": None,
                    "touches": prop.get("touches", []) or [],
                    "complexity": spec.get("complexity"),
                }
            )
    return result


def _sanitize_graph(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop dangling deps and break LLM-introduced cycles (last edge of each cycle)."""
    ids = {t["id"] for t in tasks}
    for t in tasks:
        t["dependsOn"] = [d for d in t["dependsOn"] if d in ids and d != t["id"]]
    g = build_graph(tasks)
    cycles = detect_cycles(g)
    if cycles:
        log.warning("decompose: LLM introduced %d cycle(s); breaking last edge each", len(cycles))
        for cyc in cycles:
            last, first = cyc[-1], cyc[0]
            for t in tasks:
                if t["id"] == last and first in t["dependsOn"]:
                    t["dependsOn"].remove(first)
    # Recompute the inverse blocks edges so decompose-produced items carry correct blocks.
    from app.core.deps import recompute_blocks

    recompute_blocks(tasks)
    return tasks


async def decompose_proposals(
    ws: RepoProfile,
    proposals: list[dict[str, Any]],
    *,
    scan_dir: str,
    runner: _DecomposeRunner | None,
    decomposer_ref: AgentRef | None = None,
) -> list[dict[str, Any]]:
    """Build Task-dicts (camelCase-ready) from reducer proposals. Never writes state."""

    from app.services import project_memory
    from app.services.prompt_manager import PromptManager

    if not proposals:
        return []

    pm = PromptManager()
    memory_excerpt = (project_memory.read_doc(ws, "architecture") or "")[:2000]
    prompt = pm.render_prompt(
        "scan-decomposer",
        {
            "proposals_json": json.dumps(proposals, ensure_ascii=False, indent=2),
            "repo_path": ws.repo_path,
            "memory_excerpt": memory_excerpt,
        },
    ) or ""
    # Artifacts go under the workspace's own scan dir (where the worker wrote results),
    # not the legacy global STATE_DIR.
    scan_path = pathlib.Path(ws.repo_path) / ".hephaestus" / "state" / "scans" / scan_dir
    scan_path.mkdir(parents=True, exist_ok=True)
    prompt_file = scan_path / "decompose.prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    output_path = scan_path / "decompose.output.jsonl"

    if runner is None:
        log.warning("decompose: no runner provided — 1:1 fallback projection")
        return _fallback_projection(proposals)

    ref = decomposer_ref or getattr(ws.agents, "planner", None) or ws.agents.primary
    try:
        await runner.run(
            ref,
            prompt_file=prompt_file,
            cwd=ws.repo_path,
            output_path=output_path,
            timeout_sec=600,
        )
        final_text = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
    except Exception as exc:
        log.warning("decompose: runner failed (%s) — using fallback projection", exc)
        final_text = ""

    from app.core.events import extract_assistant_text

    parsed = _parse_decompose_block(extract_assistant_text(final_text))
    if parsed is None:
        log.warning("decompose: no/invalid DECOMPOSE block — 1:1 fallback")
        return _fallback_projection(proposals)

    try:
        llm_tasks = parsed.get("tasks", [])
        complexity_by_id = {t.get("id"): t.get("complexity") for t in llm_tasks}
        tasks = _expand_tasks(proposals, llm_tasks)
        tasks = _sanitize_graph(tasks)
        groups = assign_conflict_groups(tasks)
        g = build_graph(tasks)
        order = topo_order(g)
        pos = {tid: i for i, tid in enumerate(order)}
        for t in tasks:
            t["conflictGroup"] = groups.get(t["id"])
            t["orderIndex"] = pos.get(t["id"], 0)
            t.setdefault("complexity", complexity_by_id.get(t["id"]))
        return tasks
    except Exception as exc:  # malformed LLM graph (deep chains/cycles) → safe 1:1 fallback
        log.warning("decompose: graph build failed (%s) — 1:1 fallback projection", exc)
        return _fallback_projection(proposals)
