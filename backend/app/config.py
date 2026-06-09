from __future__ import annotations

import json
import logging
import os
import pathlib
import re
from typing import Any

from pydantic_settings import BaseSettings

log = logging.getLogger("hephaestus.backend.config")

LOOP_HOME = pathlib.Path(
    os.environ.get(
        "HEPHAESTUS_LOOP_HOME",
        str(pathlib.Path(__file__).resolve().parent.parent.parent),
    )
)
STATE_DIR = LOOP_HOME / "state"
CONFIG_OVERRIDE = STATE_DIR / "config.json"
LOCK_PATH = STATE_DIR / ".work-state.lock"
REPO = os.environ.get("HEPHAESTUS_REPO", "")
PORT = int(os.environ.get("HEPHAESTUS_DASHBOARD_PORT", "8766"))
HOST = os.environ.get("HEPHAESTUS_DASHBOARD_HOST", "127.0.0.1")
BRANCH_PREFIX = os.environ.get("HEPHAESTUS_BRANCH_PREFIX", "auto")
BASE_BRANCH = os.environ.get("HEPHAESTUS_BASE_BRANCH", "main")
REMOTE = os.environ.get("HEPHAESTUS_REMOTE", "origin")

# Epic 1: AI-powered merge limits
MERGE_MAX_FILES = int(os.environ.get("HEPHAESTUS_MERGE_MAX_FILES", "40"))
MERGE_MAX_FILE_BYTES = int(os.environ.get("HEPHAESTUS_MERGE_MAX_FILE_BYTES", "200000"))
MERGE_TIMEOUT_SEC = int(os.environ.get("HEPHAESTUS_MERGE_TIMEOUT_SEC", "900"))

# Epic 3: tracker integrations
DEFAULT_PROVIDER = os.environ.get("HEPHAESTUS_DEFAULT_PROVIDER", "")

ALLOWED_CONFIG_KEYS = frozenset(
    {
        "HEPHAESTUS_REPO",
        "HEPHAESTUS_BASE_BRANCH",
        "HEPHAESTUS_REMOTE",
        "HEPHAESTUS_BRANCH_PREFIX",
        "HEPHAESTUS_PRIMARY_AGENT",
        "HEPHAESTUS_FALLBACK_AGENT",
        "HEPHAESTUS_PRIMARY_MODEL",
        "HEPHAESTUS_FALLBACK_MODEL",
        "HEPHAESTUS_USE_MODELS",
        "HEPHAESTUS_TIER_REVIEW",
        "HEPHAESTUS_TIER1_AGENTS",
        "HEPHAESTUS_TIER2_AGENTS",
        "HEPHAESTUS_FINAL_AGENT",
        "HEPHAESTUS_TIER1_APPROVE_THRESHOLD",
        "HEPHAESTUS_TIER2_APPROVE_THRESHOLD",
        "HEPHAESTUS_REVISION_MAX",
        "HEPHAESTUS_MAX_ITER",
        "HEPHAESTUS_MAX_PARALLEL",
        "HEPHAESTUS_ITER_TIMEOUT_SEC",
        "HEPHAESTUS_MAX_CONSEC_FAIL",
        "HEPHAESTUS_INTER_ITER_SLEEP",
        "HEPHAESTUS_AUTOPUSH",
        "HEPHAESTUS_REVIEW_TIMEOUT_SEC",
        "HEPHAESTUS_REVIEW_DIFF_CAP",
        "HEPHAESTUS_RUN_TESTS",
        "HEPHAESTUS_RUN_LINT",
        "HEPHAESTUS_RUN_TYPECHECK",
        "HEPHAESTUS_VERIFY_TIMEOUT_SEC",
        "HEPHAESTUS_SCAN_SCANNERS",
        "HEPHAESTUS_SCAN_REVIEWERS",
        "HEPHAESTUS_SCAN_SCOPE",
        "HEPHAESTUS_SCANNER_AGENTS",
        "HEPHAESTUS_REDUCER_AGENTS",
        "HEPHAESTUS_KEEP_ITERS",
        "SCANNERS",
        "REVIEWERS",
        "SCOPE",
        "HEPHAESTUS_AGENT_PROVIDER",
        "HEPHAESTUS_AGENT_MODEL",
        "HEPHAESTUS_VERIFY_COMMANDS",
        "HEPHAESTUS_WORKSPACE_ID",
        # Epic 1: AI-powered merge limits
        "HEPHAESTUS_MERGE_MAX_FILES",
        "HEPHAESTUS_MERGE_MAX_FILE_BYTES",
        "HEPHAESTUS_MERGE_TIMEOUT_SEC",
        # Epic 2 Batch C: Ralph run-mode
        "HEPHAESTUS_RUN_MODE",
        "HEPHAESTUS_COST_BUDGET_USD",
        "HEPHAESTUS_WALLCLOCK_SEC",
        "HEPHAESTUS_REPLENISH_MAX",
        # Epic 3: tracker integrations
        "HEPHAESTUS_DEFAULT_PROVIDER",
        # Phase 2: Reliability (REL-001, REL-005, REL-007)
        "HEPHAESTUS_KEEP_ITERS_DAYS",
        "HEPHAESTUS_KEEP_ITERS_MIN",
        "HEPHAESTUS_DISK_WARN_GB",
        "HEPHAESTUS_BACKUP_KEEP",
        # Phase 4: Provider rate limiting (MODEL-001)
        "HEPHAESTUS_RATE_LIMIT_PER_MIN",
        "HEPHAESTUS_RATE_LIMIT_MAX_WAIT_SEC",
        # FEAT-002: optional completion/failure notifications (ntfy.sh-friendly webhook)
        "HEPHAESTUS_NOTIFY_URL",
    }
)

