"""Prompt builder — construct the opencode task prompt from item + workspace context."""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

log = logging.getLogger("hephaestus.orchestrator")


def build_task_prompt(
    item: dict[str, Any],
    ws: RepoProfile | None,
    iter_dir: pathlib.Path | None,
) -> str | None:
    """Build the prompt file for opencode."""
    from app.services.doc_reader import DocReader
    from app.services.prompt_manager import PromptManager

    override_dir: pathlib.Path | None = None
    if ws is not None:
        override_dir = pathlib.Path(ws.repo_path) / ".hephaestus" / "prompts"
    pm = PromptManager(override_dir=override_dir, ws=ws)
    dr = DocReader()

    try:
        repo_context = dr.get_context_summary()
    except Exception:
        log.warning(
            "repo context unavailable for %s — building prompt without it",
            item.get("id", "?"),
            exc_info=True,
        )
        repo_context = ""

    prompt = pm.build_task_prompt(item, repo_context)

    if iter_dir:
        (iter_dir / "prompt.md").write_text(prompt, encoding="utf-8")

    return prompt
