"""Contract: /api/v1/worktrees enumeration + per-branch diff endpoint (FastAPI TestClient)."""

from __future__ import annotations

from types import SimpleNamespace


def test_worktrees_shape(client, monkeypatch):
    import app.api.v1.worktrees as wt_mod
    from app.core.worktrees import ConflictRef, Worktree, WorktreeTask
    from app.models.validation import MergePreflightResponse

    fake_ws = SimpleNamespace(
        id="ws-test", repo_path="/tmp/repo", base_branch="main",
        remote="origin", branch_prefix="auto",
    )
    monkeypatch.setattr(wt_mod, "active_workspace", lambda: fake_ws)

    pf = MergePreflightResponse(
        cleanTree=True, verifyGreen=True, validationPassed=True,
        loopActive=False, baseBranch="main", conflicts=[], ok=True,
    )
    monkeypatch.setattr(
        wt_mod, "list_worktrees",
        lambda ws: [
            Worktree(
                branch="auto/x",
                task=WorktreeTask(id="t1", title="T1", status="done"),
                changed_files=["a.ts"],
                changed_count=1,
                preflight=pf,
                conflicts_with=[ConflictRef(branch="auto/y", files=["a.ts"])],
            )
        ],
    )

    r = client.get("/api/v1/worktrees")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    w0 = body["worktrees"][0]
    assert w0["branch"] == "auto/x"
    assert w0["changedFiles"] == ["a.ts"]
    assert w0["changedCount"] == 1
    assert isinstance(w0["conflictsWith"], list)
    c0 = w0["conflictsWith"][0]
    assert c0["branch"] == "auto/y"
    assert c0["files"] == ["a.ts"]
    # Nested preflight must also be camelCase (regression guard for model_dump(by_alias=True)).
    pf_body = w0["preflight"]
    assert "cleanTree" in pf_body and "verifyGreen" in pf_body and "baseBranch" in pf_body
    assert "clean_tree" not in pf_body


def test_worktrees_no_workspace_returns_409(client, monkeypatch):
    import app.api.v1.worktrees as wt_mod

    def _boom():
        raise wt_mod.NoActiveWorkspace()

    monkeypatch.setattr(wt_mod, "active_workspace", _boom)
    r = client.get("/api/v1/worktrees")
    assert r.status_code == 409
    assert r.json()["ok"] is False


def test_branch_diff_rejects_non_auto(client):
    r = client.get("/api/v1/branches/main/diff")
    assert r.status_code == 400


def test_branch_diff_returns_unified_diff(client, monkeypatch):
    import app.api.v1.worktrees as wt_mod

    fake_ws = SimpleNamespace(
        id="ws-test", repo_path="/tmp/repo", base_branch="main",
        remote="origin", branch_prefix="auto",
    )
    monkeypatch.setattr(wt_mod, "active_workspace", lambda: fake_ws)
    monkeypatch.setattr(
        "app.core.git.GitService.diff",
        lambda self, b: "diff --git a/x b/x\n@@ -1 +1 @@\n-old\n+new\n",
    )

    r = client.get("/api/v1/branches/auto%2Fx/diff")
    assert r.status_code == 200
    assert "diff --git a/x b/x" in r.text
