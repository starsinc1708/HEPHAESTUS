"""FEAT-002: optional ntfy.sh/webhook notifications — best-effort, no-op when unset."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.services import notify as notify_mod


def test_notify_noop_when_url_unset():
    """No URL configured → no HTTP call, returns False."""
    with patch("app.config._config_effective", return_value={}), \
         patch("app.services.notify.httpx.post") as post:
        assert notify_mod.notify("t", "m") is False
        post.assert_not_called()


def test_notify_posts_when_url_set():
    """URL set + 2xx → posts the message as body with a Title header, returns True."""
    with patch("app.config._config_effective", return_value={"HEPHAESTUS_NOTIFY_URL": "https://ntfy.sh/topic"}), \
         patch("app.services.notify.httpx.post", return_value=SimpleNamespace(status_code=200)) as post:
        assert notify_mod.notify("Title!", "hello", tags="x") is True
        post.assert_called_once()
        _, kwargs = post.call_args
        assert kwargs["content"] == b"hello"
        assert kwargs["headers"]["Title"] == "Title!"
        assert kwargs["headers"]["Tags"] == "x"


def test_notify_non_2xx_returns_false():
    with patch("app.config._config_effective", return_value={"HEPHAESTUS_NOTIFY_URL": "https://x"}), \
         patch("app.services.notify.httpx.post", return_value=SimpleNamespace(status_code=500)):
        assert notify_mod.notify("t", "m") is False


def test_notify_never_raises_on_http_error():
    """A network/HTTP failure is swallowed (best-effort) — returns False, does not raise."""
    with patch("app.config._config_effective", return_value={"HEPHAESTUS_NOTIFY_URL": "https://x"}), \
         patch("app.services.notify.httpx.post", side_effect=RuntimeError("boom")):
        assert notify_mod.notify("t", "m") is False


def test_notify_task_done_and_failed_fire():
    with patch("app.services.notify.notify") as n:
        notify_mod.notify_task("task-1", "done")
        notify_mod.notify_task("task-1", "failed:verify")
    assert n.call_count == 2
    assert "task-1" in n.call_args_list[0].args[1]      # done message
    assert "failed:verify" in n.call_args_list[1].args[1]  # failure message


def test_notify_task_ignores_non_terminal():
    """Intermediate states must not notify (noise)."""
    with patch("app.services.notify.notify") as n:
        notify_mod.notify_task("task-1", "in_progress")
        notify_mod.notify_task("task-1", "queued")
    n.assert_not_called()
