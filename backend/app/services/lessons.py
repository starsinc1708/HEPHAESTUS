from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING

from app.config import LOOP_HOME
from app.core.events import extract_assistant_text
from app.core.workspaces import registry

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile
    from app.services.opencode_runner import AgentRunner

log = logging.getLogger("hephaestus.backend.lessons")


async def extract_lesson(
    blocking_issues: list[str],
    fix_summary: str,
    runner: AgentRunner,
    ws: RepoProfile,
) -> str | None:
    """Distill a blocking issue + its fix into a one-line convention rule.

    Uses a lightweight LLM call with a focused prompt.
    Returns None if dedup detects an existing similar rule or if skip requested.
    """
    prompt_file = LOOP_HOME / "prompts" / "lesson-extract.md"
    if not prompt_file.exists():
        log.warning("lesson-extract prompt template not found at %s", prompt_file)
        return None

    template = prompt_file.read_text(encoding="utf-8")

    blocking_str = "\n".join(f"- {issue}" for issue in blocking_issues)
    prompt = (
        template.replace("{{blocking}}", blocking_str)
        .replace("{{fix_summary}}", fix_summary)
    )

    state_dir = registry.state_dir(ws)
    state_dir.mkdir(parents=True, exist_ok=True)

    lessons_dir = state_dir / "lessons-gen"
    lessons_dir.mkdir(parents=True, exist_ok=True)

    prompt_path = lessons_dir / "lesson-extract.prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")

    out_path = lessons_dir / "lesson-extract.output.jsonl"
    if out_path.exists():
        with contextlib.suppress(Exception):
            out_path.unlink()

    ref = ws.agents.primary

    result = await runner.run(
        ref,
        prompt_file=prompt_path,
        cwd=ws.repo_path,
        output_path=out_path,
        timeout_sec=300,
        use_models=ws.agents.use_models,
    )

    if result.refused:
        log.warning("extract_lesson: agent refused")
        return None

    if not out_path.exists():
        log.warning("extract_lesson: output file was not created")
        return None

    raw_output = out_path.read_text(encoding="utf-8", errors="replace")
    lesson_candidate = extract_assistant_text(raw_output).strip()

    # Normalize response format
    lesson = lesson_candidate
    if lesson.startswith("`") and lesson.endswith("`"):
        lesson = lesson.strip("`").strip()
    if lesson.startswith('"') and lesson.endswith('"'):
        lesson = lesson.strip('"').strip()
    if lesson.startswith("- "):
        lesson = lesson[2:].strip()

    if lesson.upper() == "SKIP" or "SKIP" in lesson.upper()[:6]:
        return None

    return lesson
