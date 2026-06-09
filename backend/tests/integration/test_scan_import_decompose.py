"""_scan_import runs decompose + memory. AgentRunner mocked."""
from __future__ import annotations

import json
import pathlib
import types


def _write_results(scans_dir: pathlib.Path, dirname: str, proposals: list[dict]) -> None:
    d = scans_dir / dirname
    d.mkdir(parents=True, exist_ok=True)
    (d / "results.json").write_text(json.dumps({"proposals": proposals, "n_unique": len(proposals)}))


def test_scan_import_decomposes_and_orders(tmp_path, monkeypatch) -> None:
    import app.core.scan as scan_mod
    import app.core.state as state_mod
    import app.core.ws_shim as shim
    from app.models.workspace import AgentRef, AgentsConfig

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "work-state.json").write_text(json.dumps({"items": []}))
    (state_dir / "decisions.log").write_text("")
    scans_dir = state_dir / "scans"
    # _scan_import + decisions both resolve via _state_dir(); the override drives them.
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", state_dir, raising=False)

    agents = AgentsConfig(primary=AgentRef(provider="p", model="m"), fallback=AgentRef(provider="p", model="m"))
    prof = types.SimpleNamespace(id="ws01", name="r", repo_path=str(tmp_path), base_branch="main",
                                 remote="origin", branch_prefix="auto", memory_dir=".hephaestus/memory", agents=agents)
    monkeypatch.setattr(shim, "get_active_profile", lambda: prof)

    _write_results(scans_dir, "scan-1", [
        {"id": "scan-a", "title": "A", "proposal": "do a", "touches": ["x.py"], "category": "bug", "severity": "high"},
        {"id": "scan-b", "title": "B", "proposal": "do b", "touches": ["y.py"], "category": "quality"},
    ])

    async def _fake_decompose(ws, proposals, *, scan_dir, runner, decomposer_ref=None):
        return [
            {"id": p["id"], "dependsOn": [], "epicId": None, "parent": None, "orderIndex": i, "conflictGroup": None}
            for i, p in enumerate(proposals)
        ]
    monkeypatch.setattr(scan_mod, "decompose_proposals", _fake_decompose)
    monkeypatch.setattr(scan_mod, "_build_runner", lambda *_a, **_k: None, raising=False)

    res = scan_mod._scan_import("scan-1", [])
    assert res["ok"] is True
    assert set(res["added"]) == {"scan-a", "scan-b"}
    s = json.loads((state_dir / "work-state.json").read_text())
    by_id = {it["id"]: it for it in s["items"]}
    assert "orderIndex" in by_id["scan-a"]
    assert any("scan-import" in line for line in (state_dir / "decisions.log").read_text().splitlines())
