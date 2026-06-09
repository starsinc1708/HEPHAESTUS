"""Repository documentation reader for HEPHAESTUS — scans repos for context."""

from __future__ import annotations

import logging
import pathlib
import re
from typing import Any

from app.config import REPO

log = logging.getLogger("hephaestus.backend.doc_reader")

_SKIP_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "__pycache__",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".next",
        ".nuxt",
        "target",
        "vendor",
        ".venv",
        "venv",
        "env",
        ".env",
    }
)

_DOC_GLOBS = ["README*", "CONTRIBUTING*", "ARCHITECTURE*", "DESIGN*", "CHANGELOG*"]

_CONFIG_FILES: dict[str, str] = {
    "package.json": "javascript",
    "package-lock.json": "javascript",
    "pnpm-lock.yaml": "javascript",
    "yarn.lock": "javascript",
    "tsconfig.json": "typescript",
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "requirements.txt": "python",
    "Pipfile": "python",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "Gemfile": "ruby",
    "pom.xml": "java",
    "build.gradle": "java",
    "build.gradle.kts": "kotlin",
    "mix.exs": "elixir",
    "composer.json": "php",
    "*.csproj": "csharp",
    "*.sln": "csharp",
}

_FRAMEWORK_HINTS: dict[str, list[str]] = {
    "fastapi": ["fastapi"],
    "django": ["django"],
    "flask": ["flask"],
    "express": ["express"],
    "next.js": ["next"],
    "nuxt": ["nuxt"],
    "react": ["react"],
    "vue": ["vue"],
    "svelte": ["svelte"],
    "angular": ["@angular/core"],
    "actix": ["actix"],
    "rocket": ["rocket"],
    "axum": ["axum"],
    "gin": ["gin"],
    "rails": ["rails"],
}

_BINARY_EXTENSIONS = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".ico",
        ".webp",
        ".svg",
        ".zip",
        ".tar",
        ".gz",
        ".bz2",
        ".xz",
        ".7z",
        ".rar",
        ".bin",
        ".exe",
        ".dll",
        ".so",
        ".o",
        ".pyc",
        ".pyo",
        ".pdf",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".class",
        ".jar",
        ".wasm",
        ".mp3",
        ".mp4",
        ".avi",
        ".mov",
        ".wav",
        ".flac",
        ".webm",
    }
)

_SENSITIVE_PATTERNS: tuple[str, ...] = (
    ".env",
    ".env.local",
    ".env.production",
    ".env.development",
    ".env.staging",
)

_SENSITIVE_SUFFIXES: tuple[str, ...] = (
    ".key",
    ".pem",
    ".p12",
    ".pfx",
    ".jks",
    ".env",
)

_SENSITIVE_PREFIXES: tuple[str, ...] = (
    "id_",  # SSH private keys (id_rsa, id_ed25519, etc.)
)


