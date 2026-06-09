"""OPENCODE phase — run the agent and the transient-retry wrapper.

Bodies extracted from ``OrchestratorFSM._run_opencode`` and
``OrchestratorFSM._run_opencode_with_retry`` (ARCH-001). Behavior is identical,
including:

* the lazy ``from app.services.opencode_runner import AgentRunner`` import that
  lets tests monkeypatch ``app.services.opencode_runner.AgentRunner``,
* the per-item ``modelOverride`` AgentRef path (with the fallback-to-default on
  invalid override),
* the transient-failure classifier + linear backoff in the retry wrapper.

The retry wrapper calls ``fsm._run_opencode`` THROUGH THE METHOD (not through
``run_opencode`` directly) so tests that replace ``fsm._run_opencode`` with a
stub still drive the retry loop unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.orchestrator.fsm import OrchestratorFSM

log = logging.getLogger("hephaestus.orchestrator")


async def run_opencode(fsm: OrchestratorFSM, item: dict[str, Any], prompt: str) -> int | None:
    """Run opencode with the prompt via AgentRunner. Returns exit code or None if refused."""
    from app.services.opencode_runner import AgentRunner

    if fsm._ws is None or fsm.iter_dir is None:
        log.error("no active workspace / iter_dir for opencode run")
        return -1

    prompt_file = fsm.iter_dir / "prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")

    runner = AgentRunner(
        fsm._pm,
        engine=getattr(fsm._ws, "engine", "opencode"),
        env=getattr(fsm._ws, "engine_env", {}),
        profiles=getattr(fsm._ws, "engine_profiles", []),
    )
    agents = fsm._ws.agents
    mo = item.get("modelOverride") or item.get("model_override")
    if mo:
        from app.models.workspace import AgentRef
        try:
            agents = fsm._ws.agents.model_copy(update={"primary": AgentRef.model_validate(mo)})
        except Exception:
            log.warning("_run_opencode: invalid modelOverride %r — using workspace default", mo)
            agents = fsm._ws.agents
    result = await runner.run_with_fallback(
        agents,
        prompt_file=prompt_file,
        cwd=fsm._get_repo(),
        iter_dir=fsm.iter_dir,
        timeout_sec=fsm._ws.verify_timeout_sec,
    )
    if result.refused:
        log.warning("Agent refused task")
        return None
    return result.exit_code


async def run_opencode_with_retry(
    fsm: OrchestratorFSM, item: dict[str, Any], prompt: str
) -> int | None:
    """Run opencode with automatic retry on transient failures."""
    import asyncio

    from app.core.transient import classify_failure

    max_retries = int(getattr(fsm._ws, "max_transient_retries", 2))
    backoff = int(getattr(fsm._ws, "transient_backoff_sec", 10))

    rc: int | None = None
    for attempt in range(max_retries + 1):
        # Call through the FSM method so tests that replace fsm._run_opencode
        # with a stub still drive the retry loop unchanged.
        rc = await fsm._run_opencode(item, prompt)
        if rc is None:  # refused — never transient
            return None
        if rc == 0:
            if attempt > 0:
                log.info("opencode succeeded on retry attempt %d", attempt + 1)
            return 0

        # Classify failure
        output_path = stderr_path = None
        if fsm.iter_dir:
            output_path = fsm.iter_dir / "output.primary.jsonl"
            stderr_path = fsm.iter_dir / "output.primary.stderr.txt"
        cls = classify_failure(rc, output_path, stderr_path)

        if not cls.is_transient or attempt == max_retries:
            if attempt > 0:
                log.warning(
                    "opencode failed after %d attempt(s): %s",
                    attempt + 1, cls.reason,
                )
            return rc

        log.info(
            "transient failure (attempt %d/%d): %s — retrying in %ds",
            attempt + 1, max_retries + 1, cls.reason, backoff * (attempt + 1),
        )
        fsm._persist_item_fields(item, last_transient=cls.reason)
        await asyncio.sleep(backoff * (attempt + 1))

    return rc  # should not reach here, but satisfy type checker
