"""Scan findings/proposals must be extracted from stream-json output, not the raw file.

Claude CLI (`claude -p --output-format stream-json`) and opencode write JSON *events*;
the SCAN_FINDINGS/SCAN_PROPOSAL block lives inside a JSON-escaped 'result'/'text' event.
Regexing the raw file matches nothing (escaped quotes/brackets/newlines) — the regression
that made a real 7-scanner run report 0 findings.
"""
from __future__ import annotations

import json
import pathlib

from app.core.scan_run import _agent_text, parse_findings_block, parse_proposals_block


def _findings_block() -> str:
    arr = [{"title": "Bug A", "category": "bug", "severity": "high",
            "touches": ["a.py:1"], "proposal": "fix a"}]
    return "Here is my analysis.\nSCAN_FINDINGS_BEGIN\n" + json.dumps(arr, indent=2) + "\nSCAN_FINDINGS_END\n"


def test_findings_extracted_from_claude_stream_json(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "scanner-0.findings.jsonl"
    # Mimic Claude stream-json: noise events + a final 'result' event carrying the block.
    lines = [
        {"type": "system", "subtype": "init"},
        {"type": "assistant", "message": {"content": [{"text": "thinking…"}]}},
        {"type": "result", "result": _findings_block()},
    ]
    out.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")

    # Raw-file parse (the old bug) finds nothing; via _agent_text it works.
    assert parse_findings_block(out.read_text(encoding="utf-8")) == []
    findings = parse_findings_block(_agent_text(out))
    assert [f["title"] for f in findings] == ["Bug A"]
    assert findings[0]["touches"] == ["a.py:1"]


def test_proposals_extracted_from_opencode_jsonl(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "reducer-0.proposals.jsonl"
    block = ("SCAN_PROPOSAL_BEGIN\n"
             + json.dumps({"id": "p1", "title": "P", "proposal": "do p"}) + "\nSCAN_PROPOSAL_END\n")
    out.write_text(json.dumps({"type": "text", "text": block}), encoding="utf-8")
    proposals = parse_proposals_block(_agent_text(out))
    assert [p["id"] for p in proposals] == ["p1"]


def test_agent_text_falls_back_to_plain_text(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "plain.txt"
    out.write_text("SCAN_FINDINGS_BEGIN\n[]\nSCAN_FINDINGS_END", encoding="utf-8")
    # Not JSONL -> _last_text_event yields "" -> fall back to raw file text.
    assert "SCAN_FINDINGS_BEGIN" in _agent_text(out)
