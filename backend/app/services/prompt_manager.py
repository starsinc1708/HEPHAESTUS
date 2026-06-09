"""Prompt template manager for HEPHAESTUS — file-based CRUD with variable injection."""

from __future__ import annotations

import logging
import pathlib
import re
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

from app.config import LOOP_HOME
from app.core.state import _atomic_write

log = logging.getLogger("hephaestus.backend.prompt_manager")

_VAR_RE = re.compile(r"\{\{(\w+)\}\}")
_SAFE_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


class PromptManager:
    """File-based prompt template management with ``{{variable}}`` injection."""

    def __init__(self, prompts_dir: pathlib.Path | None = None,
                 override_dir: pathlib.Path | None = None,
                 ws: RepoProfile | None = None) -> None:
        self.prompts_dir = prompts_dir or (LOOP_HOME / "prompts")
        # Optional per-workspace override dir (<repo>/.hephaestus/prompts). When a file
        # exists here it shadows the global template for reads/rendering.
        self.override_dir = override_dir
        self._ws = ws
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Create prompts dir if not exists."""
        try:
            self.prompts_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            log.error("Failed to create prompts dir %s: %s", self.prompts_dir, exc)

    @staticmethod
    def _validate_name(name: str) -> bool:
        """Reject names that could cause path traversal."""
        return bool(_SAFE_NAME_RE.match(name))

    @staticmethod
    def _extract_variables(content: str) -> list[str]:
        """Find all ``{{var}}`` patterns in content."""
        return sorted(set(_VAR_RE.findall(content)))

    def _path_for(self, name: str) -> pathlib.Path:
        return self.prompts_dir / f"{name}.md"

    def _override_path(self, name: str) -> pathlib.Path | None:
        if self.override_dir is None:
            return None
        return self.override_dir / f"{name}.md"

    def _effective_path(self, name: str) -> pathlib.Path:
        """Override file if it exists, otherwise the global template."""
        ov = self._override_path(name)
        if ov is not None and ov.exists():
            return ov
        return self._path_for(name)

    def is_overridden(self, name: str) -> bool:
        ov = self._override_path(name)
        return ov is not None and ov.exists()

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def list_prompts(self) -> list[dict[str, Any]]:
        """List all prompt templates.

        Returns ``[{name, filename, size, modified_at, has_variables}]``.
        """
        prompts: list[dict[str, Any]] = []
        for p in sorted(self.prompts_dir.glob("*.md")):
            try:
                content = p.read_text(encoding="utf-8")
                variables = self._extract_variables(content)
                stat = p.stat()
                prompts.append(
                    {
                        "name": p.stem,
                        "filename": p.name,
                        "size": stat.st_size,
                        "modified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
                        "has_variables": len(variables) > 0,
                        "variables": variables,
                    }
                )
            except Exception as exc:
                log.error("Failed to read prompt %s: %s", p, exc)
        return prompts

    def get_prompt(self, name: str) -> dict[str, Any] | None:
        """Get a prompt template by name (without .md extension).

        Returns ``{name, content, variables: [str], modified_at}``.
        """
        if not self._validate_name(name):
            log.error("Invalid prompt name: %s", name)
            return None
        p = self._effective_path(name)
        if not p.exists():
            return None
        try:
            content = p.read_text(encoding="utf-8")
            stat = p.stat()
            return {
                "name": name,
                "content": content,
                "variables": self._extract_variables(content),
                "modified_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stat.st_mtime)),
            }
        except Exception as exc:
            log.error("Failed to read prompt %s: %s", name, exc)
            return None

    def get_prompt_detail(self, name: str) -> dict[str, Any] | None:
        """Effective + global content + override flag for the per-workspace editor.

        ``content`` is what the engine actually renders (override if present, else global);
        ``global`` is the shipped template; ``overridden`` whether a repo override exists.
        """
        if not self._validate_name(name):
            return None
        gp = self._path_for(name)
        global_content = gp.read_text(encoding="utf-8") if gp.exists() else None
        overridden = self.is_overridden(name)
        eff = self._effective_path(name)
        if not eff.exists():
            return None
        content = eff.read_text(encoding="utf-8")
        return {
            "name": name,
            "content": content,
            "global": global_content,
            "overridden": overridden,
            "variables": self._extract_variables(content),
        }

    def set_override(self, name: str, content: str) -> dict[str, Any] | None:
        """Write a per-workspace override at ``<override_dir>/<name>.md``."""
        if self.override_dir is None or not self._validate_name(name):
            return None
        if len(content) > 100_000:
            log.error("override content too large for %s", name)
            return None
        try:
            self.override_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(self.override_dir / f"{name}.md", content)
        except Exception as exc:
            log.error("Failed to write override %s: %s", name, exc)
            return None
        return self.get_prompt_detail(name)

    def clear_override(self, name: str) -> dict[str, Any] | None:
        """Remove the per-workspace override (reset to the global template)."""
        ov = self._override_path(name)
        if ov is None or not self._validate_name(name):
            return None
        try:
            ov.unlink(missing_ok=True)
        except Exception as exc:
            log.error("Failed to clear override %s: %s", name, exc)
            return None
        return self.get_prompt_detail(name)

    def update_prompt(self, name: str, content: str) -> dict[str, Any] | None:
        """Create or update a prompt template.

        Returns ``{name, content, variables: [str]}``.
        """
        if not self._validate_name(name):
            log.error("Invalid prompt name: %s", name)
            return None
        # Validate content size (100KB max)
        _MAX_CONTENT_SIZE = 100_000
        if len(content) > _MAX_CONTENT_SIZE:
            log.error("Prompt content too large: %d bytes (max %d)", len(content), _MAX_CONTENT_SIZE)
            return None
        # Check for malformed variable syntax
        open_count = content.count("{{")
        close_count = content.count("}}")
        if open_count != close_count:
            log.warning(
                "Prompt '%s' has unmatched variable delimiters: {{ = %d, }} = %d",
                name,
                open_count,
                close_count,
            )
        try:
            _atomic_write(self._path_for(name), content)
            return {
                "name": name,
                "content": content,
                "variables": self._extract_variables(content),
            }
        except Exception as exc:
            log.error("Failed to write prompt %s: %s", name, exc)
            return None

    def delete_prompt(self, name: str) -> bool:
        """Delete a prompt template. Returns ``True`` if deleted."""
        if not self._validate_name(name):
            return False
        p = self._path_for(name)
        try:
            if p.exists():
                p.unlink()
                return True
            return False
        except Exception as exc:
            log.error("Failed to delete prompt %s: %s", name, exc)
            return False

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render_prompt(self, name: str, variables: dict[str, Any]) -> str | None:
        """Render a prompt template with variables substituted.

        Variables use ``{{variable_name}}`` syntax.
        Unknown variables left as-is.
        """
        data = self.get_prompt(name)
        if data is None:
            return None
        content = data["content"]

        def _replace(m: re.Match[str]) -> str:
            key = m.group(1)
            return str(variables.get(key, m.group(0)))

        return _VAR_RE.sub(_replace, content)

    def get_system_prompt(self) -> str:
        """Get the main ``system-prefix.md`` prompt."""
        data = self.get_prompt("system-prefix")
        return data["content"] if data else ""

    def build_task_prompt(self, item: dict[str, Any], repo_context: str = "") -> str:
        """Build a complete task prompt from template + item + repo context.

        Uses ``system-prefix.md`` as base, injects task details.
        """
        parts: list[str] = []

        # System prefix
        system = self.get_system_prompt()
        if system:
            parts.append(system)

        # Task details
        task_parts: list[str] = [f"# Task: {item.get('title', 'Untitled')}"]
        if item.get("proposal"):
            task_parts.append(f"\n## Proposal\n\n{item['proposal']}")
        if item.get("why"):
            task_parts.append(f"\n## Why\n\n{item['why']}")
        if item.get("acceptance"):
            task_parts.append(f"\n## Acceptance Criteria\n\n{item['acceptance']}")
        if item.get("touches"):
            files = "\n".join(f"- `{t}`" for t in item["touches"])
            task_parts.append(f"\n## Files to Touch\n\n{files}")
        parts.append("\n".join(task_parts))

        # Repo context
        if repo_context:
            parts.append(f"\n## Repository Context\n\n{repo_context}")

        # Inject learned conventions from memory
        if self._ws:
            from app.services.project_memory import read_doc
            conventions = read_doc(self._ws, "conventions")
            if conventions:
                parts.append(f"\n## Project Conventions & Lessons\n\n{conventions}")

        return "\n\n---\n\n".join(parts)