class DocReader:
    """Repository documentation reader and analyzer."""

    def __init__(self, repo_path: pathlib.Path | None = None) -> None:
        # Default to the ACTIVE workspace repo (not the empty legacy REPO, which would
        # resolve to the dashboard's own cwd and read HEPHAESTUS's source instead).
        if repo_path is None:
            from app.core.helpers import _active_git

            repo_path = pathlib.Path(_active_git()[0] or REPO or ".")
        self.repo_path = repo_path

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------

    def _safe_resolve(self, relative_path: str) -> pathlib.Path | None:
        """Resolve a relative path and ensure it stays within the repo."""
        resolved = (self.repo_path / relative_path).resolve()
        repo_resolved = self.repo_path.resolve()
        try:
            resolved.relative_to(repo_resolved)
            return resolved
        except ValueError:
            log.error("Path traversal blocked: %s", relative_path)
            return None

    def _is_sensitive(self, resolved: pathlib.Path) -> bool:
        """Return True if the file should not be served through the dashboard."""
        name = resolved.name.lower()
        if name in _SENSITIVE_PATTERNS:
            return True
        return any(name.endswith(s) for s in _SENSITIVE_SUFFIXES) or any(
            name.startswith(p) for p in _SENSITIVE_PREFIXES
        )

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan_docs(self) -> dict[str, Any]:
        """Scan repo for all documentation files.

        Returns ``{readme, docs: [{path, size, type}], tech_stack: [str], structure: str}``.
        """
        readme = self.read_readme()
        docs: list[dict[str, Any]] = []

        # Root-level doc files
        for glob_pat in _DOC_GLOBS:
            for p in self.repo_path.glob(glob_pat):
                if p.is_file():
                    docs.append(self._file_info(p))

        # docs/ directory
        docs_dir = self.repo_path / "docs"
        if docs_dir.is_dir():
            for p in sorted(docs_dir.rglob("*")):
                if p.is_file() and p.suffix in (".md", ".rst", ".txt", ".adoc"):
                    docs.append(self._file_info(p))

        return {
            "readme": readme,
            "docs": docs,
            "tech_stack": self.detect_tech_stack(),
            "structure": self.get_structure(),
        }

    def _file_info(self, p: pathlib.Path) -> dict[str, Any]:
        try:
            stat = p.stat()
            return {
                "path": str(p.relative_to(self.repo_path)),
                "size": stat.st_size,
                "type": p.suffix.lstrip("."),
            }
        except Exception:
            log.debug("_file_info stat failed for %s", p, exc_info=True)
            return {"path": str(p), "size": 0, "type": ""}

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def read_readme(self, max_chars: int = 10000) -> str | None:
        """Read README content (truncated)."""
        for name in ("README.md", "README.rst", "README.txt", "README"):
            p = self.repo_path / name
            if p.is_file():
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                    return text[:max_chars]
                except Exception as exc:
                    log.error("Failed to read %s: %s", p, exc)
        return None

    def read_file(self, relative_path: str, max_chars: int = 20000) -> str | None:
        """Read a specific file from the repo (with path traversal + sensitive file protection)."""
        resolved = self._safe_resolve(relative_path)
        if resolved is None:
            return None
        if not resolved.is_file():
            return None
        if self._is_sensitive(resolved):
            log.warning("Sensitive file blocked: %s", relative_path)
            return None
        if resolved.suffix.lower() in _BINARY_EXTENSIONS:
            log.info("Skipping binary file: %s", relative_path)
            return None
        try:
            text = resolved.read_text(encoding="utf-8", errors="replace")
            return text[:max_chars]
        except Exception as exc:
            log.error("Failed to read %s: %s", relative_path, exc)
            return None

    # ------------------------------------------------------------------
    # Context / analysis
    # ------------------------------------------------------------------

    def get_context_summary(self) -> str:
        """Build a concise context summary for prompts."""
        parts: list[str] = []

        tech = self.detect_tech_stack()
        if tech:
            parts.append(f"Tech stack: {', '.join(tech)}")

        structure = self.get_structure(max_depth=1)
        if structure:
            parts.append(f"Structure:\n{structure}")

        readme = self.read_readme(max_chars=2000)
        if readme:
            parts.append(f"README excerpt:\n{readme}")

        return "\n\n".join(parts) if parts else "No context available"

    def detect_tech_stack(self) -> list[str]:
        """Detect technology stack from project files.

        Returns ``['python', 'fastapi', 'postgresql', 'react', ...]``.
        """
        stack: set[str] = set()

        # Phase 1: detect languages from config files
        for config_name, lang in _CONFIG_FILES.items():
            if config_name.startswith("*"):
                # Glob pattern
                if list(self.repo_path.glob(config_name)):
                    stack.add(lang)
            elif (self.repo_path / config_name).exists():
                stack.add(lang)

        # Phase 2: detect frameworks from package files
        self._detect_from_package_json(stack)
        self._detect_from_pyproject(stack)
        self._detect_from_cargo(stack)
        self._detect_from_go_mod(stack)

        # Phase 3: detect databases
        for hint in ("docker-compose.yml", "docker-compose.yaml"):
            dc = self.repo_path / hint
            if dc.exists():
                self._detect_from_docker_compose(dc, stack)

        return sorted(stack)

    def _detect_from_package_json(self, stack: set[str]) -> None:
        p = self.repo_path / "package.json"
        if not p.exists():
            return
        try:
            import json

            data = json.loads(p.read_text(encoding="utf-8"))
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            for framework, hints in _FRAMEWORK_HINTS.items():
                for hint in hints:
                    if hint in deps:
                        stack.add(framework)
                        break
        except Exception:
            log.debug("failed to detect frameworks from package.json", exc_info=True)
            pass

    def _detect_from_pyproject(self, stack: set[str]) -> None:
        p = self.repo_path / "pyproject.toml"
        if not p.exists():
            return
        try:
            content = p.read_text(encoding="utf-8")
            for framework, hints in _FRAMEWORK_HINTS.items():
                if any(h in content.lower() for h in hints):
                    stack.add(framework)
        except Exception:
            log.debug("failed to detect frameworks from pyproject.toml", exc_info=True)
            pass

    def _detect_from_cargo(self, stack: set[str]) -> None:
        p = self.repo_path / "Cargo.toml"
        if not p.exists():
            return
        try:
            content = p.read_text(encoding="utf-8")
            for framework, hints in _FRAMEWORK_HINTS.items():
                if any(h in content.lower() for h in hints):
                    stack.add(framework)
        except Exception:
            log.debug("failed to detect frameworks from Cargo.toml", exc_info=True)
            pass

    def _detect_from_go_mod(self, stack: set[str]) -> None:
        p = self.repo_path / "go.mod"
        if not p.exists():
            return
        try:
            content = p.read_text(encoding="utf-8")
            for framework, hints in _FRAMEWORK_HINTS.items():
                if any(h in content.lower() for h in hints):
                    stack.add(framework)
        except Exception:
            log.debug("failed to detect frameworks from go.mod", exc_info=True)
            pass

    @staticmethod
    def _detect_from_docker_compose(dc_path: pathlib.Path, stack: set[str]) -> None:
        try:
            content = dc_path.read_text(encoding="utf-8").lower()
            if "postgres" in content or "postgresql" in content:
                stack.add("postgresql")
            if "mysql" in content or "mariadb" in content:
                stack.add("mysql")
            if "redis" in content:
                stack.add("redis")
            if "mongo" in content:
                stack.add("mongodb")
        except Exception:
            log.debug("failed to detect databases from docker-compose", exc_info=True)
            pass

    def get_structure(self, max_depth: int = 2) -> str:
        """Get directory tree structure as string."""
        lines: list[str] = []
        self._build_tree(self.repo_path, lines, prefix="", max_depth=max_depth, depth=0)
        return "\n".join(lines)

    def _build_tree(
        self,
        directory: pathlib.Path,
        lines: list[str],
        prefix: str,
        max_depth: int,
        depth: int,
    ) -> None:
        if depth > max_depth:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
        except PermissionError:
            return
        # Filter out skip dirs
        entries = [e for e in entries if e.name not in _SKIP_DIRS and not e.name.startswith(".")]
        for i, entry in enumerate(entries):
            is_last = i == len(entries) - 1
            connector = "└── " if is_last else "├── "
            suffix = "/" if entry.is_dir() else ""
            lines.append(f"{prefix}{connector}{entry.name}{suffix}")
            if entry.is_dir():
                extension = "    " if is_last else "│   "
                self._build_tree(entry, lines, prefix + extension, max_depth, depth + 1)

    # ------------------------------------------------------------------
    # Task decomposition
    # ------------------------------------------------------------------

    def decompose_task(self, title: str, description: str, context: str = "") -> list[dict[str, Any]]:
        """Template-based task decomposition. Break a large task into subtasks.

        Returns ``[{title, description, priority, touches: [str]}]``.
        Uses simple heuristics — splits by sections, detects subtasks from bullet lists.
        """
        subtasks: list[dict[str, Any]] = []

        # Split on markdown headings
        sections = re.split(r"\n(?=#{1,3}\s)", description)
        if len(sections) > 1:
            for section in sections:
                if not section.strip():
                    continue
                lines = section.strip().splitlines()
                heading = lines[0].lstrip("#").strip()
                body = "\n".join(lines[1:]).strip()
                if heading and body:
                    subtasks.append(self._parse_subtask(heading, body))
        else:
            # Try bullet / numbered lists
            items = re.split(r"\n(?=[-\*]\s|\d+\.\s)", description)
            if len(items) > 1:
                for item in items:
                    item = item.strip()
                    if not item:
                        continue
                    first_line = item.splitlines()[0] if item else ""
                    # Strip bullet/number prefix
                    clean_title = re.sub(r"^[-*]\s+|\d+\.\s+", "", first_line).strip()
                    body = "\n".join(item.splitlines()[1:]).strip() if len(item.splitlines()) > 1 else ""
                    if clean_title:
                        subtasks.append(self._parse_subtask(clean_title, body or item))
            else:
                # Single task, return as-is
                subtasks.append(self._parse_subtask(title, description))

        return subtasks or [{"title": title, "description": description, "priority": "medium", "touches": []}]

    @staticmethod
    def _parse_subtask(title: str, description: str) -> dict[str, Any]:
        """Parse a subtask section into structured data."""
        title_lower = title.lower()

        # Priority from keywords
        if any(kw in title_lower for kw in ("must", "critical", "required", "essential")):
            priority = "high"
        elif any(kw in title_lower for kw in ("should", "important", "recommended")):
            priority = "medium"
        elif any(kw in title_lower for kw in ("could", "nice", "optional", "bonus")):
            priority = "low"
        else:
            priority = "medium"

        # Extract file paths
        touches: list[str] = []
        for match in re.finditer(r"`([^`]+\.\w+)`", description):
            touches.append(match.group(1))
        for match in re.finditer(r"(?:src|lib|test|tests)/[\w/.-]+\.\w{1,4}", description):
            path = match.group(0)
            if path not in touches:
                touches.append(path)

        return {
            "title": title[:200],
            "description": description[:2000],
            "priority": priority,
            "touches": touches[:20],
        }
