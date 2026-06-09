"""Optional completion/failure notifications via a webhook (FEAT-002).

When ``HEPHAESTUS_NOTIFY_URL`` is set, a short message is POSTed when a task finishes or fails so a
self-hosted user doesn't have to watch the dashboard. The default target is ntfy.sh-friendly: a
plain POST where the body is the message and the ``Title``/``Tags`` headers are metadata — but any
URL that accepts a POST works.

Best-effort by design: never raises, short timeout, and a no-op when the URL is unset (so it adds
zero behaviour when not configured).
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger("hephaestus.backend.notify")

_TIMEOUT_SEC = 5.0


def _notify_url() -> str:
    from app.config import _config_effective

    return str(_config_effective().get("HEPHAESTUS_NOTIFY_URL", "") or "").strip()


def notify(title: str, message: str, *, tags: str = "") -> bool:
    """Send a best-effort notification. Returns True only if a request was sent AND the target
    answered 2xx. A no-op returning False when ``HEPHAESTUS_NOTIFY_URL`` is unset. Never raises."""
    url = _notify_url()
    if not url:
        return False
    headers = {"Title": title}
    if tags:
        headers["Tags"] = tags
    try:
        resp = httpx.post(url, content=message.encode("utf-8"), headers=headers, timeout=_TIMEOUT_SEC)
    except Exception:
        log.debug("notify failed (best-effort)", exc_info=True)
        return False
    ok = 200 <= resp.status_code < 300
    if not ok:
        log.debug("notify: %s answered %d", url, resp.status_code)
    return ok


def notify_task(item_id: str, status: str) -> None:
    """Fire a task done/failed notification (best-effort). Only ``done`` and ``failed:*`` are
    notified — intermediate states are noise."""
    if status == "done":
        notify("HEPHAESTUS: task done", f"✅ {item_id} completed", tags="white_check_mark")
    elif status.startswith("failed"):
        notify("HEPHAESTUS: task failed", f"❌ {item_id} — {status}", tags="x")
