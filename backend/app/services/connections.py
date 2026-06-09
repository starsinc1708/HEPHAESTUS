"""Global connections store: state/connections.json. Single source of truth for model
endpoints/keys; resolved into per-workspace agent config at registry load."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.config import STATE_DIR
from app.core.state import _atomic_write
from app.models.connections import Connection, build_env, mask_env

log = logging.getLogger("hephaestus.backend.connections")
_STORE = STATE_DIR / "connections.json"


def list_connections() -> list[Connection]:
    if not _STORE.exists():
        return []
    try:
        data = json.loads(_STORE.read_text(encoding="utf-8"))
        return [Connection.model_validate(c) for c in data.get("connections", [])]
    except Exception:
        log.warning("connections.json unreadable — treating as empty", exc_info=True)
        return []


def _save(conns: list[Connection]) -> None:
    _STORE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"connections": [c.model_dump(by_alias=True) for c in conns]}
    _atomic_write(_STORE, json.dumps(payload, indent=2, ensure_ascii=False))


def get_connection(conn_id: str) -> Connection | None:
    return next((c for c in list_connections() if c.id == conn_id), None)


def add_connection(  # noqa: PLR0913
    *, provider: str, engine: str, auth_method: str, model: str,
    key: str = "", label: str | None = None,
) -> Connection:
    env = build_env(provider, engine, auth_method, model, key)  # raises ValueError on bad combo
    conn = Connection(
        id="conn-" + uuid.uuid4().hex[:8],
        label=label or f"{provider} ({engine})",
        provider=provider, engine=engine, auth_method=auth_method, model=model, env=env, status="untested",
    )
    conns = list_connections()
    conns.append(conn)
    _save(conns)
    return conn


def delete_connection(conn_id: str) -> bool:
    conns = list_connections()
    kept = [c for c in conns if c.id != conn_id]
    if len(kept) == len(conns):
        return False
    _save(kept)
    return True


def set_status(conn_id: str, status: str, *, error: str | None, tested_at: str | None) -> None:
    conns = list_connections()
    for c in conns:
        if c.id == conn_id:
            c.status, c.last_error, c.last_tested_at = status, error, tested_at
    _save(conns)


def list_connections_masked() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for c in list_connections():
        d = c.model_dump(by_alias=True)
        d["env"] = mask_env(c.env)
        out.append(d)
    return out
