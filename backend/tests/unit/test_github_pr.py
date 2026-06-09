"""Unit tests for GitHubIssuesService.create_pr, available, and GitHubProvider."""

from __future__ import annotations

import app.services.integrations.creds as creds
from app.services.github_issues import GitHubIssuesService


def test_create_pr_pushes_then_creates(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(creds, "_STORE", tmp_path / "integrations.json")
    creds.set_cred("github", "ghp_token")  # connected → available
    svc = GitHubIssuesService("owner/repo")
    calls: list[list[str]] = []
    monkeypatch.setattr(svc, "_gh", lambda args, input_data=None: calls.append(args) or  # type: ignore[attr-defined]
                        {"number": 7, "url": "https://github.com/owner/repo/pull/7"})
    pushes: list[list[str]] = []
    monkeypatch.setattr("app.services.github_issues._run",  # type: ignore[attr-defined]
                        lambda cmd, **kw: (pushes.append(cmd) or ""))
    res = svc.create_pr("auto/x", title="T", body="B", base="main")
    assert res is not None
    assert res["number"] == 7
    assert any("pr" in a and "create" in a for a in calls)
    assert any("push" in c for c in pushes)


def test_create_pr_unavailable_returns_none(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(creds, "_STORE", tmp_path / "integrations.json")  # no token stored
    svc = GitHubIssuesService("owner/repo")
    assert svc.available() is False
    result = svc.create_pr("auto/x", title="T", body="B", base="main")
    assert result is None
