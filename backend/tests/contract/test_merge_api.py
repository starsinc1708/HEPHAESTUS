"""Contract: merge-preflight / merge-job endpoints (FastAPI TestClient)."""

from __future__ import annotations

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def test_preflight_rejects_unsafe_branch(client):
    r = client.get("/api/v1/branches/not-an-auto-branch/merge-preflight")
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_merge_rejects_unsafe_branch(client):
    r = client.post("/api/v1/branches/main/merge", json={"push": False}, headers=_CSRF)
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_preflight_no_workspace_returns_409(client, monkeypatch):
    import app.api.v1.merge as merge_mod

    def _boom():
        raise merge_mod.NoActiveWorkspace()

    monkeypatch.setattr(merge_mod, "active_workspace", _boom)
    r = client.get("/api/v1/branches/auto%2Fx-1/merge-preflight")
    assert r.status_code == 409
    assert "workspace" in r.json()["error"].lower()


def test_start_merge_returns_jobid(client, monkeypatch):
    from types import SimpleNamespace

    import app.api.v1.merge as merge_mod
    from app.models.merge import MergeJob, MergeJobStatus
    from app.models.validation import MergePreflightResponse

    # Provide a fake workspace so active_workspace() doesn't raise.
    fake_ws = SimpleNamespace(
        id="ws-test", repo_path="/tmp/repo", base_branch="main", remote="origin"
    )
    monkeypatch.setattr(merge_mod, "active_workspace", lambda: fake_ws)

    monkeypatch.setattr(
        "app.core.git.GitService.merge_preflight",
        lambda self, b: MergePreflightResponse(
            cleanTree=True,
            verifyGreen=True,
            validationPassed=True,
            loopActive=False,
            baseBranch="main",
            conflicts=[],
            ok=True,
        ),
    )
    monkeypatch.setattr("app.core.git.GitService._loop_active", lambda self: False)
    monkeypatch.setattr("app.core.merge_job.MergeJobStore.active", lambda self: None)

    async def fake_start(self, **kw):
        return MergeJob(
            id="merge-0001",
            branch=kw["branch"],
            base_branch="main",
            status=MergeJobStatus.RESOLVED,
        )

    monkeypatch.setattr("app.core.merge_job.MergeJobRunner.start", fake_start)

    r = client.post("/api/v1/branches/auto%2Fx/merge", json={"push": False}, headers=_CSRF)
    assert r.status_code == 200
    assert r.json()["jobId"] == "merge-0001"


def test_get_merge_job(client, monkeypatch):
    from app.models.merge import MergeJob, MergeJobStatus

    monkeypatch.setattr(
        "app.core.merge_job.MergeJobStore.get",
        lambda self, jid: MergeJob(
            id=jid,
            branch="auto/x",
            base_branch="main",
            status=MergeJobStatus.RESOLVED,
        ),
    )
    r = client.get("/api/v1/merge-jobs/merge-0001")
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"


def test_get_merge_job_not_found(client, monkeypatch):
    monkeypatch.setattr(
        "app.core.merge_job.MergeJobStore.get",
        lambda self, jid: None,
    )
    r = client.get("/api/v1/merge-jobs/no-such-job")
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_merge_job_verify_log(client, monkeypatch, tmp_path):
    from app.models.merge import MergeJob, MergeJobStatus

    monkeypatch.setattr(
        "app.core.merge_job.MergeJobStore.get",
        lambda self, jid: MergeJob(id=jid, branch="auto/x", base_branch="main",
                                   status=MergeJobStatus.RESOLVED),
    )
    monkeypatch.setattr("app.core.state._state_dir", lambda: tmp_path)
    (tmp_path / "merge-0001").mkdir()
    (tmp_path / "merge-0001" / "verify.log").write_text("All checks passed!\n", encoding="utf-8")

    r = client.get("/api/v1/merge-jobs/merge-0001/verify-log")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "All checks passed!" in body["log"]


def test_merge_job_verify_log_unknown_job_404(client, monkeypatch):
    monkeypatch.setattr("app.core.merge_job.MergeJobStore.get", lambda self, jid: None)
    r = client.get("/api/v1/merge-jobs/nope/verify-log")
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_second_active_job_conflicts(client, monkeypatch):
    from types import SimpleNamespace

    import app.api.v1.merge as merge_mod
    from app.models.merge import MergeJob, MergeJobStatus

    # Provide a fake workspace so active_workspace() doesn't raise before the active() check.
    fake_ws = SimpleNamespace(
        id="ws-test", repo_path="/tmp/repo", base_branch="main", remote="origin"
    )
    monkeypatch.setattr(merge_mod, "active_workspace", lambda: fake_ws)

    monkeypatch.setattr(
        "app.core.merge_job.MergeJobStore.active",
        lambda self: MergeJob(
            id="merge-0001",
            branch="auto/y",
            base_branch="main",
            status=MergeJobStatus.RESOLVING,
        ),
    )
    r = client.post("/api/v1/branches/auto%2Fx/merge", json={}, headers=_CSRF)
    assert r.status_code == 409


def test_active_merge_job_returns_job(client, monkeypatch):
    from app.models.merge import MergeJob, MergeJobStatus

    monkeypatch.setattr(
        "app.core.merge_job.MergeJobStore.active",
        lambda self: MergeJob(id="merge-0007", branch="auto/x-1", base_branch="main",
                              status=MergeJobStatus.RESOLVED),
    )
    r = client.get("/api/v1/active-merge-job")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["job"]["id"] == "merge-0007"
    assert body["job"]["branch"] == "auto/x-1"


def test_active_merge_job_none(client, monkeypatch):
    monkeypatch.setattr("app.core.merge_job.MergeJobStore.active", lambda self: None)
    r = client.get("/api/v1/active-merge-job")
    assert r.status_code == 200
    assert r.json()["job"] is None
