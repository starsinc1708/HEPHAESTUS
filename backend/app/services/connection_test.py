"""Real-CLI connection test: run the connection's engine on a 1-token prompt (mirrors the
manual HEPHAESTUS_DS_OK smoke test). Never raises — returns (status, error)."""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from app.models.connections import Connection, find_combo
from app.models.workspace import AgentRef, EngineProfile

if TYPE_CHECKING:
    from app.services.opencode_runner import AgentRunner

log = logging.getLogger("hephaestus.backend.connection_test")
_PROMPT = "Reply with exactly this token and nothing else: HEPHAESTUS_CONN_OK"


def _make_runner(conn: Connection) -> AgentRunner:  # patched in tests
    from app.core.process import pm
    from app.services.opencode_runner import AgentRunner
    return AgentRunner(pm, engine=conn.engine,
                       profiles=[EngineProfile(name="__test__", engine=conn.engine, env=conn.env)])


async def test_connection(conn: Connection) -> tuple[str, str | None]:
    ref = AgentRef(provider=conn.provider, model=conn.model, engine_profile="__test__")
    runner = _make_runner(conn)
    with tempfile.TemporaryDirectory() as d:
        pf = Path(d) / "prompt.md"
        pf.write_text(_PROMPT, encoding="utf-8")
        out = Path(d) / "out.jsonl"
        try:
            res = await runner.run(ref, prompt_file=pf, cwd=d, output_path=out,
                                   timeout_sec=60, use_models=True)
        except Exception as exc:  # never crash the endpoint
            return "failed", f"runner error: {exc}"
        text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
        if res.exit_code == 0 and text.strip():
            return "connected", None
        if res.exit_code == -1:
            return "failed", f"{conn.engine} CLI not found or failed to start"
        tail = (text or "").strip()[-300:]
        err = f"exit {res.exit_code}: {tail or 'no output'}"
        if conn.auth_method == "subscription":
            combo = find_combo(conn.provider, conn.engine, "subscription")
            if combo and combo.login_cmd:
                login_hint = combo.login_cmd
            elif conn.engine == "codex":
                login_hint = "codex login"
            elif conn.engine == "opencode":
                login_hint = "opencode auth login"
            else:
                login_hint = "claude (/login)"
            err = f"{err} — run: {login_hint}"
        return "failed", err
