"""Native map-reduce scan worker (R19, D1). Runs INSIDE the supervised `scan` process with
its own asyncio loop. chunk → N scan-mapper agents → dedup → M scan-reducer agents → dedup
→ results.json. No tmux, no bash. CLI: python -m app.core.scan_run --dir <scan_dir>."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import pathlib
import sys
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile
    from app.services.opencode_runner import AgentRunner
    from app.services.prompt_manager import PromptManager

log = logging.getLogger("hephaestus.backend.scan_run")

# Dirs never worth scanning: VCS, our own data, dep installs, build/cache output.
# Used both to bound chunk_files() and to prune the scope picker (list_subdirs()).
SKIP_DIRS = {
    ".git", ".hephaestus", "node_modules", "dist", "build", "out",
    "__pycache__", ".venv", "venv", ".next", ".turbo", ".cache",
    "coverage", ".idea", ".vscode", ".pytest_cache", ".mypy_cache",
}


def chunk_files(repo_path: str, scope: str, n: int) -> list[list[str]]:
    """Walk scope dirs under repo_path, collect source files, split into n round-robin chunks.
    Skips VCS/build/vendor dirs. Pure stdlib, cross-platform."""
    root = pathlib.Path(repo_path)
    seg = [s for s in scope.split() if s and ".." not in s]
    files: list[str] = []
    for s in seg:
        base = root / s
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and not (set(p.parts[:-1]) & SKIP_DIRS):  # match DIR components, not filename
                files.append(str(p.relative_to(root)).replace("\\", "/"))
    files.sort()
    buckets: list[list[str]] = [[] for _ in range(max(1, n))]
    for i, f in enumerate(files):
        buckets[i % len(buckets)].append(f)
    return [c for c in buckets if c]


def list_subdirs(repo_path: str, under: str = "") -> list[dict[str, Any]]:
    """Immediate child directories of ``<repo>/<under>``, for the scope picker UI.

    Returns ``[{path, name, files, hasChildren}]`` sorted by name, where ``path`` is the
    repo-relative POSIX path (the exact token chunk_files() expects in ``scope``), ``files``
    is the recursive source-file count with vendor/build dirs pruned, and ``hasChildren``
    flags whether the dir has further (non-skipped) subdirs to expand. Skips SKIP_DIRS and
    guards against path traversal (``..`` / escaping the repo root)."""
    root = pathlib.Path(repo_path).resolve()
    target = (root / under).resolve() if under else root
    # Containment guard: target must be the root or live under it.
    if target != root and root not in target.parents:
        return []
    if not target.is_dir():
        return []

    out: list[dict[str, Any]] = []
    try:
        children = sorted(target.iterdir(), key=lambda p: p.name.casefold())
    except OSError:
        log.debug("list_subdirs: failed to enumerate %s", target, exc_info=True)
        return []
    for child in children:
        # Hide vendor/build dirs and hidden dot-dirs from the picker (rarely scan targets;
        # still reachable via the manual scope field if a user really wants one).
        if not child.is_dir() or child.name in SKIP_DIRS or child.name.startswith("."):
            continue
        files = 0
        for _dp, dirnames, filenames in os.walk(child):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]  # prune in place (mirror chunk_files)
            files += len(filenames)
        try:
            has_children = any(
                c.is_dir() and c.name not in SKIP_DIRS and not c.name.startswith(".")
                for c in child.iterdir()
            )
        except OSError:
            log.debug("has_children check failed for %s", child, exc_info=True)
            has_children = False
        out.append({
            "path": str(child.relative_to(root)).replace("\\", "/"),
            "name": child.name,
            "files": files,
            "hasChildren": has_children,
        })
    return out


def dedup_findings(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge duplicates by (normalized title, sorted normalized touches); bumps agreement_count."""
    from app.core.task_graph import _norm_touch

    seen: dict[tuple[Any, ...], dict[str, Any]] = {}
    for it in items:
        title = (it.get("title", "") or "").strip().casefold()
        if not title:  # don't collapse distinct empty-title findings into one
            title = (it.get("proposal") or it.get("rationale") or it.get("id") or "").strip().casefold()[:80]
        key = (
            title,
            tuple(sorted(_norm_touch(t) for t in (it.get("touches") or []))),
        )
        if key in seen:
            seen[key]["agreement_count"] = int(seen[key].get("agreement_count", 1) or 1) + 1
        else:
            copy = dict(it)
            copy.setdefault("agreement_count", 1)
            seen[key] = copy
    return list(seen.values())


