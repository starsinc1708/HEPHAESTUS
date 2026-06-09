"""_scans_import_by_ids — the v1 scans/import resolver (#7)."""
from __future__ import annotations

import json
import pathlib
import types


def _write_results(scans_dir: pathlib.Path, dirname: str, proposals: list[dict]) -> None:
    d = scans_dir / dirname
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.json").write_text(json.dumps({"proposals": proposals, "n_unique": len(proposals)}))


def test_scans_import_empty_ids_is_clean() -> None:
    """No ids → clean empty result, never touches storage."""
    import app.core.scan as scan_mod

    res = scan_mod._scans_import_by_ids([])
    assert res == {"ok": True, "added": [], "skipped": []}


def test_scans_import_resolves_across_scans(tmp_path, monkeypatch) -> None:
    """Without a dirname, ids are resolved across every scan and grouped per owning dir."""
    import app.core.scan as scan_mod
    import app.core.state as state_mod

    sd = tmp_path / "st"
    sd.mkdir()
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd, raising=False)
    scans = sd / "scans"
    _write_results(scans, "scan-1", [{"id": "a", "title": "A", "proposal": "pa"}])
    _write_results(scans, "scan-2", [{"id": "b", "title": "B", "proposal": "pb"}])

    calls: list[tuple[str, list[str]]] = []

    def _fake_import(d: str, ids: list[str]) -> dict:
        calls.append((d, ids))
        return {"ok": True, "added": list(ids), "skipped": []}

    monkeypatch.setattr(scan_mod, "_scan_import", _fake_import)

    res = scan_mod._scans_import_by_ids(["a", "b"])
    assert res["ok"] is True
    assert set(res["added"]) == {"a", "b"}
    assert {d for d, _ in calls} == {"scan-1", "scan-2"}


def test_scans_import_dirname_pending_and_idempotent(tmp_path, monkeypatch) -> None:
    """With a dirname, findings land as `pending`; a second import skips them."""
    import app.core.scan as scan_mod
    import app.core.state as state_mod
    import app.core.ws_shim as shim
    from app.models.workspace import AgentRef, AgentsConfig

    sd = tmp_path / "state"
    sd.mkdir()
    (sd / "work-state.json").write_text(json.dumps({"items": []}))
    (sd / "decisions.log").write_text("")
    scans = sd / "scans"
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd, raising=False)

    agents = AgentsConfig(primary=AgentRef(provider="p", model="m"), fallback=AgentRef(provider="p", model="m"))
    prof = types.SimpleNamespace(id="ws01", name="r", repo_path=str(tmp_path), base_branch="main",
                                 remote="origin", branch_prefix="auto", memory_dir=".hephaestus/memory", agents=agents)
    monkeypatch.setattr(shim, "get_active_profile", lambda: prof)

    async def _fake_decompose(ws, proposals, *, scan_dir, runner, decomposer_ref=None):
        return [{"id": p["id"], "dependsOn": [], "epicId": None, "parent": None,
                 "orderIndex": i, "conflictGroup": None} for i, p in enumerate(proposals)]
    monkeypatch.setattr(scan_mod, "decompose_proposals", _fake_decompose)
    monkeypatch.setattr(scan_mod, "_build_runner", lambda *_a, **_k: None, raising=False)

    _write_results(scans, "scan-9", [
        {"id": "f1", "title": "F1", "proposal": "do f1", "category": "bug"},
        {"id": "f2", "title": "F2", "proposal": "do f2", "category": "quality"},
    ])

    res = scan_mod._scans_import_by_ids(["f1"], dirname="scan-9")
    assert res["added"] == ["f1"]
    items = {it["id"]: it for it in json.loads((sd / "work-state.json").read_text())["items"]}
    assert items["f1"]["status"] == "pending"
    assert "f2" not in items  # only the selected finding imported

    # Re-import the same id → idempotent skip, no duplicate.
    res2 = scan_mod._scans_import_by_ids(["f1"], dirname="scan-9")
    assert res2["added"] == []
    assert res2["skipped"] == ["f1"]
    items2 = json.loads((sd / "work-state.json").read_text())["items"]
    assert sum(1 for it in items2 if it["id"] == "f1") == 1
