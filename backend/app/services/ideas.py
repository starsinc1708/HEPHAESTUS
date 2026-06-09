"""Ideas generator + store — Epic 4 (B1).

Generates improvement ideas via an agent, persists them in
<state>/ideas.json, and imports selected ideas into the work queue.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import logging
import pathlib
import re
import time
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.state import _atomic_write, _state_dir, _StateLock

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

log = logging.getLogger("hephaestus.backend.ideas")

_REGISTRY = "ideas.json"
_MAX_KEEP = 500

_IDEAS_RE = re.compile(r"IDEAS_BEGIN\s*(\{.*?\})\s*IDEAS_END", re.DOTALL)


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


class Idea(BaseModel):
    """A generated improvement idea that can be imported into the queue."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    proposal: str = ""
    rationale: str = ""
    category: str = ""
    severity: str = ""
    touches: list[str] = Field(default_factory=list)
    imported: bool = False


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class IdeaStore:
    """Persist Idea records as a rolling JSON registry in the state dir."""

    def _path(self) -> pathlib.Path:
        return _state_dir() / _REGISTRY

    def list(self) -> list[Idea]:
        p = self._path()
        if not p.exists():
            return []
        try:
            raw = p.read_text(encoding="utf-8") or '{"ideas": []}'
            data: Any = json.loads(raw)
            return [Idea.model_validate(i) for i in data.get("ideas", [])]
        except Exception as exc:
            log.warning("IdeaStore.list failed (%s)", exc)
            return []

    def get(self, idea_id: str) -> Idea | None:
        return next((i for i in self.list() if i.id == idea_id), None)

    def put(self, idea: Idea) -> None:
        with _StateLock():
            ideas = [i for i in self.list() if i.id != idea.id]
            ideas.append(idea)
            ideas = ideas[-_MAX_KEEP:]
            payload = json.dumps(
                {"ideas": [i.model_dump(by_alias=True) for i in ideas]},
                indent=2,
                ensure_ascii=False,
            )
            self._path().parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(self._path(), payload)

    def put_many(self, new_ideas: builtins.list[Idea]) -> None:
        """Persist a batch of ideas, replacing any with the same id."""
        with _StateLock():
            existing = self.list()
            by_id = {i.id: i for i in existing}
            for idea in new_ideas:
                by_id[idea.id] = idea
            merged = list(by_id.values())[-_MAX_KEEP:]
            payload = json.dumps(
                {"ideas": [i.model_dump(by_alias=True) for i in merged]},
                indent=2,
                ensure_ascii=False,
            )
            self._path().parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(self._path(), payload)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_ideas_block(text: str) -> list[dict[str, Any]]:
    """Find the LAST IDEAS_BEGIN..IDEAS_END block, parse JSON, return list of idea dicts."""
    matches = list(_IDEAS_RE.finditer(text))
    if not matches:
        return []
    raw = matches[-1].group(1)
    try:
        data: Any = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, dict):
        return []
    ideas = data.get("ideas", [])
    if not isinstance(ideas, list):
        return []
    return [i for i in ideas if isinstance(i, dict)]


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


async def generate_ideas(
    ws: RepoProfile,
    *,
    categories: list[str] | None,
    runner: Any,
    output_path: pathlib.Path | None = None,
) -> list[Idea]:
    """Run the ideas agent and persist the results.

    Steps:
    1. Render ``ideas`` prompt with categories + memory + map context.
    2. Run agent → parse IDEAS block.
    3. Build Idea objects (stable sha1-based ids) → persist via IdeaStore.
    4. Return list.  Never raises — returns [] on any error.
    """
    from app.services import codebase_map, project_memory
    from app.services.prompt_manager import PromptManager

    try:
        repo = pathlib.Path(ws.repo_path)

        # Context excerpts
        memory_excerpt = (project_memory.read_doc(ws, "architecture") or "")[:2000]
        raw_map = codebase_map.read_map(ws)
        map_excerpt = json.dumps(raw_map, ensure_ascii=False)[:1500]

        categories_str = (
            ", ".join(categories) if categories else "performance, quality, security, test"
        )

        pm = PromptManager()
        prompt = (
            pm.render_prompt(
                "ideas",
                {
                    "categories": categories_str,
                    "memory_excerpt": memory_excerpt,
                    "map_excerpt": map_excerpt,
                },
            )
            or ""
        )

        state_dir = _state_dir()
        ideas_dir = state_dir / "ideas-gen"
        ideas_dir.mkdir(parents=True, exist_ok=True)
        prompt_file = ideas_dir / "ideas.prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")
        _default_output = ideas_dir / "ideas.output.jsonl"
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
            log.warning("generate_ideas: agent refused")
            return []

        from app.core.events import extract_assistant_text

        final_text = effective_output.read_text(encoding="utf-8") if effective_output.exists() else ""
        raw_ideas = _parse_ideas_block(extract_assistant_text(final_text))
        if not raw_ideas:
            log.warning("generate_ideas: no/invalid IDEAS block")
            return []

        ideas: list[Idea] = []
        for item in raw_ideas:
            title = str(item.get("title", ""))
            if not title:
                continue
            idea_id = "idea-" + hashlib.sha1(
                (title + str(time.time())).encode()
            ).hexdigest()[:8]
            ideas.append(
                Idea(
                    id=idea_id,
                    title=title,
                    proposal=str(item.get("proposal", "")),
                    rationale=str(item.get("rationale", "")),
                    category=str(item.get("category", "")),
                    severity=str(item.get("severity", "")),
                    touches=list(item.get("touches", []) or []),
                )
            )

        IdeaStore().put_many(ideas)
        return ideas
    except Exception as exc:
        log.warning("generate_ideas failed (%s) — returning []", exc)
        return []


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------


def import_ideas(ids: list[str]) -> dict[str, Any]:
    """Import selected ideas into the work queue and mark them as imported.

    Returns ``{"added": [<id>, ...]}``.
    """
    from app.core.queue import add_proposals_to_queue

    store = IdeaStore()
    all_ideas = store.list()
    by_id = {i.id: i for i in all_ideas}

    props: list[dict[str, Any]] = []
    added_ids: list[str] = []

    for idea_id in ids:
        idea = by_id.get(idea_id)
        if idea is None:
            log.warning("import_ideas: id %r not found", idea_id)
            continue
        props.append(
            {
                "id": idea.id,
                "title": idea.title,
                "proposal": idea.proposal,
                "rationale": idea.rationale,
                "acceptance": "",
                "touches": idea.touches,
                "category": idea.category,
                "severity": idea.severity,
            }
        )
        idea.imported = True
        added_ids.append(idea.id)

    if props:
        add_proposals_to_queue(props, source="ideas")

    # Persist imported=True flags
    updated = [by_id[i] for i in added_ids if i in by_id]
    if updated:
        store.put_many(updated)

    return {"added": added_ids}
