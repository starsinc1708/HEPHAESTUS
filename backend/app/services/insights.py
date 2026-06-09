"""Insights session store + read-only agentic project chat — Epic 4 (C1).

Insights runs are READ-ONLY: the agent is instructed not to modify files.
The loop never commits insights runs.
"""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import time
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.helpers import _run
from app.core.state import _atomic_write, _state_dir, _StateLock

log = logging.getLogger("hephaestus.backend.insights")

_REGISTRY = "insights.json"
_MAX_KEEP = 200


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class InsightsTurn(BaseModel):
    """A single turn in an insights conversation."""

    model_config = ConfigDict(populate_by_name=True)

    role: str
    content: str
    iter_dir: str | None = Field(None, alias="iterDir")


class InsightsSession(BaseModel):
    """A multi-turn insights conversation."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str = ""
    turns: list[InsightsTurn] = Field(default_factory=list)
    created_at: str | None = Field(None, alias="createdAt")
    updated_at: str | None = Field(None, alias="updatedAt")


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class InsightsStore:
    """Persist InsightsSession records as a rolling JSON registry in the state dir."""

    def _path(self) -> pathlib.Path:
        return _state_dir() / _REGISTRY

    def list(self) -> list[InsightsSession]:
        p = self._path()
        if not p.exists():
            return []
        try:
            raw = p.read_text(encoding="utf-8") or '{"sessions": []}'
            data: Any = json.loads(raw)
            return [InsightsSession.model_validate(s) for s in data.get("sessions", [])]
        except Exception as exc:
            log.warning("InsightsStore.list failed (%s)", exc)
            return []

    def get(self, session_id: str) -> InsightsSession | None:
        return next((s for s in self.list() if s.id == session_id), None)

    def put(self, session: InsightsSession) -> None:
        with _StateLock():
            sessions = [s for s in self.list() if s.id != session.id]
            sessions.append(session)
            sessions = sessions[-_MAX_KEEP:]
            payload = json.dumps(
                {"sessions": [s.model_dump(by_alias=True) for s in sessions]},
                indent=2,
                ensure_ascii=False,
            )
            self._path().parent.mkdir(parents=True, exist_ok=True)
            _atomic_write(self._path(), payload)


# ---------------------------------------------------------------------------
# Sequencing
# ---------------------------------------------------------------------------


def _next_insights_seq() -> int:
    """Return the next monotonically-increasing insights sequence number."""
    sd = _state_dir()
    nums: list[int] = []
    for p in sd.glob("insights-*"):
        part = p.name.split("-", 1)[1] if "-" in p.name else ""
        if p.is_dir() and part.isdigit():
            nums.append(int(part))
    return (max(nums) + 1) if nums else 1


# ---------------------------------------------------------------------------
# Answer extraction
# ---------------------------------------------------------------------------


def _extract_answer(jsonl_path: pathlib.Path) -> str:
    """Read the JSONL output, concatenate all ``text`` parts before a finish event.

    Returns "(no response)" if nothing is found.
    """
    if not jsonl_path.exists():
        return "(no response)"
    texts: list[str] = []
    try:
        for raw_line in jsonl_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            # Handle simple {"type":"text","text":"..."} shape (stub + opencode)
            obj_type = obj.get("type") or obj.get("event") or ""
            if obj_type == "text":
                t = obj.get("text", "")
                if t:
                    texts.append(str(t))
                continue
            # Handle Claude CLI stream-json {"type":"assistant","message":{"content":[...]}}
            msg = obj.get("message")
            if isinstance(msg, dict) and isinstance(msg.get("content"), list):
                for block in msg["content"]:
                    if isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                        texts.append(str(block["text"]))
                continue
            # Handle opencode part shape {"part":{"type":"text","text":"..."}}
            part = obj.get("part") if isinstance(obj.get("part"), dict) else None
            if part and part.get("type") == "text":
                t = part.get("text", "")
                if t:
                    texts.append(str(t))
    except Exception as exc:
        log.warning("_extract_answer failed (%s)", exc)
    return "\n".join(texts).strip() or "(no response)"


# ---------------------------------------------------------------------------
# Core ask function
# ---------------------------------------------------------------------------


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


async def ask(
    ws: Any,
    question: str,
    *,
    session_id: str | None,
    runner: Any,
) -> dict[str, Any]:
    """Run a read-only agentic codebase question and persist the turn.

    Steps:
    1. Load or create session (id "ins-" + sha1[:8]).
    2. Append user turn.
    3. Allocate insights-NNNN dir; build and render prompt.
    4. Run agent (read-only cwd=repo).
    5. Detect unexpected file modifications (log warning, NO auto-clean).
    6. Extract answer; append assistant turn; persist; return dict.

    Never raises — agent failure returns answer="(no response)".
    """
    from app.services import codebase_map, project_memory
    from app.services.prompt_manager import PromptManager

    store = InsightsStore()

    # 1. Load or create session
    session = store.get(session_id) if session_id else None

    if session is None:
        seed = f"{question}|{time.time()}"
        new_id = "ins-" + hashlib.sha1(seed.encode()).hexdigest()[:8]
        session = InsightsSession(
            id=new_id,
            title=question[:80],
            created_at=_now(),
            updated_at=_now(),
        )

    # 2. Append user turn
    session.turns.append(InsightsTurn(role="user", content=question))
    session.updated_at = _now()
    store.put(session)

    # 3. Allocate insights dir and build prompt
    seq = _next_insights_seq()
    dirname = f"insights-{seq:04d}"
    ins_dir = _state_dir() / dirname
    ins_dir.mkdir(parents=True, exist_ok=True)

    # Build history excerpt (cap to last 10 turns)
    history_turns = session.turns[:-1][-10:]  # exclude the just-appended user turn
    if history_turns:
        history_lines: list[str] = []
        for t in history_turns:
            prefix = "User" if t.role == "user" else "Assistant"
            history_lines.append(f"**{prefix}:** {t.content[:500]}")
        history = "\n\n".join(history_lines)
    else:
        history = "(none)"

    raw_map = codebase_map.read_map(ws)
    map_json = json.dumps(raw_map, ensure_ascii=False)[:1500]

    memory_excerpt = (project_memory.read_doc(ws, "architecture") or "")[:2000]

    git_log = _run(
        ["git", "log", "-n", "20", "--pretty=%h %s"],
        cwd=ws.repo_path,
        default="",
    )

    pm = PromptManager()
    prompt = pm.render_prompt(
        "insights",
        {
            "question": question,
            "history": history,
            "codebase_map": map_json,
            "memory_excerpt": memory_excerpt,
            "git_log": git_log,
        },
    ) or ""

    prompt_file = ins_dir / "insights.prompt.md"
    prompt_file.write_text(prompt, encoding="utf-8")
    output_path = ins_dir / "output.insights.jsonl"

    # 4. Snapshot git status before run (read-only guard)
    before = _run(["git", "status", "--porcelain"], cwd=ws.repo_path, default="")

    answer = "(no response)"
    try:
        ref = ws.agents.primary
        result = await runner.run(
            ref,
            prompt_file=prompt_file,
            cwd=ws.repo_path,
            output_path=output_path,
            timeout_sec=ws.verify_timeout_sec,
            use_models=False,
        )
        if result.refused:
            log.warning("insights ask: agent refused (session=%s)", session.id)
        else:
            answer = _extract_answer(output_path)
    except Exception as exc:
        log.warning("insights ask: runner failed (%s) — returning (no response)", exc)

    # 5. Detect modifications (log only, no auto-clean)
    after = _run(["git", "status", "--porcelain"], cwd=ws.repo_path, default="")
    modified: list[str] = []
    if after != before:
        before_lines = set(before.splitlines())
        after_lines = set(after.splitlines())
        modified = sorted(after_lines - before_lines)
        log.warning(
            "insights ask: READ-ONLY violation — agent modified files: %s",
            modified,
        )

    # 6. Append assistant turn and persist
    session.turns.append(
        InsightsTurn(role="assistant", content=answer, iter_dir=dirname)
    )
    session.updated_at = _now()
    store.put(session)

    return {
        "sessionId": session.id,
        "iterDir": dirname,
        "answer": answer,
        "modifiedFiles": modified,
    }
