"""scan-*.md must not contain HEPHAESTUS-as-target hardcodes (D7, spec §9.6)."""
from __future__ import annotations

import pathlib

import pytest

_PROMPTS = pathlib.Path(__file__).resolve().parents[3] / "prompts"
_FORBIDDEN = ["/home/starsinc", "pnpm", "Prisma", "zod", "otplib", "@hephaestus/server", "hephaestus-platform-snapshot"]


@pytest.mark.parametrize("name", ["scan-mapper", "scan-reducer"])
def test_scan_prompt_generic(name: str) -> None:
    text = (_PROMPTS / f"{name}.md").read_text(encoding="utf-8")
    for token in _FORBIDDEN:
        assert token not in text, f"{name}.md still contains '{token}'"


def test_scan_mapper_templated() -> None:
    text = (_PROMPTS / "scan-mapper.md").read_text(encoding="utf-8")
    for var in (
        "{{repo_path}}", "{{scope}}", "{{chunk}}",
        "{{tech_stack}}", "{{memory_excerpt}}", "{{tech_debt_excerpt}}",
    ):
        assert var in text
