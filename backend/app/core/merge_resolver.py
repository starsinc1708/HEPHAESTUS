"""Conflict-marker detection and AI merge-resolver (Epic 1)."""

from __future__ import annotations

import pathlib
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile
    from app.services.opencode_runner import AgentResult


def has_conflict_markers(text: str) -> bool:
    """Return True if *text* contains any git conflict-marker lines."""
    for line in text.splitlines():
        if line.startswith("<<<<<<<") or line.startswith(">>>>>>>") or line == "=======":
            return True
    return False


def _read_prompt_template() -> str:
    from app.config import LOOP_HOME

    path = LOOP_HOME / "prompts" / "merge-resolver.md"
    return path.read_text(encoding="utf-8")


def build_resolver_prompt(*, item: dict[str, Any], conflicts: list[str]) -> str:
    """Build the resolver prompt by injecting item intent + conflict file list."""
    intent = "\n".join(
        f"- {k}: {item.get(k)}" for k in ("proposal", "why", "acceptance") if item.get(k)
    ) or "- (no intent recorded)"
    files = "\n".join(f"- {f}" for f in conflicts)
    template = _read_prompt_template()
    return template.replace("{intent}", intent).replace("{files}", files)


# ---------------------------------------------------------------------------
# ResolveOutcome + MergeResolver
# ---------------------------------------------------------------------------


class ResolveOutcome(BaseModel):
    ok: bool
    agent_exit: int
    output_path: pathlib.Path


class MergeResolver:
    """Runs an AI agent to resolve merge conflicts inside a worktree."""

    def __init__(
        self,
        ws: RepoProfile,
        *,
        run_agent: Callable[
            [pathlib.Path, str, pathlib.Path],
            Awaitable[AgentResult],
        ]
        | None = None,
    ) -> None:
        self.ws = ws
        self._run_agent = run_agent  # async (prompt_file, cwd, output_path) -> AgentResult

    async def resolve(
        self,
        *,
        worktree_cwd: str,
        conflicts: list[str],
        item: dict[str, Any],
        job_dir: pathlib.Path | str,
        timeout_sec: int,
    ) -> ResolveOutcome:
        prompt = build_resolver_prompt(item=item, conflicts=conflicts)
        job_dir_path = pathlib.Path(job_dir)
        job_dir_path.mkdir(parents=True, exist_ok=True)
        prompt_file = job_dir_path / "resolve.prompt.md"
        prompt_file.write_text(prompt, encoding="utf-8")
        output_path = job_dir_path / "output.resolve.jsonl"
        if self._run_agent is not None:
            result = await self._run_agent(prompt_file, worktree_cwd, output_path)
        else:
            from app.core.process import pm
            from app.services.opencode_runner import AgentRunner

            ref = self.ws.agents.merge or self.ws.agents.primary
            runner = AgentRunner(
                pm,
                engine=self.ws.engine,
                env=self.ws.engine_env,
                profiles=self.ws.engine_profiles,
            )
            result = await runner.run(
                ref,
                prompt_file=prompt_file,
                cwd=worktree_cwd,
                output_path=output_path,
                timeout_sec=timeout_sec,
                use_models=self.ws.agents.use_models,
            )
        return ResolveOutcome(
            ok=(result.exit_code == 0 and not result.refused),
            agent_exit=result.exit_code,
            output_path=output_path,
        )
