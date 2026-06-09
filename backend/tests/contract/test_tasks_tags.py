"""#7 — PATCH /api/v1/tasks/{id}/tags sets tags with normalization.

Happy path sets tags on an existing task; normalization strips whitespace, removes
empties, and deduplicates; validation rejects >10 tags or >30-char tags; 404 on
missing task.
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


def test_patch_tags_happy(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "pending"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.patch("/api/v1/tasks/a/tags", json={"tags": ["ui", "backend"]}, headers=_CSRF)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "id": "a", "tags": ["ui", "backend"]}

    assert _items(sd)["a"]["tags"] == ["ui", "backend"]


def test_patch_tags_normalizes(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "pending"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.patch(
        "/api/v1/tasks/a/tags",
        json={"tags": ["  ui  ", "ui", "  ", "backend", "backend"]},
        headers=_CSRF,
    )
    assert r.status_code == 200
    # "  ui  " trimmed → "ui", duplicate "ui" removed, empty "  " removed,
    # duplicate "backend" removed
    assert r.json() == {"ok": True, "id": "a", "tags": ["ui", "backend"]}


def test_patch_tags_too_many_400(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "pending"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.patch(
        "/api/v1/tasks/a/tags",
        json={"tags": [str(i) for i in range(11)]},
        headers=_CSRF,
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_patch_tags_too_long_400(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [{"id": "a", "status": "pending"}])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.patch(
        "/api/v1/tasks/a/tags",
        json={"tags": ["ok", "x" * 31]},
        headers=_CSRF,
    )
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_patch_tags_missing_task_404(tmp_path, monkeypatch, client) -> None:
    sd = tmp_path / "state"
    _seed(sd, [])
    monkeypatch.setattr(state_mod, "_STATE_DIR_OVERRIDE", sd)

    r = client.patch("/api/v1/tasks/nope/tags", json={"tags": ["ui"]}, headers=_CSRF)
    assert r.status_code == 404
    assert r.json()["ok"] is False
