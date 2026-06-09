"""Contract tests for POST /api/v1/scans/import (#7)."""
from __future__ import annotations

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def test_scans_import_empty_ids_clean(client, tmp_path, monkeypatch):
    """Empty ids → 200 with a clean empty result (never crashes)."""
    import app.core.state as state_mod

    sd = tmp_path / "st"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.post("/api/v1/scans/import", json={"ids": []}, headers=_CSRF)
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["added"] == []
    assert data["skipped"] == []


def test_scans_import_bad_dirname_404(client, tmp_path, monkeypatch):
    """A bad/missing dirname → 404 (cleanly), not a crash."""
    import app.core.state as state_mod

    sd = tmp_path / "st2"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.post("/api/v1/scans/import", json={"ids": ["x"], "dirname": "not-a-scan"},
                    headers=_CSRF)
    assert r.status_code == 404
    assert r.json()["ok"] is False


def test_scans_import_passes_ids_and_dirname(client, tmp_path, monkeypatch):
    """The route forwards ids + dirname to the resolver and returns its result."""
    import app.api.v1.scans as scans_mod
    import app.core.state as state_mod

    sd = tmp_path / "st3"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    seen: dict = {}

    def _fake(ids, *, dirname=None):
        seen["ids"] = ids
        seen["dirname"] = dirname
        return {"ok": True, "added": ids, "skipped": []}

    monkeypatch.setattr(scans_mod, "_scans_import_by_ids", _fake)

    r = client.post("/api/v1/scans/import", json={"ids": ["a", "b"], "dirname": "scan-1"},
                    headers=_CSRF)
    assert r.status_code == 200
    assert r.json()["added"] == ["a", "b"]
    assert seen == {"ids": ["a", "b"], "dirname": "scan-1"}
