"""Codebase map — Epic 4 (A1).

Builds and persists a file-to-purpose index under
<repo>/.hephaestus/memory/codebase_map.json.
"""

from __future__ import annotations

import json
import logging
import pathlib
import re
import time
from typing import TYPE_CHECKING, Any

from app.core.helpers import _run

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

log = logging.getLogger("hephaestus.backend.codebase_map")

_MAP_RE = re.compile(r"MAP_BEGIN\s*(\{.*?\})\s*MAP_END", re.DOTALL)

_EXCLUDE_FRAGMENTS = ("node_modules", ".venv", "/dist/", ".git/")


def _parse_map_block(text: str) -> dict[str, str]:
    """Find the LAST MAP_BEGIN..MAP_END block, parse JSON, return inner 'map' or {}."""
    matches = list(_MAP_RE.finditer(text))
    if not matches:
        return {}
    raw = matches[-1].group(1)
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    inner = data.get("map", {})
    if not isinstance(inner, dict):
        return {}
    return {str(k): str(v) for k, v in inner.items()}


async def build_map(
    ws: RepoProfile,
    *,
    runner: Any,
    max_files: int = 400,
    output_path: pathlib.Path | None = None,
) -> dict[str, str]:
    """Build a file→purpose index for the workspace repo.

    Steps:
    1. ``git ls-files`` → filter → cap to max_files.
    2. Render ``codebase-map`` prompt → run agent.
    3. Parse MAP block → write <repo>/.hephaestus/memory/codebase_map.json.
    4. Return the map dict.  Never raises — returns {} on any error.
    """
    from app.services.prompt_manager import PromptManager

    try:
        repo = pathlib.Path(ws.repo_path)
        all_files = _run(["git", "ls-files"], cwd=str(repo), default="").splitlines()
        files = [
            f
            for f in all_files
            if f and not any(frag in f for frag in _EXCLUDE_FRAGMENTS)
        ]
        files = files[:max_files]

        pm = PromptManager()
        prompt = pm.render_prompt("codebase-map", {"files": "\n".join(files)}) or ""

        # Write prompt to a temp location under .hephaestus/state so the runner can pick it up
        state_dir = repo / ".hephaestus" / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = state_dir / "codebase-map.prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")
        _default_output = state_dir / "codebase-map.output.jsonl"
        effective_output = output_path if output_path is not None else _default_output

        ref = ws.agents.primary
        result = await runner.run(
            ref,
            prompt_file=prompt_file,
            cwd=str(repo),
            output_path=effective_output,
            timeout_sec=300,
            use_models=False,
        )
        if result.refused:
            log.warning("build_map: agent refused")
            return {}

        from app.core.events import extract_assistant_text

        final_text = effective_output.read_text(encoding="utf-8") if effective_output.exists() else ""
        file_map = _parse_map_block(extract_assistant_text(final_text))

        # Persist
        memory_dir = repo / ".hephaestus" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "map": file_map,
                "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            },
            indent=2,
            ensure_ascii=False,
        )
        (memory_dir / "codebase_map.json").write_text(payload, encoding="utf-8")
        return file_map
    except Exception as exc:
        log.warning("build_map failed (%s) — returning {}", exc)
        return {}


def read_map(ws: RepoProfile) -> dict[str, str]:
    """Read <repo>/.hephaestus/memory/codebase_map.json and return its 'map'. Returns {} if absent."""
    import pathlib

    p = pathlib.Path(ws.repo_path) / ".hephaestus" / "memory" / "codebase_map.json"
    if not p.exists():
        return {}
    try:
        data: Any = json.loads(p.read_text(encoding="utf-8"))
        inner = data.get("map", {})
        if not isinstance(inner, dict):
            return {}
        return {str(k): str(v) for k, v in inner.items()}
    except Exception as exc:
        log.warning("read_map failed (%s) — returning {}", exc)
        return {}
