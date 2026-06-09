"""Per-workspace prompt overrides: PromptManager resolution + ws-prompts API."""

from __future__ import annotations

import pathlib
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.services.prompt_manager import PromptManager

_CSRF = {"Origin": "http://localhost:8766", "Host": "localhost:8766"}


def test_override_shadows_global(tmp_path: pathlib.Path) -> None:
    g = tmp_path / "prompts"
    g.mkdir()
    (g / "system-prefix.md").write_text("GLOBAL {{x}}", encoding="utf-8")
    ov = tmp_path / "repo" / ".hephaestus" / "prompts"
    mgr = PromptManager(prompts_dir=g, override_dir=ov)

    # No override yet -> effective == global.
    assert mgr.get_prompt("system-prefix")["content"] == "GLOBAL {{x}}"
    assert mgr.is_overridden("system-prefix") is False
    detail = mgr.get_prompt_detail("system-prefix")
    assert detail["overridden"] is False
    assert detail["global"] == "GLOBAL {{x}}"

    # Write override -> effective switches; global is preserved.
    mgr.set_override("system-prefix", "REPO {{x}} {{y}}")
    assert mgr.is_overridden("system-prefix") is True
    d2 = mgr.get_prompt_detail("system-prefix")
    assert d2["content"] == "REPO {{x}} {{y}}"
    assert d2["global"] == "GLOBAL {{x}}"
    assert set(d2["variables"]) == {"x", "y"}
    assert mgr.render_prompt("system-prefix", {"x": "1", "y": "2"}) == "REPO 1 2"

    # Reset -> back to global, override file gone.
    mgr.clear_override("system-prefix")
    assert mgr.is_overridden("system-prefix") is False
    assert mgr.get_prompt("system-prefix")["content"] == "GLOBAL {{x}}"


@pytest.fixture
def _ws_client(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("HEPHAESTUS_HOME", str(tmp_path / "home"))
    import app.api.v1.workspaces as wsapi
    import app.core.workspaces as wsmod

    reg = wsmod.WorkspaceRegistry(home=tmp_path / "home")
    monkeypatch.setattr(wsmod, "registry", reg)
    monkeypatch.setattr(wsapi, "registry", reg)
    monkeypatch.setattr(wsapi, "_start_profiler", lambda _id, _repo: None)

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], capture_output=True, timeout=30, check=True)
    ws = reg.create(str(repo), name="repo")
    from app.main import app

    return TestClient(app), ws.id


def test_ws_prompt_override_roundtrip(_ws_client) -> None:
    client, ws_id = _ws_client
    base = f"/api/v1/workspaces/{ws_id}/prompts"

    # effective == global, not overridden (validate-lens ships globally)
    r = client.get(f"{base}/validate-lens")
    assert r.status_code == 200
    assert r.json()["overridden"] is False
    assert "VALIDATION_VERDICT_BEGIN" in r.json()["content"]

    # write a repo override
    r2 = client.put(f"{base}/validate-lens", json={"content": "MY REPO LENS {{lens}}"}, headers=_CSRF)
    assert r2.status_code == 200
    assert r2.json()["overridden"] is True
    assert r2.json()["content"] == "MY REPO LENS {{lens}}"

    # list shows it overridden
    rl = client.get(base)
    names = {p["name"]: p["overridden"] for p in rl.json()["prompts"]}
    assert names.get("validate-lens") is True

    # reset to global
    r3 = client.delete(f"{base}/validate-lens", headers=_CSRF)
    assert r3.status_code == 200
    assert r3.json()["overridden"] is False
    assert "VALIDATION_VERDICT_BEGIN" in r3.json()["content"]
