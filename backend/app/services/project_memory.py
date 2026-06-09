"""MemoryWriter/Reader for <repo>/.hephaestus/memory/*.md with YAML frontmatter (umbrella §4.3)."""
from __future__ import annotations

import logging
import pathlib
import time
from typing import TYPE_CHECKING, Any

from app.core.state import _atomic_write

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

log = logging.getLogger("hephaestus.backend.project_memory")

DOCS = ("index", "architecture", "verify", "conventions", "tech-debt")
_FILENAME = {
    "index": "MEMORY.md",
    "architecture": "architecture.md",
    "verify": "verify.md",
    "conventions": "conventions.md",
    "tech-debt": "tech-debt.md",
}


def utcnow_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def memory_dir(ws: RepoProfile) -> pathlib.Path:
    return pathlib.Path(ws.repo_path) / ws.memory_dir


def _frontmatter(doc: str, ws_id: str, source: str) -> str:
    return (
        f"---\ndoc: {doc}\nworkspace_id: {ws_id}\n"
        f"updated_at: {utcnow_iso()}\nsource: {source}\nschema: 1\n---\n"
    )


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Return (meta-dict, body-without-frontmatter). No frontmatter → ({}, text)."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines(keepends=True)
    end = None
    for i in range(1, min(len(lines), 40)):  # frontmatter is compact; never scan into body
        if lines[i].rstrip("\n") == "---":
            end = i
            break
    if end is None:
        return {}, text
    meta: dict[str, Any] = {}
    for ln in lines[1:end]:
        if ":" in ln:
            k, _, v = ln.partition(":")
            val = v.strip()
            if val.isdigit():
                meta[k.strip()] = int(val)
            else:
                meta[k.strip()] = val
    body = "".join(lines[end + 1 :])
    return meta, body


def _validate_doc(doc: str) -> None:
    if doc not in DOCS:
        raise ValueError(f"unknown memory doc: {doc} (allowed: {', '.join(DOCS)})")


def read_doc(ws: RepoProfile, doc: str) -> str | None:
    """Read raw file body (without frontmatter). Unknown doc or missing file → None."""
    if doc not in DOCS:
        return None
    p = memory_dir(ws) / _FILENAME[doc]
    if not p.exists():
        return None
    try:
        _, body = _parse_frontmatter(p.read_text(encoding="utf-8"))
        return body
    except Exception as exc:
        log.error("read_doc %s failed: %s", doc, exc)
        return None


def read_doc_full(ws: RepoProfile, doc: str) -> tuple[dict[str, Any], str]:
    """Read (frontmatter-dict, body). Used by backward-compat ProjectMemory class."""
    if doc not in _FILENAME:
        return {}, ""
    p = memory_dir(ws) / _FILENAME[doc]
    if not p.exists():
        return {}, ""
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
        return _parse_frontmatter(raw)
    except Exception:
        return {}, ""


def write_doc(ws: RepoProfile, doc: str, body: str, *, source: str) -> pathlib.Path:
    """Write <repo>/.hephaestus/memory/<file> with frontmatter + body (atomic). Updates MEMORY.md index."""
    _validate_doc(doc)
    mdir = memory_dir(ws)
    mdir.mkdir(parents=True, exist_ok=True)
    p = mdir / _FILENAME[doc]
    _atomic_write(p, _frontmatter(doc, ws.id, source) + body)
    if doc != "index":
        _refresh_index(ws, source=source)
    return p


def _refresh_index(ws: RepoProfile, *, source: str) -> None:
    mdir = memory_dir(ws)
    lines = ["# HEPHAESTUS Project Memory", "", f"Updated: {utcnow_iso()}", ""]
    for doc in DOCS:
        if doc == "index":
            continue
        fname = _FILENAME[doc]
        exists = (mdir / fname).exists()
        mark = "x" if exists else " "
        lines.append(f"- [{mark}] [{doc}]({fname})")
    body = "\n".join(lines) + "\n"
    _atomic_write(mdir / _FILENAME["index"], _frontmatter("index", ws.id, source) + body)


def read_verify_commands(ws: RepoProfile) -> list[str]:
    """Parse verify.md: the ```sh ... ``` block under '## commands' → list of commands."""
    body = read_doc(ws, "verify")
    if not body:
        return []
    import re
    m = re.search(r"##\s*commands\s*\n```(?:sh|bash)?\s*\n(.*?)\n```", body, re.S)
    if not m:
        return []
    return [
        ln.strip()
        for ln in m.group(1).splitlines()
        if ln.strip() and not ln.strip().startswith("#")
    ]


def init_verify_if_empty(ws: RepoProfile) -> bool:
    """Idempotent: only write verify.md if it has no commands. Returns True if written."""
    existing = read_verify_commands(ws)
    if existing:
        return False
    from app.services.verify_detect import detect_verify_commands
    cmds = detect_verify_commands(pathlib.Path(ws.repo_path))
    if not cmds:
        return False
    verify_body = "## commands\n```sh\n" + "\n".join(cmds) + "\n```\n"
    write_doc(ws, "verify", verify_body, source="auto-detect")
    return True


