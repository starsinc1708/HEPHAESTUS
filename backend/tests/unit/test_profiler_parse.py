"""Unit: Profiler extracts last JSON block; tolerates non-JSON."""
from __future__ import annotations


def test_extract_last_json_block() -> None:
    from app.services.profiler import Profiler

    out = (
        'prose...\n{"tech_stack":["python"],"verify_commands":["uv run pytest"],'
        '"architecture_md":"A","conventions_md":"C","tech_debt_md":"D","base_branch":"main"}'
    )
    parsed = Profiler._parse_output(out)
    assert parsed.tech_stack == ["python"]
    assert parsed.verify_commands == ["uv run pytest"]
    assert parsed.base_branch == "main"


def test_parse_non_json_returns_blank() -> None:
    from app.services.profiler import Profiler

    parsed = Profiler._parse_output("the agent refused and wrote prose only")
    assert parsed.verify_commands == []
    assert parsed.tech_stack == []
