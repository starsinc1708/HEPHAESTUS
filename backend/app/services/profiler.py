"""Profiler — onboarding agent: detect stack, run agent, write memory (D4+D6)."""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any

from pydantic import BaseModel

from app.models.workspace import RepoProfile, VerifySource
from app.services.opencode_runner import AgentRunner

log = logging.getLogger("hephaestus.backend.profiler")


class ProfilerOutput(BaseModel):
    tech_stack: list[str] = []
    verify_commands: list[str] = []
    architecture_md: str = ""
    conventions_md: str = ""
    tech_debt_md: str = ""
    base_branch: str | None = None


class Profiler:
    def __init__(self, ws: RepoProfile, runner: AgentRunner) -> None:
        self.ws = ws
        self.runner = runner

    @staticmethod
    def _parse_output(text: str) -> ProfilerOutput:
        """Extract the LAST balanced {...} block and parse it; blank on failure."""
        last: str | None = None
        depth = 0
        start = -1
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                if depth > 0:
                    depth -= 1
                    if depth == 0 and start >= 0:
                        last = text[start : i + 1]
        if last is None:
            return ProfilerOutput()
        try:
            data = json.loads(last)
            return ProfilerOutput.model_validate(data)
        except Exception:
            log.warning("profiler output not valid JSON — writing blanks")
            return ProfilerOutput()

    async def onboard(self) -> ProfilerOutput:
        from app.core.workspaces import registry
        from app.services.doc_reader import DocReader
        from app.services.project_memory import ProjectMemory

        # Deterministic context from DocReader
        dr = DocReader(pathlib.Path(self.ws.repo_path))
        try:
            tech_stack = dr.detect_tech_stack()
        except Exception:
            log.debug("profiler: detect_tech_stack failed", exc_info=True)
            tech_stack = []

        # Read prompt template from prompts/profiler.md
        prompt_file = pathlib.Path(__file__).resolve().parents[2] / "prompts" / "profiler.md"
        try:
            template = prompt_file.read_text(encoding="utf-8")
        except Exception:
            log.debug("profiler: failed to read prompt template", exc_info=True)
            template = "Analyze the repository and return the required JSON object."

        prompt = (
            template.replace("{{tech_stack}}", ", ".join(tech_stack))
            .replace("{{structure}}", "")
            .replace("{{readme}}", "")
        )

        state_dir = registry.state_dir(self.ws)
        state_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = state_dir / "profiler-prompt.md"
        prompt_path.write_text(prompt, encoding="utf-8")
        out_path = state_dir / "output.profiler.jsonl"

        await self.runner.run(
            self.ws.agents.primary,
            prompt_file=prompt_path,
            cwd=self.ws.repo_path,
            output_path=out_path,
            timeout_sec=self.ws.verify_timeout_sec,
            use_models=self.ws.agents.use_models,
        )
        raw = out_path.read_text(encoding="utf-8", errors="replace") if out_path.exists() else ""
        parsed = self._parse_output(raw)

        # Deterministic fallback: if profiler agent returned no verify commands,
        # use the detector.
        if not parsed.verify_commands:
            from app.services.verify_detect import detect_verify_commands
            parsed.verify_commands = detect_verify_commands(pathlib.Path(self.ws.repo_path))

        mem = ProjectMemory(self.ws)
        verify_body = "## commands\n```sh\n" + "\n".join(parsed.verify_commands) + "\n```\n"
        mem.write_doc("verify", verify_body, source="profiler")
        mem.write_doc("architecture", parsed.architecture_md or "## Modules\n", source="profiler")
        mem.write_doc("conventions", parsed.conventions_md or "## Style\n", source="profiler")
        mem.write_doc("tech-debt", parsed.tech_debt_md or "## Known debt\n", source="profiler")
        mem.bootstrap_index()

        patch: dict[str, Any] = {"onboarded": True, "verifySource": VerifySource.AGENT.value}
        if parsed.base_branch:
            patch["baseBranch"] = parsed.base_branch
        registry.update(self.ws.id, patch)
        return parsed
