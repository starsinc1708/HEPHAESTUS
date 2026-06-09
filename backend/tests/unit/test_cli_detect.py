import app.services.cli_detect as cd


def test_detect_marks_installed_and_version(monkeypatch):
    monkeypatch.setattr(cd.shutil, "which", lambda name: f"/usr/bin/{name}" if name in ("claude", "codex") else None)
    monkeypatch.setattr(cd, "_version", lambda exe: "1.2.3")
    monkeypatch.setattr(cd, "_opencode_providers", lambda: [])
    out = cd.detect_clis()
    assert out["claude"]["installed"] is True and out["claude"]["version"] == "1.2.3"
    assert out["opencode"]["installed"] is False
    assert out["codex"]["installed"] is True


def test_opencode_auth_parsing(monkeypatch):
    sample = "Providers\n  anthropic  logged in\n  openai     api key\n"
    monkeypatch.setattr(cd, "_run", lambda *a, **k: sample)
    assert set(cd._parse_opencode_auth(sample)) >= {"anthropic", "openai"}
