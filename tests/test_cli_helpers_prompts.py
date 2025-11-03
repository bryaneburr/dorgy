"""Tests for prompt resolution helpers."""

from __future__ import annotations

from pathlib import Path

from dorgy.cli.helpers.prompts import resolve_prompt_text


def test_resolve_prompt_text_prefers_file(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.txt"
    prompt_file.write_text("line a\nline b", encoding="utf-8")

    result = resolve_prompt_text("inline", str(prompt_file))

    assert result == "line a\nline b"


def test_resolve_prompt_text_inline_when_file_missing() -> None:
    assert resolve_prompt_text("inline", None) == "inline"
