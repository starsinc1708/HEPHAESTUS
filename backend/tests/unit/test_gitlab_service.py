"""Unit tests for GitLabService."""

from __future__ import annotations

import pytest

import app.services.integrations.creds as creds
from app.services.integrations.gitlab_service import GitLabService


def test_available(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(creds, "_STORE", tmp_path / "integrations.json")
    assert GitLabService("group/proj").available() is False
    creds.set_cred("gitlab", "glpat_x")
    assert GitLabService("group/proj").available() is True


def test_import_to_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    svc = GitLabService("group/proj")
    monkeypatch.setattr(
        svc,
        "_glab",
        lambda args: [{"iid": 4, "title": "Bug", "description": "d", "labels": ["hephaestus:bug"]}],
    )
    added: list[dict] = []
    monkeypatch.setattr("app.core.queue._queue_add", lambda item: added.append(item) or {"ok": True})
    svc.import_to_queue(label="hephaestus:bug")
    assert any(i["id"] == "gl-4" for i in added)


def test_create_mr_args(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(creds, "_STORE", tmp_path / "integrations.json")
    creds.set_cred("gitlab", "glpat_x")  # connected → available
    svc = GitLabService("group/proj")
    calls: list[list[str]] = []
    monkeypatch.setattr(svc, "_glab", lambda args: calls.append(args) or {"web_url": "http://gl/mr/1", "iid": 1})
    svc.create_pr("auto/x", title="T", body="B", base="main")
    assert any("mr" in a and "create" in a for a in calls)