def _agent_text(out: pathlib.Path) -> str:
    """The agent's emitted text from an output file.

    Agent CLIs (Claude `claude -p --output-format stream-json`, opencode JSONL) write a
    stream of JSON events, NOT plain text — the SCAN_FINDINGS/SCAN_PROPOSAL block lives
    inside a JSON-escaped 'result'/'text' event. Regexing the raw file therefore never
    matches (escaped quotes/newlines/brackets). Reuse the validators' multi-shape JSONL
    extractor to recover the real text; fall back to raw for a plain-text output.
    """
    from app.core.validators import _last_text_event

    text = _last_text_event(out)
    if text:
        return text
    try:
        return out.read_text(encoding="utf-8", errors="replace")
    except OSError:
        log.debug("_agent_text read failed for %s", out, exc_info=True)
        return ""


def parse_findings_block(text: str) -> list[dict[str, Any]]:
    """Parse SCAN_FINDINGS_BEGIN..END JSON array. Bad/absent → []."""
    import re

    m = re.search(r"SCAN_FINDINGS_BEGIN\s*(\[.*?\])\s*SCAN_FINDINGS_END", text, re.DOTALL)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []


def parse_proposals_block(text: str) -> list[dict[str, Any]]:
    """Parse SCAN_PROPOSAL_BEGIN..END blocks (one JSON object each) into a list."""
    import re

    out: list[dict[str, Any]] = []
    for m in re.finditer(r"SCAN_PROPOSAL_BEGIN\s*(\{.*?\})\s*SCAN_PROPOSAL_END", text, re.DOTALL):
        try:
            obj = json.loads(m.group(1))
            if isinstance(obj, dict):
                out.append(obj)
        except json.JSONDecodeError:
            continue
    return out


async def run_mappers(ws: RepoProfile, runner: AgentRunner, scan_dir: pathlib.Path,
                      chunks: list[list[str]],
                      *, prompt_mgr: PromptManager, timeout_sec: int,
                      on_done: Callable[[], None] | None = None) -> list[dict[str, Any]]:
    """N concurrent scan-mapper agents (one per chunk). on_done() fires as each finishes."""
    async def _one(i: int, chunk: list[str]) -> list[dict[str, Any]]:
        try:
            prompt = prompt_mgr.render_prompt("scan-mapper", {
                "repo_path": ws.repo_path,
                "scope": " ".join(sorted({c.split("/")[0] for c in chunk})),
                "chunk": "\n".join(chunk),
                "tech_stack": "",
                "memory_excerpt": "",
                "tech_debt_excerpt": "",
            }) or ""
            pf = scan_dir / f"scanner-{i}.prompt.md"
            pf.write_text(prompt, encoding="utf-8")
            out = scan_dir / f"scanner-{i}.findings.jsonl"
            await runner.run(getattr(ws.agents, "planner", None) or ws.agents.primary,
                             prompt_file=pf, cwd=ws.repo_path,
                             output_path=out, timeout_sec=timeout_sec)
            return parse_findings_block(_agent_text(out))
        finally:
            if on_done:
                on_done()

    results = await asyncio.gather(*[_one(i, c) for i, c in enumerate(chunks)],
                                   return_exceptions=True)
    findings: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, Exception):
            log.warning("scan mapper failed: %s", r)
            continue
        findings.extend(cast("list[dict[str, Any]]", r))
    return findings


async def run_reducers(ws: RepoProfile, runner: AgentRunner, scan_dir: pathlib.Path,
                       findings: list[dict[str, Any]],
                       *, reducers: int, prompt_mgr: PromptManager,
                       timeout_sec: int,
                       on_done: Callable[[], None] | None = None) -> list[dict[str, Any]]:
    """M concurrent scan-reducer agents over sharded findings. on_done() fires per shard."""
    shards: list[list[dict[str, Any]]] = [[] for _ in range(max(1, reducers))]
    for i, f in enumerate(findings):
        shards[i % len(shards)].append(f)

    async def _one(j: int, shard: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            prompt = prompt_mgr.render_prompt("scan-reducer", {
                "all_findings": json.dumps(shard, ensure_ascii=False, indent=2),
                "tech_debt_excerpt": "",
            }) or ""
            pf = scan_dir / f"reducer-{j}.prompt.md"
            pf.write_text(prompt, encoding="utf-8")
            out = scan_dir / f"reducer-{j}.proposals.jsonl"
            await runner.run(getattr(ws.agents, "planner", None) or ws.agents.primary,
                             prompt_file=pf, cwd=ws.repo_path,
                             output_path=out, timeout_sec=timeout_sec)
            return parse_proposals_block(_agent_text(out))
        finally:
            if on_done:
                on_done()

    results = await asyncio.gather(*[_one(j, s) for j, s in enumerate(shards) if s],
                                   return_exceptions=True)
    proposals: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, Exception):
            log.warning("scan reducer failed: %s", r)
            continue
        proposals.extend(cast("list[dict[str, Any]]", r))
    return proposals


def _resolve_ws() -> RepoProfile:
    """The workspace this scan runs against: the registry's active repo (real agents,
    engine, prompt overrides), falling back to the legacy global-config profile."""
    try:
        from app.core.workspaces import registry

        ws = registry.active()
        if ws is not None:
            return ws
    except Exception:  # noqa: BLE001 — registry optional; fall back below
        log.warning("registry.active() unavailable; using global-config profile")
    from app.core.ws_shim import get_active_profile

    return get_active_profile()


