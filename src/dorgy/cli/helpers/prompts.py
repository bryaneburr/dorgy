"""Prompt loading helpers used by CLI commands."""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def resolve_prompt_text(prompt: Optional[str], prompt_file: Optional[str]) -> Optional[str]:
    """Return the prompt text, preferring file contents when provided."""

    if not prompt_file:
        return prompt
    path = Path(prompt_file).expanduser()
    return path.read_text(encoding="utf-8")


__all__ = ["resolve_prompt_text"]
