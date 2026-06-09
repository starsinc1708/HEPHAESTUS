"""AgentRunner — wraps `opencode run` with provider/model/agent selection (D2, R1/R2).

AgentRunner runs INSIDE a child process (orchestrator/profiler/scan) on that process's own
asyncio event loop. It owns its OWN asyncio.subprocess handle and awaits exactly that handle —
it NEVER touches ProcessManager private fields (_procs/_finalize) and concurrent calls never
share a session_name (each gets a unique output_path). The ``pm`` is kept only for API parity.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import pathlib
import shutil
from typing import IO

from pydantic import BaseModel

from app.core.process import ProcessManager
from app.models.workspace import AgentRef, AgentsConfig, EngineProfile

log = logging.getLogger("hephaestus.backend.opencode")


class AgentResult(BaseModel):
    exit_code: int
    refused: bool
    output_path: pathlib.Path
    agent_label: str


class AgentRunner:
    # Known model params mapped to opencode CLI flags (MODEL-003).
    _OPENCODE_PARAM_FLAGS: dict[str, str] = {
        "temperature": "--temperature",
        "max_tokens": "--max-output-tokens",
        "top_p": "--top-p",
    }

    def __init__(self, pm: ProcessManager, *, engine: str = "opencode",
                 env: dict[str, str] | None = None,
                 profiles: list[EngineProfile] | None = None) -> None:
        self._pm = pm  # parity only; AgentRunner never reads pm internals (R1)
        # Workspace-default engine: "opencode" or "claude" (Claude Code CLI, `claude -p`).
        self._engine = engine or "opencode"
        # Default extra env merged into the agent subprocess.
        self._env = env or {}
        # Named engine profiles a per-role AgentRef may select via engine_profile —
        # lets one workspace mix CLIs/models per role (plan vs implement vs verify).
        self._profiles: dict[str, EngineProfile] = {p.name: p for p in (profiles or [])}

    def _resolve_engine(self, ref: AgentRef) -> tuple[str, dict[str, str]]:
        """Engine + extra env for this ref: its named profile, else the ws default."""
        name = getattr(ref, "engine_profile", None)
        if name and name in self._profiles:
            p = self._profiles[name]
            return (p.engine or "opencode"), dict(p.env)
        return self._engine, {}

    def _label(self, ref: AgentRef, use_models: bool, engine: str) -> str:
        if engine == "claude":
            return f"claude:{ref.model or 'default'}"
        if engine == "codex":
            return f"codex:{ref.model or 'default'}"
        if ref.agent and not use_models:
            return ref.agent
        return f"{ref.provider}/{ref.model}"

    def _append_model_params(self, cmd: list[str], params: dict[str, float | int | str | bool]) -> None:
        """Append known model params as CLI flags; silently skip unknowns."""
        for key, flag in self._OPENCODE_PARAM_FLAGS.items():
            if key in params:
                cmd += [flag, str(params[key])]
        unknown = set(params) - set(self._OPENCODE_PARAM_FLAGS)
        if unknown:
            log.debug("ignoring unknown model params: %s", unknown)

    def _build_cmd_codex(self, ref: AgentRef) -> list[str]:
        # codex exec: prompt fed via STDIN; no --json (plain text degrades gracefully).
        # --skip-git-repo-check: codex refuses to run outside a "trusted"/git dir otherwise
        # (e.g. the connection test's temp cwd) — verified live 2026-06-07.
        return ["codex", "exec", "--model", ref.model, "--skip-git-repo-check"]

    def _build_cmd_claude(self, ref: AgentRef) -> list[str]:
        # Claude Code headless: prompt fed via STDIN; JSONL events on STDOUT.
        # Model maps through ANTHROPIC_BASE_URL provider (e.g. DeepSeek) when set.
        cmd = ["claude", "-p", "--output-format", "stream-json", "--verbose",
               "--dangerously-skip-permissions"]
        if ref.model:
            cmd += ["--model", ref.model]
        return cmd

    # opencode 1.16.0: `opencode run [message..]` — message is POSITIONAL (no --prompt).
    # Machine output: `--format json` to STDOUT (no --output). Agent via --agent,
    # model via --model provider/model. Flags verified against `opencode run --help`.
    _MAX_INLINE_PROMPT = 28000  # CreateProcess arg-length headroom (Windows)

    def _build_cmd(
        self,
        ref: AgentRef,
        prompt_text: str,
        *,
        use_models: bool,
        attach_file: pathlib.Path | None = None,
    ) -> list[str]:
        cmd = ["opencode", "run", "--format", "json"]
        if ref.agent and not use_models:
            cmd += ["--agent", ref.agent]
        else:
            cmd += ["--model", f"{ref.provider}/{ref.model}"]
        # Model params (MODEL-003)
        self._append_model_params(cmd, ref.model_params)
        if attach_file is not None:
            # large prompt: attach the file and pass a short positional message
            cmd += ["-f", str(attach_file),
                    "Follow the instructions in the attached file exactly."]
        else:
            cmd.append(prompt_text)  # positional message
        return cmd

    async def run(
        self,
        ref: AgentRef,
        *,
        prompt_file: pathlib.Path,
        cwd: str,
        output_path: pathlib.Path,
        timeout_sec: int,
        use_models: bool = False,
    ) -> AgentResult:
        # Per-role engine: this ref's named profile, else the workspace default.
        engine, prof_env = self._resolve_engine(ref)
        label = self._label(ref, use_models, engine)
        # Proactive rate limiting: acquire a slot before launching the subprocess (MODEL-001)
        from app.core.rate_limit import get_rate_limiter
        rl = get_rate_limiter()
        if not rl.acquire(ref.provider):
            log.warning("rate limit: provider %s throttled, skipping", ref.provider)
            return AgentResult(exit_code=-1, refused=False, output_path=output_path, agent_label=label)
        prompt_text = prompt_file.read_text(encoding="utf-8", errors="replace")
        stdin_data: bytes | None = None
        if engine in ("claude", "codex"):
            # Claude and codex: prompt fed via STDIN (avoids argv length limits).
            # codex exec reads the instruction from stdin when no positional prompt is given.
            cmd = self._build_cmd_claude(ref) if engine == "claude" else self._build_cmd_codex(ref)
            stdin_data = prompt_text.encode("utf-8", errors="replace")
        else:
            attach = prompt_file if len(prompt_text) > self._MAX_INLINE_PROMPT else None
            cmd = self._build_cmd(ref, prompt_text, use_models=use_models, attach_file=attach)
        # Resolve the executable (picks up .cmd/.bat shims on Windows; no-op on POSIX).
        resolved = shutil.which(cmd[0]) or cmd[0]
        cmd = [resolved, *cmd[1:]]
        # Merge default env + the profile env (e.g. DeepSeek endpoint/keys for this role).
        sub_env = {**os.environ, **self._env, **prof_env}
        # Headless Claude CLI auth: an ANTHROPIC_API_KEY for a third-party ANTHROPIC_BASE_URL
        # (e.g. DeepSeek) is only honored after interactive "approval"; in `-p` runs the CLI
        # instead falls back to the machine's logged-in OAuth account and sends THAT token to
        # the custom endpoint -> 401. ANTHROPIC_AUTH_TOKEN (Authorization: Bearer) is higher
        # precedence and needs no approval, so route the provided key through it. Only when a
        # key is set, so OAuth-only profiles (the real-Anthropic `claude` role) keep the login.
        # This routing is claude-only; codex uses OPENAI_API_KEY and passes it through as-is.
        if engine == "claude" and sub_env.get("ANTHROPIC_API_KEY") and not sub_env.get("ANTHROPIC_AUTH_TOKEN"):
            sub_env["ANTHROPIC_AUTH_TOKEN"] = sub_env.pop("ANTHROPIC_API_KEY")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # Own asyncio subprocess on the CURRENT loop; JSONL events on STDOUT are
            # captured into a unique output_path (no shared session_name, R1/R2).
            proc = await asyncio.create_subprocess_exec(  # noqa: S603 — list args, no shell
                *cmd,
                cwd=cwd,
                stdin=asyncio.subprocess.PIPE if stdin_data is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=sub_env,
            )
        except FileNotFoundError:
            log.error("%s CLI not found on PATH", engine)
            return AgentResult(exit_code=-1, refused=False, output_path=output_path, agent_label=label)
        stderr_path = output_path.with_name(output_path.stem + ".stderr.txt")
        # Stream the agent's STDOUT to output_path incrementally (flush per chunk) so the
        # conversation viewer's live-tail shows the dialogue AS IT HAPPENS, instead of only
        # after the agent exits (the old communicate()+write_bytes buffered the whole run in
        # memory and dumped it once, so a slow agent looked like an empty conversation).
        # STDERR is drained concurrently — an undrained PIPE deadlocks a chatty agent — and
        # STDIN is fed concurrently for the same reason (replaces communicate()'s plumbing).
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []

        async def _feed_stdin() -> None:
            if stdin_data is None or proc.stdin is None:
                return
            with contextlib.suppress(Exception):
                proc.stdin.write(stdin_data)
                await proc.stdin.drain()
            with contextlib.suppress(Exception):
                proc.stdin.close()

        async def _pump_stdout(fh: IO[bytes]) -> None:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                stdout_chunks.append(chunk)
                with contextlib.suppress(OSError):
                    fh.write(chunk)
                    fh.flush()

        async def _pump_stderr() -> None:
            assert proc.stderr is not None
            while True:
                chunk = await proc.stderr.read(65536)
                if not chunk:
                    break
                stderr_chunks.append(chunk)

        try:
            with open(output_path, "wb") as _fh:  # noqa: SIM115 — closed by the with-block
                await asyncio.wait_for(
                    asyncio.gather(_feed_stdin(), _pump_stdout(_fh), _pump_stderr(), proc.wait()),
                    timeout=timeout_sec,
                )
            rc = proc.returncode if proc.returncode is not None else -1
        except TimeoutError:
            with contextlib.suppress(Exception):
                proc.kill()
                await proc.wait()
            with contextlib.suppress(OSError):
                stderr_path.write_text(f"[agent] TIMEOUT after {timeout_sec}s ({label})\n", encoding="utf-8")
            # output_path keeps whatever streamed before the timeout (partial conversation).
            return AgentResult(exit_code=-1, refused=False, output_path=output_path, agent_label=label)
        stdout = b"".join(stdout_chunks)
        stderr_data = b"".join(stderr_chunks)
        # Capture stderr so failures are diagnosable (was silently discarded). On a non-zero
        # exit with empty stdout this is the only record of WHY the agent failed.
        if stderr_data or rc != 0:
            with contextlib.suppress(OSError):
                stderr_path.write_text(
                    f"[agent] exit={rc} label={label} stdout_bytes={len(stdout or b'')}\n"
                    + (stderr_data or b"").decode("utf-8", errors="replace"),
                    encoding="utf-8",
                )
            if rc != 0:
                log.warning("agent %s exit=%d; stderr -> %s", label, rc, stderr_path.name)
        head = (stdout or b"")[:1000].decode("utf-8", errors="replace")
        refused = "REFUSED" in head
        return AgentResult(exit_code=rc, refused=refused, output_path=output_path, agent_label=label)

    async def run_with_fallback(
        self,
        agents: AgentsConfig,
        *,
        prompt_file: pathlib.Path,
        cwd: str,
        iter_dir: pathlib.Path,
        timeout_sec: int,
    ) -> AgentResult:
        primary_out = iter_dir / "output.primary.jsonl"
        res = await self.run(
            agents.primary,
            prompt_file=prompt_file,
            cwd=cwd,
            output_path=primary_out,
            timeout_sec=timeout_sec,
            use_models=agents.use_models,
        )
        if res.exit_code == 0 or res.refused:
            return res
        log.warning("primary agent failed (rc=%d), trying fallback", res.exit_code)
        fallback_out = iter_dir / "output.fallback.jsonl"
        return await self.run(
            agents.fallback,
            prompt_file=prompt_file,
            cwd=cwd,
            output_path=fallback_out,
            timeout_sec=timeout_sec,
            use_models=agents.use_models,
        )

    async def run_with_provider_fallback(
        self,
        agents: AgentsConfig,
        *,
        prompt_file: pathlib.Path,
        cwd: str,
        iter_dir: pathlib.Path,
        timeout_sec: int,
        provider_chain: list[tuple[str, AgentRef, AgentRef]] | None = None,
    ) -> AgentResult:
        """Run with optional provider-level fallback ON TOP of agent-level fallback.

        provider_chain: list of (provider_name, primary_ref, fallback_ref) tuples.
        First entry = default. Subsequent = alternatives on repeated 503/429.
        If None or empty → delegates to run_with_fallback (current behavior).
        """
        if not provider_chain:
            return await self.run_with_fallback(
                agents, prompt_file=prompt_file, cwd=cwd,
                iter_dir=iter_dir, timeout_sec=timeout_sec)

        tried: set[str] = set()
        last_res: AgentResult | None = None
        for prov_name, primary, fallback in provider_chain:
            if prov_name in tried:
                continue
            tried.add(prov_name)
            from app.models.workspace import AgentsConfig as AC
            prov_agents = AC(primary=primary, fallback=fallback,
                           use_models=agents.use_models)
            res = await self.run_with_fallback(
                prov_agents, prompt_file=prompt_file, cwd=cwd,
                iter_dir=iter_dir, timeout_sec=timeout_sec)
            last_res = res
            if res.exit_code == 0 or res.refused:
                return res
            from app.core.transient import classify_failure
            stderr_path = res.output_path.with_name(res.output_path.stem + ".stderr.txt")
            cls = classify_failure(res.exit_code, res.output_path, stderr_path)
            if not cls.is_transient:
                return res
            log.warning("provider %s transient failure (%s), trying next",
                        prov_name, cls.reason)
        return last_res if last_res is not None else AgentResult(
            exit_code=-1, refused=False, output_path=iter_dir / "output.provider-fallback.jsonl",
            agent_label="provider-fallback")
