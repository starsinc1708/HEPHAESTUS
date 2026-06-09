"""#4 — PATCH /api/v1/tasks/{id}/deps sets dependsOn and recomputes blocks.

Happy path recomputes inverse blocks; 400 on self-ref / unknown id / cycle (with the
offending id surfaced); 404 on a missing task.
"""

from __future__ import annotations

import json
import pathlib

import app.core.state as state_mod

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def _seed(sd: pathlib.Path, items: list[dict]) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "work-state.json").write_text(json.dumps({"items": items}), encoding="utf-8")


def _items(sd: pathlib.Path) -> dict:
    raw = json.loads((sd / "work-state.json").read_text(encoding="utf-8"))["items"]
    return {it["id"]: it for it in raw}


def test_patch_deps_happy_recomputes_blocks(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [
        {"id": "a", "status": "pending"},
        {"id": "b", "status": "pending"},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.patch("/api/v1/tasks/b/deps", json={"dependsOn": ["a"]}, headers=_CSRF)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "id": "b", "dependsOn": ["a"]}

    items = _items(sd)
    assert items["b"]["dependsOn"] == ["a"]
    assert items["a"]["blocks"] == ["b"]  # inverse edge recomputed
    assert items["b"]["blocks"] == []


def test_patch_deps_self_ref_400(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "pending"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.patch("/api/v1/tasks/a/deps", json={"dependsOn": ["a"]}, headers=_CSRF)
    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False
    assert body.get("offending") == "a"


def test_patch_deps_unknown_id_400(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "pending"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.patch("/api/v1/tasks/a/deps", json={"dependsOn": ["ghost"]}, headers=_CSRF)
    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False
    assert body.get("offending") == "ghost"


def test_patch_deps_cycle_400(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    # a dependsOn b already; making b dependsOn a -> cycle.
    _seed(sd, [
        {"id": "a", "status": "pending", "dependsOn": ["b"]},
        {"id": "b", "status": "pending"},
    ])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.patch("/api/v1/tasks/b/deps", json={"dependsOn": ["a"]}, headers=_CSRF)
    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False
    assert body.get("offending") == "a"
    # b must remain unchanged on a rejected patch
    assert _items(sd)["b"].get("dependsOn", []) == []


def test_patch_deps_missing_task_404(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.patch("/api/v1/tasks/nope/deps", json={"dependsOn": []}, headers=_CSRF)
    assert r.status_code == 404
    assert r.json()["ok"] is False
