"""Stage 3 — map-reduce validation funnel (D10).

Layer 1 (lenses, many) → Layer 2 (arbiters, fewer) → Layer 3 (final gate, one).
Sizes/thresholds come from TIER_PRESETS + effective config (no parallel source of
truth). Cross-platform: pathlib paths, asyncio subprocess via AgentRunner, no bash.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import re
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel

from app.models.validation import LensVerdict, ValidationResult

if TYPE_CHECKING:
    from app.models.workspace import RepoProfile

log = logging.getLogger("hephaestus.validators")

LENSES: tuple[str, ...] = ("correctness", "tests", "security", "conventions", "scope")

LENS_FOCUS: dict[str, str] = {
    "correctness": "Does the diff actually solve the item's problem? Edge cases, null/empty, error paths, races.",
    "tests": "Are tests present, do they exercise the new path, would they fail WITHOUT the production change? CRITICAL: do the tests match the ACTUAL implementation in this diff — same exported/imported names, same function signatures, same return/throw contract (resolve-vs-reject, returned fields, file/value names)? A test file that asserts a DIFFERENT design than the code it covers (wrong symbol names, a method that doesn't exist, expecting a throw where the code returns null) is BROKEN and must be needs_revision even if it looks thorough — it would fail if actually run.",  # noqa: E501
    "security": "Secret leaks, weakened auth, SSRF, swallowed exceptions hiding bugs, unsafe casts, missing input validation.",  # noqa: E501
    "conventions": "Naming, code style, project conventions from .hephaestus/memory/conventions.md, no out-of-style patterns.",  # noqa: E501
    "scope": "Does the diff stay inside item.touches? Out-of-scope refactors / 'while-I-was-here' tweaks are a needs_revision signal.",  # noqa: E501
}

# strictness → (active_lenses, arbiter_cap)
_STRICTNESS_LENSES: dict[str, tuple[list[str], int]] = {
    "strict": (list(LENSES), 2),
    "standard": (list(LENSES), 2),
    "permissive": (["correctness", "tests", "scope"], 1),
    "disabled": ([], 0),
}

_PROMPTS_DIR = pathlib.Path(__file__).resolve().parent.parent.parent.parent / "prompts"


def _effective() -> dict[str, str]:
    """Thin wrapper so tests can monkeypatch the threshold source."""
    from app.config import _config_effective

    return _config_effective()


class LensSpec(BaseModel):
    lens: str
    focus: str


class _AgentRunnerProto(Protocol):
    # R2: каждый конкурентный вызов имеет уникальный output_path; общего session_name нет.
    async def run(self, ref: object, *, prompt_file: pathlib.Path, cwd: str,
                  output_path: pathlib.Path, timeout_sec: int) -> object: ...


class ValidationFunnel:
    def __init__(self, ws: RepoProfile, runner: _AgentRunnerProto) -> None:
        self.ws = ws
        self.runner = runner

    def _layer_sizes_for(self) -> tuple[list[str], int, int, int]:
        """Return (active_lenses, m_arbiters, tier1_threshold, tier2_threshold)."""
        strictness = getattr(self.ws, "strictness", "standard")
        lenses, arb_cap = _STRICTNESS_LENSES.get(strictness, _STRICTNESS_LENSES["standard"])
        if not lenses:  # disabled
            return [], 0, 0, 0
        eff = _effective()
        t1_raw = int(eff.get("HEPHAESTUS_TIER1_APPROVE_THRESHOLD", str(len(lenses))))
        t2_raw = int(eff.get("HEPHAESTUS_TIER2_APPROVE_THRESHOLD", "2"))
        t1 = max(1, min(t1_raw, len(lenses)))
        n_arbiters = min(len(getattr(self.ws.agents, "arbiters", [])), arb_cap)
        t2 = max(0, min(t2_raw, n_arbiters)) if n_arbiters else 0
        return lenses, n_arbiters, t1, t2

    def _validator_pool(self) -> list[object]:
        """R3: validators pool, fallback to [primary] so the funnel never silently passes."""
        vals = list(getattr(self.ws.agents, "validators", []))
        if vals:
            return vals
        primary = getattr(self.ws.agents, "primary", None)
        return [primary] if primary is not None else []

    def _final_ref(self) -> object | None:
        """R3: final gate agent, fallback to primary when final is None."""
        final: object | None = getattr(self.ws.agents, "final", None)
        if final is not None:
            return final
        primary: object | None = getattr(self.ws.agents, "primary", None)
        return primary

    async def run_funnel(self, item: dict[str, object], *, iter_dir: pathlib.Path,
                         diff_text: str, revision: int) -> ValidationResult:
        """Full funnel. Writes artifacts under iter_dir/validation/. Returns ValidationResult.

        strictness=='disabled' or review.enabled is False → immediate pass, no agents (R3).
        """
        review_enabled = getattr(getattr(self.ws, "review", None), "enabled", True)
        lenses, m, t1, t2 = self._layer_sizes_for()
        if not lenses or not review_enabled:
            return ValidationResult(layer1=[], gate="pass", blocking=[], revision=revision)
        vdir = iter_dir / "validation"
        (vdir / "layer1").mkdir(parents=True, exist_ok=True)
        l1 = await self._run_layer1(item, iter_dir=iter_dir, diff_text=diff_text, lenses=lenses)
        passed, blocking = _aggregate_layer1(l1, t1)
        l2: list[dict[str, object]] = []
        l2_errored_all = False
        if m > 0:
            (vdir / "layer2").mkdir(parents=True, exist_ok=True)
            l2 = await self._run_layer2(item, iter_dir=iter_dir, l1=l1, m=m)
            # R20: if EVERY arbiter errored (launch failure, not a substantive verdict),
            # do not penalize Layer 2 — fall back to L1+L3 just like m==0.
            l2_errored_all = bool(l2) and all(bool(a.get("errored")) for a in l2)
        l3 = await self._run_layer3(item, iter_dir=iter_dir, l1=l1, l2=l2)
        layer2_active = m > 0 and not l2_errored_all
        approvals = sum(1 for a in l2 if a.get("verdict") == "approve")
        l2_pass = (not layer2_active) or approvals >= t2
        l2_blocking: list[str] = []
        if layer2_active and not l2_pass:
            l2_blocking.append(f"arbiters: {approvals} of {t2} approvals")  # R20 diagnostics
        gate_pass = passed and l2_pass
        l3_gate = l3.get("gate", "pass")
        l3_blocking_raw = l3.get("blocking", [])
        l3_blocking = [str(x) for x in l3_blocking_raw] if isinstance(l3_blocking_raw, list) else []
        # final agent gate can only downgrade to needs_revision, never upgrade
        gate = "pass" if (gate_pass and l3_gate == "pass") else "needs_revision"
        all_blocking = list(dict.fromkeys([*blocking, *l2_blocking, *l3_blocking]))
        # NB: this repo doesn't enable the pydantic mypy plugin, so the aliased field
        # must be passed by its alias name (layer2Summary). populate_by_name keeps the
        # snake_case form working at runtime too.
        result = ValidationResult(layer1=l1, layer2Summary=l2, gate=gate,
                                  blocking=all_blocking, revision=revision)
        (vdir / "layer3").mkdir(parents=True, exist_ok=True)
        final: dict[str, object] = {"gate": gate, "blocking": all_blocking,
                                    "notes": l3.get("notes", ""), "revision": revision}
        # umbrella §4.4/§7: final gate artifact lives at validation/layer3/final.json
        (vdir / "layer3" / "final.json").write_text(json.dumps(final, indent=2), encoding="utf-8")
        return result

    async def _run_layer1(self, item: dict[str, object], *, iter_dir: pathlib.Path,
                          diff_text: str, lenses: list[str]) -> list[LensVerdict]:
        vals = self._validator_pool()  # R3 fallback
        l1dir = iter_dir / "validation" / "layer1"

        async def _one(i: int, lens: str) -> LensVerdict:
            ref = vals[i % len(vals)] if vals else None
            prompt = _render_template(
                "validate-lens.md", override_dir=_ws_prompts_dir(self.ws),
                lens=lens, lens_focus=LENS_FOCUS[lens],
                item_id=str(item.get("id", "?")),
                prompt_excerpt=str(item.get("proposal", ""))[:2000], diff=diff_text[:20000],
            )
            pf = l1dir / f"{lens}.prompt.md"
            pf.write_text(prompt, encoding="utf-8")
            out = l1dir / f"{lens}.jsonl"  # R2: unique output_path per lens, no session_name
            await self.runner.run(ref, prompt_file=pf, cwd=str(self.ws.repo_path),
                                  output_path=out, timeout_sec=600)
            text = _last_text_event(out)
            v = _parse_lens_block(text, lens)
            (l1dir / f"{lens}.json").write_text(v.model_dump_json(indent=2), encoding="utf-8")
            return v

        results = await asyncio.gather(*[_one(i, ln) for i, ln in enumerate(lenses)],
                                       return_exceptions=True)
        out: list[LensVerdict] = []
        for lens, r in zip(lenses, results, strict=True):
            if isinstance(r, BaseException):
                out.append(LensVerdict(lens=lens, verdict="needs_revision", confidence=0.0,
                                       reasoning=f"validator {lens} errored: {type(r).__name__}"))
            else:
                out.append(r)
        return out

    async def _run_layer2(self, item: dict[str, object], *, iter_dir: pathlib.Path,
                          l1: list[LensVerdict], m: int) -> list[dict[str, object]]:
        arbiters = list(getattr(self.ws.agents, "arbiters", []))[:m]
        l2dir = iter_dir / "validation" / "layer2"
        digest = json.dumps([v.model_dump() for v in l1])

        async def _one(i: int, ref: object) -> dict[str, object]:
            prompt = _render_template("validate-arbiter.md",
                                      override_dir=_ws_prompts_dir(self.ws), layer1_digest=digest)
            pf = l2dir / f"arbiter-{i}.prompt.md"
            pf.write_text(prompt, encoding="utf-8")
            out = l2dir / f"arbiter-{i}.jsonl"  # R2: unique output_path per arbiter, no session_name
            await self.runner.run(ref, prompt_file=pf, cwd=str(self.ws.repo_path),
                                  output_path=out, timeout_sec=600)
            text = _last_text_event(out)
            verdict = _parse_arbiter_block(text)
            rec: dict[str, object] = {"arbiter": i, "verdict": verdict, "errored": False}
            # umbrella §4.4: arbiter artifact is validation/layer2/arbiter-<i>.json
            (l2dir / f"arbiter-{i}.json").write_text(json.dumps(rec, indent=2), encoding="utf-8")
            return rec

        results = await asyncio.gather(*[_one(i, a) for i, a in enumerate(arbiters)],
                                       return_exceptions=True)
        # R20: mark errored arbiters explicitly so run_funnel can avoid penalizing L2
        out: list[dict[str, object]] = []
        for i, r in enumerate(results):
            if isinstance(r, BaseException):
                out.append({"arbiter": i, "verdict": "needs_revision", "errored": True})
            else:
                out.append(r)
        return out

    async def _run_layer3(self, item: dict[str, object], *, iter_dir: pathlib.Path,
                          l1: list[LensVerdict], l2: list[dict[str, object]]) -> dict[str, object]:
        final_ref = self._final_ref()  # R3: fallback to primary when final is None
        if final_ref is None:
            return {"gate": "pass", "blocking": [], "notes": "no final agent configured"}
        l3dir = iter_dir / "validation" / "layer3"
        l3dir.mkdir(parents=True, exist_ok=True)
        prompt = _render_template(
            "validate-final.md", override_dir=_ws_prompts_dir(self.ws),
            layer1_digest=json.dumps([v.model_dump() for v in l1]),
            layer2_digest=json.dumps(l2),
        )
        pf = l3dir / "final.prompt.md"
        pf.write_text(prompt, encoding="utf-8")
        out = l3dir / "final.jsonl"  # R2: unique output_path, no session_name
        try:
            await self.runner.run(final_ref, prompt_file=pf, cwd=str(self.ws.repo_path),
                                  output_path=out, timeout_sec=600)
        except Exception as exc:  # fail-safe to needs_revision
            return {"gate": "needs_revision",
                    "blocking": [f"final gate errored: {type(exc).__name__}"], "notes": ""}
        return _parse_final_block(_last_text_event(out))


_VERDICT_VALUES = {"approve", "needs_revision", "reject"}
_LENS_BLOCK_RE = re.compile(r"VALIDATION_VERDICT_BEGIN(.*?)VALIDATION_VERDICT_END", re.DOTALL)


def _parse_kv(block: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip().lower()] = v.strip()
    return out


def _norm_confidence(raw: str) -> float:
    try:
        val = float(raw)
    except (ValueError, TypeError):
        return 0.0
    if val > 1.0:  # 0..10 form
        val = val / 10.0
    return max(0.0, min(1.0, val))


def _parse_lens_block(text: str, lens: str) -> LensVerdict:
    """Defensive: take the LAST verdict block; missing → needs_revision/0.0."""
    matches = _LENS_BLOCK_RE.findall(text or "")
    if not matches:
        return LensVerdict(lens=lens, verdict="needs_revision", confidence=0.0,
                           reasoning="no verdict block emitted")
    kv = _parse_kv(matches[-1])
    verdict = kv.get("verdict", "").lower()
    if verdict not in _VERDICT_VALUES:
        verdict = "needs_revision"
    return LensVerdict(
        lens=kv.get("lens", lens) or lens,
        verdict=verdict,
        confidence=_norm_confidence(kv.get("confidence", "0")),
        reasoning=kv.get("reasoning", "") or "(no reasoning)",
    )


def _aggregate_layer1(verdicts: list[LensVerdict], threshold: int) -> tuple[bool, list[str]]:
    """passed = approve_count >= clamp(threshold,1,len). Any reject@conf>=0.7 → False."""
    if not verdicts:
        return False, ["all validators failed — check opencode availability"]
    approve_count = sum(1 for v in verdicts if v.verdict == "approve")
    clamped = max(1, min(threshold, len(verdicts)))
    passed = approve_count >= clamped
    if any(v.verdict == "reject" and v.confidence >= 0.7 for v in verdicts):
        passed = False
    blocking = [f"{v.lens}: {v.reasoning}" for v in verdicts if v.verdict != "approve"]
    return passed, blocking


def _ws_prompts_dir(ws: object) -> pathlib.Path | None:
    """Per-workspace prompt override dir (<repo>/.hephaestus/prompts), if the ws has a repo."""
    repo = getattr(ws, "repo_path", None)
    if not repo:
        return None
    return pathlib.Path(str(repo)) / ".hephaestus" / "prompts"


def _render_template(name: str, *, override_dir: pathlib.Path | None = None,
                     **variables: str) -> str:
    path = _PROMPTS_DIR / name
    if override_dir is not None:
        cand = override_dir / name
        if cand.exists():
            path = cand
    tpl = path.read_text(encoding="utf-8", errors="replace")
    for k, v in variables.items():
        tpl = tpl.replace("{{" + k + "}}", v)
    return tpl


def build_revision_prompt(item: dict[str, object], vr: ValidationResult, attempt: int,
                          ws: RepoProfile) -> str:
    """Render prompts/revision-feedback.md with blocking + non-approve lens findings."""
    max_rev = getattr(getattr(ws, "review", None), "max_revisions", 2)
    lens_findings = "\n".join(
        f"- {v.lens}: {v.reasoning}" for v in vr.layer1 if v.verdict != "approve"
    ) or "- (none)"
    blocking = "\n".join(f"- {b}" for b in vr.blocking) or "- (none)"
    return _render_template(
        "revision-feedback.md", override_dir=_ws_prompts_dir(ws),
        item_id=str(item.get("id", "?")),
        attempt=str(attempt),
        max_revisions=str(max_rev),
        blocking=blocking,
        lens_findings=lens_findings,
        proposal=str(item.get("proposal", "")),
        acceptance=str(item.get("acceptance", "")),
    )


_ARBITER_BLOCK_RE = re.compile(r"ARBITER_VERDICT_BEGIN(.*?)ARBITER_VERDICT_END", re.DOTALL)
_FINAL_BLOCK_RE = re.compile(r"FINAL_GATE_BEGIN(.*?)FINAL_GATE_END", re.DOTALL)


def _parse_arbiter_block(text: str) -> str:
    matches = _ARBITER_BLOCK_RE.findall(text or "")
    if not matches:
        return "needs_revision"
    verdict = _parse_kv(matches[-1]).get("verdict", "").lower()
    return verdict if verdict in _VERDICT_VALUES else "needs_revision"


def _parse_final_block(text: str) -> dict[str, object]:
    matches = _FINAL_BLOCK_RE.findall(text or "")
    if not matches:
        return {"gate": "needs_revision", "blocking": ["no final gate block emitted"], "notes": ""}
    kv = _parse_kv(matches[-1])
    gate = kv.get("gate", "needs_revision").lower()
    if gate != "pass":
        gate = "needs_revision"
    raw_blocking = kv.get("blocking", "none")
    blocking = [] if raw_blocking.lower() == "none" else [
        b.strip() for b in raw_blocking.split(";") if b.strip()]
    return {"gate": gate, "blocking": blocking, "notes": kv.get("notes", "")}


def _last_text_event(output_path: pathlib.Path) -> str:
    """Assemble the FULL text from an opencode JSONL stream.

    IMPORTANT: do NOT use app.core.events._parse_events — it truncates each event's
    text to EVENT_TEXT_MAX (=240) chars for the UI timeline, which would clip the
    VALIDATION_VERDICT / ARBITER / FINAL_GATE blocks so the regex parsers never find
    their closing marker. Read the raw JSONL and concatenate the text whole.
    """
    if not output_path.exists():
        return ""
    try:
        raw = output_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    texts: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(ev, dict):
            continue
        # Multi-shape JSONL (opencode + Claude CLI stream-json): text | content |
        # output | result | message.content[].text | part.text
        val = ev.get("text") or ev.get("content") or ev.get("output") or ev.get("result")
        if isinstance(val, str) and val:
            texts.append(val)
        msg = ev.get("message")
        if isinstance(msg, dict):
            mc = msg.get("content")
            if isinstance(mc, str) and mc:
                texts.append(mc)
            elif isinstance(mc, list):
                for part in mc:
                    if isinstance(part, dict) and isinstance(part.get("text"), str):
                        texts.append(part["text"])
        part = ev.get("part")
        if isinstance(part, dict) and isinstance(part.get("text"), str):
            texts.append(part["text"])
    return "\n".join(t for t in texts if t)
