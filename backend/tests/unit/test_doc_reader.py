"""Tests for DocReader path traversal protection and sensitive file blocking (SEC-007)."""
from __future__ import annotations

import pathlib

import pytest

from app.services.doc_reader import DocReader


def _can_symlink() -> bool:
    """Check whether we can create symlinks on this platform."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        src = pathlib.Path(td) / "src"
        src.touch()
        dst = pathlib.Path(td) / "dst"
        try:
            dst.symlink_to(src)
            return True
        except (OSError, NotImplementedError):
            return False


@pytest.fixture
def repo(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a minimal repo tree for testing."""
    # Normal files
    (tmp_path / "README.md").write_text("# Hello", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("print('hi')", encoding="utf-8")
    # Sensitive files inside repo
    (tmp_path / ".env").write_text("SECRET=abc", encoding="utf-8")
    (tmp_path / "deploy.key").write_text("-----BEGIN RSA...", encoding="utf-8")
    (tmp_path / "cert.pem").write_text("-----BEGIN CERT...", encoding="utf-8")
    (tmp_path / "id_rsa").write_text("-----BEGIN RSA...", encoding="utf-8")
    (tmp_path / "id_ed25519").write_text("-----BEGIN OPENSSH...", encoding="utf-8")
    (tmp_path / "config.p12").write_bytes(b"\x00\x01\x02")
    (tmp_path / "src" / "local.env").write_text("DB=local", encoding="utf-8")
    return tmp_path


class TestPathTraversal:
    """Verify _safe_resolve blocks directory traversal attacks."""

    def test_parent_traversal(self, repo: pathlib.Path) -> None:
        reader = DocReader(repo)
        assert reader._safe_resolve("../../../etc/passwd") is None

    def test_dotdot_in_middle(self, repo: pathlib.Path) -> None:
        reader = DocReader(repo)
        assert reader._safe_resolve("src/../../../etc/shadow") is None

    def test_absolute_path(self, repo: pathlib.Path) -> None:
        reader = DocReader(repo)
        assert reader._safe_resolve("/etc/passwd") is None

    @pytest.mark.skipif(
        not _can_symlink(),
        reason="Symlinks not available on this platform without elevated privileges",
    )
    def test_symlink_escape(self, repo: pathlib.Path) -> None:
        link = repo / "escape"
        link.symlink_to(repo.parent)
        reader = DocReader(repo)
        assert reader._safe_resolve("escape/secret") is None

    def test_valid_relative_path(self, repo: pathlib.Path) -> None:
        reader = DocReader(repo)
        result = reader._safe_resolve("src/main.py")
        assert result is not None
        assert result.name == "main.py"


class TestSensitiveFiles:
    """Verify _is_sensitive blocks sensitive file patterns."""

    def test_env_file_blocked(self, repo: pathlib.Path) -> None:
        reader = DocReader(repo)
        assert reader.read_file(".env") is None

    def test_key_file_blocked(self, repo: pathlib.Path) -> None:
        reader = DocReader(repo)
        assert reader.read_file("deploy.key") is None

    def test_pem_file_blocked(self, repo: pathlib.Path) -> None:
        reader = DocReader(repo)
        assert reader.read_file("cert.pem") is None

    def test_ssh_key_blocked(self, repo: pathlib.Path) -> None:
        reader = DocReader(repo)
        assert reader.read_file("id_rsa") is None

    def test_ed25519_key_blocked(self, repo: pathlib.Path) -> None:
        reader = DocReader(repo)
        assert reader.read_file("id_ed25519") is None

    def test_p12_file_blocked(self, repo: pathlib.Path) -> None:
        reader = DocReader(repo)
        assert reader.read_file("config.p12") is None

    def test_env_inside_subdir_blocked(self, repo: pathlib.Path) -> None:
        reader = DocReader(repo)
        assert reader.read_file("src/local.env") is None

    def test_normal_file_allowed(self, repo: pathlib.Path) -> None:
        reader = DocReader(repo)
        content = reader.read_file("src/main.py")
        assert content is not None
        assert "print" in content

    def test_readme_allowed(self, repo: pathlib.Path) -> None:
        reader = DocReader(repo)
        content = reader.read_file("README.md")
        assert content is not None
        assert "Hello" in content

    def test_nonexistent_file(self, repo: pathlib.Path) -> None:
        reader = DocReader(repo)
        assert reader.read_file("nonexistent.txt") is None

    def test_traversal_with_sensitive_name(self, repo: pathlib.Path) -> None:
        """Even if path traversal somehow resolved to a .env, it should be blocked."""
        reader = DocReader(repo)
        # Direct attempt
        assert reader.read_file(".env") is None
        # The traversal itself is blocked first
        assert reader.read_file("../../../.env") is None