_CONFIG_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class Settings(BaseSettings):
    loop_home: pathlib.Path = LOOP_HOME
    state_dir: pathlib.Path = STATE_DIR
    repo: str = REPO
    port: int = PORT
    host: str = HOST
    branch_prefix: str = BRANCH_PREFIX
    base_branch: str = BASE_BRANCH
    remote: str = REMOTE

    model_config = {"env_prefix": "HEPHAESTUS_"}


def filter_env_bits(bits: dict[str, Any]) -> dict[str, str]:
    safe: dict[str, str] = {}
    for k, v in bits.items():
        if not isinstance(k, str):
            continue
        if k not in ALLOWED_CONFIG_KEYS:
            continue
        if not _CONFIG_KEY_RE.match(k):
            continue
        safe[k] = v
    return safe


# ---------- config loading ----------


def _config_overrides() -> dict[str, Any]:
    """Load config overrides from state/config.json, filtering to allowed keys only."""
    try:
        raw = json.loads(CONFIG_OVERRIDE.read_text(encoding="utf-8")) if CONFIG_OVERRIDE.exists() else {}
    except Exception:
        return {}
    # Only keep keys in the whitelist; ignore unknowns silently.
    return {k: v for k, v in raw.items() if k in ALLOWED_CONFIG_KEYS}


