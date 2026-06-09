from __future__ import annotations

import pathlib
from typing import Any

import pytest

from app.models.workspace import AgentRef, AgentsConfig, RepoProfile
from app.services import project_memory as pm
from app.services.lessons import extract_lesson
from app.services.prompt_manager import PromptManager


def _ws(repo_path: str) -> RepoProfile:
    return RepoProfile(
        id="9f3a1c20e4b57d61",
        name="demo",
        repo_path=repo_path,
        memory_dir=".hephaestus/memory",
        agents=AgentsConfig(
            primary=AgentRef(provider="p", model="m"),
            fallback=AgentRef(provider="p", model="m"),
        ),
    )


class MockAgentRunner:
    def __init__(self, response_text: str):
        self.response_text = response_text

    async def run(
        self,
        ref: AgentRef,
        *,
        prompt_file: pathlib.Path,
        cwd: str,
        output_path: pathlib.Path,
        timeout_sec: int,
        use_models: bool = False,
    ) -> Any:
        import json
        # Emit a text event like the real opencode/claude CLIs
        output_path.write_text(json.dumps({"type": "text", "text": self.response_text}) + "\n")
        from app.services.opencode_runner import AgentResult
        return AgentResult(
            exit_code=0,
            refused=False,
            output_path=output_path,
            agent_label="primary",
        )


def test_new_lesson_added(tmp_path: pathlib.Path) -> None:
    ws = _ws(str(tmp_path))
    added = pm.add_lesson(ws, lesson="ALWAYS keep the workspace clean.", task_id="task-1")
    assert added is True

    body = pm.read_doc(ws, "conventions")
    assert body is not None
    assert "ALWAYS keep the workspace clean." in body
    assert "## lesson from task-1" in body


def test_dedup_similar_lessons(tmp_path: pathlib.Path) -> None:
    ws = _ws(str(tmp_path))
    added1 = pm.add_lesson(ws, lesson="ALWAYS validate input parameters.", task_id="task-1")
    assert added1 is True

    # Same exact lesson
    added2 = pm.add_lesson(ws, lesson="ALWAYS validate input parameters.", task_id="task-2")
    assert added2 is False

    # Highly similar lesson (fuzzy match ratio >= 0.7)
    added3 = pm.add_lesson(ws, lesson="ALWAYS validate parameters.", task_id="task-3")
    assert added3 is False

    # Different lesson
    added4 = pm.add_lesson(ws, lesson="NEVER commit credentials.", task_id="task-4")
    assert added4 is True


def test_lesson_cap(tmp_path: pathlib.Path) -> None:
    ws = _ws(str(tmp_path))
    for i in range(200):
        pm.add_lesson(ws, lesson=f"ALWAYS use feature number {i}.", task_id=f"task-{i}")

    body = pm.read_doc(ws, "conventions")
    assert body is not None
    # Verify that the document stays within the line cap (150 lines)
    assert len(body.splitlines()) <= 150


@pytest.mark.anyio
async def test_skip_trivial(tmp_path: pathlib.Path) -> None:
    ws = _ws(str(tmp_path))
    runner = MockAgentRunner(response_text="SKIP")

    # Mock prompts dir so the template is found
    prompts_dir = pathlib.Path(ws.repo_path) / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    template_path = prompts_dir / "lesson-extract.md"
    template_path.write_text("## Blocking\n{{blocking}}\n## Fix\n{{fix_summary}}")

    import app.config
    original_loop_home = app.config.LOOP_HOME
    app.config.LOOP_HOME = pathlib.Path(ws.repo_path)

    try:
        lesson = await extract_lesson(
            blocking_issues=["Trivial typo"],
            fix_summary="Fixed spelling",
            runner=runner,
            ws=ws,
        )
        assert lesson is None
    finally:
        app.config.LOOP_HOME = original_loop_home


@pytest.mark.anyio
async def test_extract_valid_lesson(tmp_path: pathlib.Path) -> None:
    ws = _ws(str(tmp_path))
    runner = MockAgentRunner(response_text="ALWAYS use raw string for regex.")

    # Mock prompts dir so the template is found
    prompts_dir = pathlib.Path(ws.repo_path) / "prompts"
    prompts_dir.mkdir(parents=True, exist_ok=True)
    template_path = prompts_dir / "lesson-extract.md"
    template_path.write_text("## Blocking\n{{blocking}}\n## Fix\n{{fix_summary}}")

    import app.config
    original_loop_home = app.config.LOOP_HOME
    app.config.LOOP_HOME = pathlib.Path(ws.repo_path)

    try:
        lesson = await extract_lesson(
            blocking_issues=["Regex escapes warning"],
            fix_summary="Switched pattern to r'pattern'",
            runner=runner,
            ws=ws,
        )
        assert lesson == "ALWAYS use raw string for regex."
    finally:
        app.config.LOOP_HOME = original_loop_home


def test_lesson_appears_in_prompt(tmp_path: pathlib.Path) -> None:
    ws = _ws(str(tmp_path))
    pm.add_lesson(ws, lesson="ALWAYS check status code.", task_id="task-1")

    # Write a dummy system-prefix.md in override prompts so PromptManager reads it
    prompts_override = pathlib.Path(ws.repo_path) / ".hephaestus" / "prompts"
    prompts_override.mkdir(parents=True, exist_ok=True)
    (prompts_override / "system-prefix.md").write_text("System instructions")

    pm_mgr = PromptManager(override_dir=prompts_override, ws=ws)
    prompt = pm_mgr.build_task_prompt(item={"title": "My Task"})

    assert "ALWAYS check status code." in prompt
    assert "## Project Conventions & Lessons" in prompt
