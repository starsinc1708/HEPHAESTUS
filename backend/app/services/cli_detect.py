"""Detect which agent CLIs are installed/logged in → drives capability gating."""
from __future__ import annotations

import shutil
import subprocess
from typing import Any

_CLIS = ("claude", "opencode", "codex")


def _run(argv: list[str], timeout: int = 8) -> str:
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=timeout).stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _version(exe: str) -> str | None:
    out = _run([exe, "--version"]).strip()
    return out.splitlines()[0] if out else None


def _parse_opencode_auth(text: str) -> list[str]:
    provs: list[str] = []
    for ln in text.splitlines():
        s = ln.strip()
        if s and " " in s and not s.lower().startswith("provider"):
            provs.append(s.split()[0])
    return provs


def _opencode_providers() -> list[str]:
    return _parse_opencode_auth(_run(["opencode", "auth", "list"]))


def detect_clis() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for name in _CLIS:
        exe = shutil.which(name)
        info: dict[str, Any] = {"installed": exe is not None, "version": None, "auth": {}}
        if exe:
            info["version"] = _version(exe)
            if name == "opencode":
                info["auth"] = {"providers": _opencode_providers()}
            else:
                info["auth"] = {"unknown": True}  # no cheap whoami → the connection test is the truth
        out[name] = info
    return out