def _config_effective() -> dict[str, str]:
    """Merge config.env defaults with state/config.json overrides into a single dict."""
    eff: dict[str, str] = {
        "HEPHAESTUS_REPO": REPO,
        "HEPHAESTUS_BRANCH_PREFIX": BRANCH_PREFIX,
        "HEPHAESTUS_BASE_BRANCH": BASE_BRANCH,
        "HEPHAESTUS_REMOTE": REMOTE,
        "HEPHAESTUS_PRIMARY_AGENT": os.environ.get("HEPHAESTUS_PRIMARY_AGENT", ""),
        "HEPHAESTUS_FALLBACK_AGENT": os.environ.get("HEPHAESTUS_FALLBACK_AGENT", ""),
        "HEPHAESTUS_MAX_ITER": os.environ.get("HEPHAESTUS_MAX_ITER", "50"),
        "HEPHAESTUS_MAX_PARALLEL": os.environ.get("HEPHAESTUS_MAX_PARALLEL", "1"),
        "HEPHAESTUS_TIER_REVIEW": os.environ.get("HEPHAESTUS_TIER_REVIEW", "on"),
        "HEPHAESTUS_AUTOPUSH": os.environ.get("HEPHAESTUS_AUTOPUSH", "off"),
        "HEPHAESTUS_ITER_TIMEOUT_SEC": os.environ.get("HEPHAESTUS_ITER_TIMEOUT_SEC", "2400"),
        "HEPHAESTUS_MAX_CONSEC_FAIL": os.environ.get("HEPHAESTUS_MAX_CONSEC_FAIL", "4"),
        "HEPHAESTUS_TIER1_AGENTS": os.environ.get("HEPHAESTUS_TIER1_AGENTS", ""),
        "HEPHAESTUS_TIER2_AGENTS": os.environ.get("HEPHAESTUS_TIER2_AGENTS", ""),
        "HEPHAESTUS_FINAL_AGENT": os.environ.get("HEPHAESTUS_FINAL_AGENT", ""),
        # Stage 3 (D10): funnel thresholds default here so _layer_sizes_for always
        # has a value even before a TIER_PRESET is applied; presets still override.
        "HEPHAESTUS_TIER1_APPROVE_THRESHOLD": os.environ.get("HEPHAESTUS_TIER1_APPROVE_THRESHOLD", "5"),
        "HEPHAESTUS_TIER2_APPROVE_THRESHOLD": os.environ.get("HEPHAESTUS_TIER2_APPROVE_THRESHOLD", "2"),
        "HEPHAESTUS_REVISION_MAX": os.environ.get("HEPHAESTUS_REVISION_MAX", "2"),
        # Epic 2 Batch C: Ralph run-mode defaults
        "HEPHAESTUS_RUN_MODE": os.environ.get("HEPHAESTUS_RUN_MODE", "queue"),
        "HEPHAESTUS_COST_BUDGET_USD": os.environ.get("HEPHAESTUS_COST_BUDGET_USD", "0"),
        "HEPHAESTUS_WALLCLOCK_SEC": os.environ.get("HEPHAESTUS_WALLCLOCK_SEC", "0"),
        "HEPHAESTUS_REPLENISH_MAX": os.environ.get("HEPHAESTUS_REPLENISH_MAX", "10"),
        # Epic 3: tracker integrations defaults
        "HEPHAESTUS_DEFAULT_PROVIDER": os.environ.get("HEPHAESTUS_DEFAULT_PROVIDER", ""),
    }
    eff.update(_config_overrides())

    # Validate and clamp numeric config values
    _validate_config_int(eff, "HEPHAESTUS_MAX_ITER", 1, 1000, 50)
    _validate_config_int(eff, "HEPHAESTUS_MAX_PARALLEL", 1, 16, 1)
    _validate_config_int(eff, "HEPHAESTUS_ITER_TIMEOUT_SEC", 30, 7200, 2400)
    _validate_config_int(eff, "HEPHAESTUS_MAX_CONSEC_FAIL", 1, 20, 4)
    _validate_config_int(eff, "HEPHAESTUS_REVISION_MAX", 0, 10, 2)

    return eff


def _validate_config_int(eff: dict[str, str], key: str, lo: int, hi: int, default: int) -> None:
    """Validate a config integer value, clamping to [lo, hi] with a warning."""
    raw = eff.get(key)
    if raw is None:
        return
    try:
        val = int(raw)
    except (ValueError, TypeError):
        log.warning("config %s is not an integer ('%s'), clamping to %d", key, raw, default)
        eff[key] = str(default)
        return
    if val < lo:
        log.warning("config %s=%d below minimum %d, clamping to %d", key, val, lo, lo)
        eff[key] = str(lo)
    elif val > hi:
        log.warning("config %s=%d above maximum %d, clamping to %d", key, val, hi, hi)
        eff[key] = str(hi)


# ---------- tier-review presets ----------

TIER_PRESETS: dict[str, dict[str, str]] = {
    "strict": {
        "HEPHAESTUS_TIER_REVIEW": "on",
        "HEPHAESTUS_TIER1_APPROVE_THRESHOLD": "6",
        "HEPHAESTUS_TIER2_APPROVE_THRESHOLD": "2",
    },
    "standard": {
        "HEPHAESTUS_TIER_REVIEW": "on",
        "HEPHAESTUS_TIER1_APPROVE_THRESHOLD": "5",
        "HEPHAESTUS_TIER2_APPROVE_THRESHOLD": "2",
    },
    "permissive": {
        "HEPHAESTUS_TIER_REVIEW": "on",
        "HEPHAESTUS_TIER1_APPROVE_THRESHOLD": "3",
        "HEPHAESTUS_TIER2_APPROVE_THRESHOLD": "1",
    },
    "disabled": {"HEPHAESTUS_TIER_REVIEW": "off"},
}


def _config_preset(name: str) -> dict[str, Any]:
    """Apply a named tier-review preset to config overrides."""
    from app.core.state import _atomic_write

    p = TIER_PRESETS.get(name)
    if not p:
        return {"ok": False, "error": f"unknown preset {name}"}
    cur = _config_overrides()
    cur.update(p)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    _atomic_write(CONFIG_OVERRIDE, json.dumps(cur, indent=2, ensure_ascii=False))
    return {"ok": True, "applied": p, "preset": name}