def init_memory(
    ws: RepoProfile,
    *,
    architecture: str,
    verify_commands: list[str],
    conventions: str,
    tech_debt: str,
) -> None:
    """Profiler onboarding — write initial memory docs."""
    write_doc(ws, "architecture", architecture, source="profiler")
    verify_body = "## commands\n```sh\n" + "\n".join(verify_commands) + "\n```\n"
    write_doc(ws, "verify", verify_body, source="profiler")
    write_doc(ws, "conventions", conventions, source="profiler")
    write_doc(ws, "tech-debt", tech_debt, source="profiler")


_MEMORY_MAX_LINES = 150  # research (ETH Zurich AGENTS.md, 2026): keep memory SHORT


def _upsert_section(
    body: str, header: str, content_lines: list[str], *, max_lines: int = _MEMORY_MAX_LINES
) -> str:
    """Replace (or append) a '## <header>' section, then cap the doc by dropping the OLDEST
    sections (preamble/title kept). Deduplicates re-scans/re-tasks and bounds memory length."""
    preamble: list[str] = []
    sections: list[list[str]] = []
    cur: list[str] | None = None
    for ln in body.splitlines():
        if ln.startswith("## "):
            cur = [ln]
            sections.append(cur)
        elif cur is None:
            preamble.append(ln)
        else:
            cur.append(ln)
    sections = [s for s in sections if s[0].strip() != header.strip()]  # dedup same key
    sections.append([header, *content_lines])
    while len(sections) > 1 and len(preamble) + sum(len(s) for s in sections) > max_lines:
        sections.pop(0)  # drop oldest section to stay under the budget
    out = [*preamble, *(ln for s in sections for ln in s)]
    return "\n".join(out).rstrip() + "\n"


def update_after_scan(ws: RepoProfile, *, scan_dir: str, proposals: list[dict[str, Any]]) -> None:
    """Upsert a '## from scan <dir>' section in tech-debt.md (high/security/bug items only).
    Dedups a re-scanned dir and caps the doc so memory stays short."""
    relevant = [
        p
        for p in proposals
        if (p.get("category") in ("bug", "security")) or (p.get("severity") == "high")
    ]
    if not relevant:
        return
    existing = read_doc(ws, "tech-debt") or "# Tech Debt"
    content = [
        f"- [{p.get('category', '?')}/{p.get('severity', '?')}] {p.get('title', p.get('id', '?'))}"
        for p in relevant
    ]
    new_body = _upsert_section(existing, f"## from scan {scan_dir}", content)
    write_doc(ws, "tech-debt", new_body, source="scan")


def update_after_task(ws: RepoProfile, *, task: dict[str, Any], summary: str) -> None:
    """After a done task: upsert a '## from task <id>' convention note. Dedup + cap."""
    if not summary.strip():
        return
    existing = read_doc(ws, "conventions") or "# Conventions"
    new_body = _upsert_section(existing, f"## from task {task.get('id', '?')}", [f"- {summary.strip()}"])
    write_doc(ws, "conventions", new_body, source="task")


def _similar(a: str, b: str, threshold: float = 0.7) -> bool:
    a_trunc = a[:60].strip()
    b_trunc = b[:60].strip()
    if not a_trunc or not b_trunc:
        return False
    import difflib
    ratio = difflib.SequenceMatcher(None, a_trunc, b_trunc).ratio()
    return ratio >= threshold


def add_lesson(ws: RepoProfile, *, lesson: str, task_id: str) -> bool:
    """Append a lesson to conventions.md with dedup.

    Returns False if a similar lesson already exists (fuzzy match on first 60 chars).
    """
    existing = read_doc(ws, "conventions") or "# Conventions"
    # Dedup: check if a line with >70% overlap exists. lstrip the leading "- " bullet but
    # rstrip whitespace only — str.strip("- ") would also eat a trailing dash, mangling
    # rules that end in a CLI flag (e.g. "NEVER pass --no-verify").
    for line in existing.splitlines():
        if _similar(line.lstrip("- ").rstrip(), lesson, threshold=0.7):
            return False
    new_body = _upsert_section(
        existing,
        f"## lesson from {task_id}",
        [f"- {lesson}"],
    )
    write_doc(ws, "conventions", new_body, source="lesson")
    return True


# ── Backward-compatible class wrapper (used by profiler.py, verify.py, existing tests) ──

class ProjectMemory:
    """Thin wrapper delegating to module-level functions. Preserved for backward compat."""

    def __init__(self, ws: RepoProfile) -> None:
        self.ws = ws

    def ensure_dir(self) -> pathlib.Path:
        d = memory_dir(self.ws)
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_doc(self, doc: str, body: str, *, source: str) -> pathlib.Path:
        return write_doc(self.ws, doc, body, source=source)

    def read_doc(self, doc: str) -> tuple[dict[str, Any], str]:
        return read_doc_full(self.ws, doc)

    def read_verify_commands(self) -> list[str]:
        return read_verify_commands(self.ws)

    def bootstrap_index(self) -> None:
        _refresh_index(self.ws, source="profiler")