def write_status(scan_dir: pathlib.Path, **fields: Any) -> None:
    """Merge fields into scan_dir/status.json (atomic), stamping updatedAt. The dashboard
    polls this file to render live phase/progress, so each phase transition calls it."""
    from app.core.state import _atomic_write

    path = scan_dir / "status.json"
    cur: dict[str, Any] = {}
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cur = loaded
        except Exception:  # noqa: BLE001 — best-effort, overwrite on parse failure
            log.debug("write_status: failed to parse existing status.json", exc_info=True)
            cur = {}
    cur.update(fields)
    cur["updatedAt"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    _atomic_write(path, json.dumps(cur, ensure_ascii=False, indent=2))


async def _run(scan_dir: pathlib.Path) -> int:
    from app.core.process import pm
    from app.services.opencode_runner import AgentRunner
    from app.services.prompt_manager import PromptManager

    req = json.loads((scan_dir / "request.json").read_text(encoding="utf-8"))
    scanners = int(req.get("scanners", 6))
    reviewers = int(req.get("reviewers", 2))
    ws = _resolve_ws()
    runner = AgentRunner(pm, engine=getattr(ws, "engine", "opencode"),
                         env=getattr(ws, "engine_env", {}),
                         profiles=getattr(ws, "engine_profiles", []))
    prompt_mgr = PromptManager(override_dir=pathlib.Path(ws.repo_path) / ".hephaestus" / "prompts")

    try:
        log.info("scan_run start: repo=%s scope=%r scanners=%d reviewers=%d",
                 ws.repo_path, req.get("scope"), scanners, reviewers)
        write_status(scan_dir, phase="chunking", detail="collecting scope files",
                     scanners=scanners, reviewers=reviewers, scanners_done=0, reducers_done=0)
        chunks = chunk_files(ws.repo_path, req["scope"], scanners)
        if not chunks:
            log.info("scan_run: no files in scope %r", req.get("scope"))
            (scan_dir / "results.json").write_text(
                json.dumps({"proposals": [], "n_unique": 0}, ensure_ascii=False), encoding="utf-8")
            write_status(scan_dir, phase="done", detail="no files in the selected scope",
                         scanners=0, scanners_done=0, reducers_done=0, n_findings=0, n_proposals=0)
            return 0

        n_map = len(chunks)
        log.info("scan_run: mapping %d chunk(s) across scanners", n_map)
        write_status(scan_dir, phase="mapping", detail=f"0/{n_map} scanners",
                     scanners=n_map, scanners_done=0)
        mapped = {"n": 0}

        def _map_done() -> None:
            mapped["n"] += 1
            log.info("scan_run: scanner %d/%d done", mapped["n"], n_map)
            write_status(scan_dir, phase="mapping", detail=f"{mapped['n']}/{n_map} scanners",
                         scanners_done=mapped["n"])

        findings = dedup_findings(
            await run_mappers(ws, runner, scan_dir, chunks,
                              prompt_mgr=prompt_mgr, timeout_sec=900, on_done=_map_done)
        )
        log.info("scan_run: %d unique finding(s)", len(findings))
        write_status(scan_dir, phase="reducing", detail=f"0/{reviewers} reviewers",
                     n_findings=len(findings), reducers_done=0)
        reduced = {"n": 0}

        def _red_done() -> None:
            reduced["n"] += 1
            log.info("scan_run: reducer %d/%d done", reduced["n"], reviewers)
            write_status(scan_dir, phase="reducing", detail=f"{reduced['n']}/{reviewers} reviewers",
                         reducers_done=reduced["n"])

        proposals = dedup_findings(
            await run_reducers(ws, runner, scan_dir, findings, reducers=reviewers,
                               prompt_mgr=prompt_mgr, timeout_sec=900, on_done=_red_done)
        )
        (scan_dir / "results.json").write_text(
            json.dumps({"proposals": proposals, "n_unique": len(proposals)}, ensure_ascii=False),
            encoding="utf-8",
        )
        write_status(scan_dir, phase="done", detail=f"{len(proposals)} findings",
                     n_findings=len(findings), n_proposals=len(proposals))
        log.info("scan_run done: %d proposals", len(proposals))
        return 0
    except Exception as exc:  # noqa: BLE001 — surface failure into status for the UI
        log.exception("scan_run failed")
        write_status(scan_dir, phase="error", detail=str(exc)[:300], error=str(exc)[:300])
        return 1


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from app.core.state import _state_dir

    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    args = ap.parse_args()
    scan_dir = _state_dir() / "scans" / args.dir
    return asyncio.run(_run(scan_dir))


if __name__ == "__main__":
    sys.exit(main())
