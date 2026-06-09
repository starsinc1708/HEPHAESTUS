from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.doc_reader import DocReader

log = logging.getLogger("hephaestus.backend")

router = APIRouter()


def _get_doc_reader() -> DocReader:
    return DocReader()


# ---------------------------------------------------------------------------
# Documentation scanning
# ---------------------------------------------------------------------------


@router.get("/api/v1/repos/docs")
def scan_docs() -> dict[str, Any]:
    reader = _get_doc_reader()
    try:
        result = reader.scan_docs()
        return {
            "readme": result.get("readme", ""),
            "docs": result.get("docs", []),
            "tech_stack": result.get("tech_stack", []),
            "structure": result.get("structure", ""),
        }
    except Exception as exc:
        log.error("scan_docs failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/v1/repos/docs/readme")
def read_readme() -> dict[str, Any]:
    reader = _get_doc_reader()
    try:
        content = reader.read_readme()
        return {"ok": True, "content": content}
    except Exception as exc:
        log.error("read_readme failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/v1/repos/docs/file")
def read_file(path: str) -> dict[str, Any]:
    if not path:
        raise HTTPException(status_code=400, detail="path query parameter is required")
    reader = _get_doc_reader()
    try:
        content = reader.read_file(path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"file not found: {path}") from None
    except Exception as exc:
        log.error("read_file(%s) failed: %s", path, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if content is None:
        raise HTTPException(status_code=404, detail=f"file not found: {path}")
    return {"ok": True, "content": content}


# ---------------------------------------------------------------------------
# Context & tech stack
# ---------------------------------------------------------------------------


@router.get("/api/v1/repos/context")
def get_context() -> dict[str, Any]:
    reader = _get_doc_reader()
    try:
        context = reader.get_context_summary()
        return {"ok": True, "context": context}
    except Exception as exc:
        log.error("get_context_summary failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/api/v1/repos/tech-stack")
def get_tech_stack() -> dict[str, Any]:
    reader = _get_doc_reader()
    try:
        stack = reader.detect_tech_stack()
        return {"stack": stack}
    except Exception as exc:
        log.error("detect_tech_stack failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Task decomposition
# ---------------------------------------------------------------------------


@router.post("/api/v1/repos/decompose")
def decompose_task(body: dict[str, Any]) -> dict[str, Any]:
    title = body.get("title")
    description = body.get("description", "")
    context = body.get("context")
    if not title:
        raise HTTPException(status_code=400, detail="title is required")
    reader = _get_doc_reader()
    try:
        # context may be None when absent; preserve existing call semantics.
        subtasks = reader.decompose_task(title, description, context)  # type: ignore[arg-type]
        return {"ok": True, "subtasks": subtasks}
    except Exception as exc:
        log.error("decompose_task failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
