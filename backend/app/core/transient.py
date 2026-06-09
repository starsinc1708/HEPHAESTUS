"""Transient failure classifier for agent runs (Improvement 5)."""
from __future__ import annotations

import logging
import pathlib
from dataclasses import dataclass

log = logging.getLogger("hephaestus.core.transient")

# Specific enough not to fire on benign mentions. Bare "worktree"/"lock" were too broad
# ("deadlock in user code", normal "Preparing worktree…" git chatter) and could promote a
# real deterministic failure to transient, wasting the retry budget — narrowed to the actual
# git-lock phrases. These only matter when output is tiny-but-non-empty and exit != 0.
_TRANSIENT_STDERR_PATTERNS = (
    "worktree already locked",
    "index.lock",
    "another git process",
    "econnreset",
    "etimedout",
    "rate limit",
    "rate_limit",
    "429",
    "503",
    "connection reset",
    "connection refused",
    "timed out",
    "network",
    "socket hang up",
    "epipe",
    "enotfound",
)


@dataclass
class TransientClassification:
    is_transient: bool
    reason: str


def classify_failure(
    exit_code: int,
    output_path: pathlib.Path | None,
    stderr_path: pathlib.Path | None,
) -> TransientClassification:
    """Classify whether an agent failure is transient (retryable).

    Transient signals:
    - exit_code == -1 (timeout from AgentRunner)
    - exit_code != 0 AND output file empty/missing/tiny (agent crashed before producing output)
    - stderr contains known transient patterns

    NOT transient:
    - Agent refused (REFUSED in output) — caller should check refused separately
    - Non-empty output (>500 bytes) with exit_code != 0 (agent ran but produced bad result)
    """
    # Timeout is always transient
    if exit_code == -1:
        return TransientClassification(is_transient=True, reason="timeout")

    # Check output size: empty/missing/tiny output = likely crash
    output_size = 0
    if output_path is not None:
        try:
            output_size = output_path.stat().st_size
        except OSError:
            output_size = 0

    # If agent produced substantial output, it's not transient (it ran and failed)
    if output_size > 500:
        return TransientClassification(is_transient=False, reason="agent produced output")

    # Check stderr for known transient patterns
    if stderr_path is not None:
        try:
            stderr_text = stderr_path.read_text(encoding="utf-8", errors="replace").lower()
            for pattern in _TRANSIENT_STDERR_PATTERNS:
                if pattern in stderr_text:
                    return TransientClassification(
                        is_transient=True, reason=f"stderr contains '{pattern}'"
                    )
        except OSError:
            pass

    # Empty output + non-zero exit = likely crash/transient
    if output_size == 0:
        return TransientClassification(
            is_transient=True, reason="empty output (agent crash)"
        )

    # Small but non-empty output without transient stderr patterns
    return TransientClassification(is_transient=False, reason="non-transient failure")
