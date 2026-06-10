"""VerifyRunner — cross-platform verify commands from memory/override (D4, R5).

Each command is "one program + args per line, no shell operators" (&&, |, >, $VAR).
The executable is resolved via shutil.which BEFORE exec so Windows picks up .cmd/.bat/.exe
shims (npm.cmd / pnpm.cmd). shlex.split uses posix=True on every platform.
Optional 'shell:' prefix forces shell execution.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import pathlib
import shlex
import shutil
import sys

from pydantic import BaseModel

from app.models.workspace import RepoProfile, VerifySource

log = logging.getLogger("hephaestus.backend.verify")

_IS_WIN = sys.platform.startswith("win")


def argv_for(cmd: str) -> list[str]:
    """Resolve a verify command line into an argv list (R5).

    Module-level so the baseline probe (verify_detect.partition_by_baseline) executes
    commands exactly the way the gate will. Optional ``shell:`` prefix forces shell
    execution; otherwise the executable is resolved via ``shutil.which`` first so Windows
    picks up ``.cmd``/``.bat`` shims (npm.cmd / pnpm.cmd)."""
    stripped = cmd.strip()
    if stripped.startswith("shell:"):
        inner = stripped[len("shell:") :].strip()
        return ["cmd", "/c", inner] if _IS_WIN else ["sh", "-c", inner]
    argv = shlex.split(stripped, posix=True)
    if not argv:
        return []
    exe = shutil.which(argv[0]) or argv[0]  # picks up npm.cmd/pnpm.cmd on Windows
    return [exe, *argv[1:]]


class VerifyResult(BaseModel):
    ok: bool
    ran: list[str]
    failed_command: str | None = None
    log_path: pathlib.Path


class VerifyOutcome(BaseModel):
    """FSM-level verdict combining configured verify commands AND the diff-test
    safety net (app.core.diff_tests). ``unverified`` means *nothing actually ran* —
    no verify command configured and no test file in the diff — so the gate must NOT
    be reported as green (honest gate; R-honest-verify)."""

    passed: bool          # nothing that ran reported failure
    checks_ran: int       # verify commands + diff-test files actually executed green
    unverified: bool      # checks_ran == 0 → nothing ran, do not claim "green"
    detail: str = ""


class VerifyRunner:
    def __init__(self, ws: RepoProfile) -> None:
        self.ws = ws

    def resolve_commands(self) -> list[str]:
        if self.ws.verify_source is VerifySource.MANUAL:
            return list(self.ws.verify_commands_override)
        from app.services.project_memory import ProjectMemory

        return ProjectMemory(self.ws).read_verify_commands()

    def _argv_for(self, cmd: str) -> list[str]:
        """Resolve a verify command line into an argv list (R5)."""
        return argv_for(cmd)

    async def run(
        self, *, cwd: str, log_path: pathlib.Path, timeout_sec: int
    ) -> VerifyResult:
        cmds = self.resolve_commands()
        ran: list[str] = []
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as logf:
            for cmd in cmds:
                argv = self._argv_for(cmd)
                if not argv:
                    continue
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *argv,
                        cwd=cwd,
                        stdout=logf,
                        stderr=asyncio.subprocess.STDOUT,
                        env=os.environ,
                    )
                except FileNotFoundError:
                    logf.write(f"\n[verify] command not found: {cmd}\n".encode())
                    return VerifyResult(
                        ok=False, ran=ran, failed_command=cmd, log_path=log_path
                    )
                try:
                    rc = await asyncio.wait_for(proc.wait(), timeout=timeout_sec)
                except TimeoutError:
                    with contextlib.suppress(Exception):
                        proc.kill()
                        await proc.wait()
                    logf.write(f"\n[verify] timeout: {cmd}\n".encode())
                    return VerifyResult(
                        ok=False, ran=ran, failed_command=cmd, log_path=log_path
                    )
                ran.append(cmd)
                if rc != 0:
                    return VerifyResult(
                        ok=False, ran=ran, failed_command=cmd, log_path=log_path
                    )
        return VerifyResult(ok=True, ran=ran, failed_command=None, log_path=log_path)
