"""Text normalization utilities for search indexing."""

from __future__ import annotations

import re

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
_WHITESPACE = re.compile(r"\s+")


def normalize_search_text(text: str, *, limit: int = 4096) -> str:
    """Return sanitized text suitable for Chromadb document payloads.

    Args:
        text: Source text extracted from previews or captions.
        limit: Maximum number of characters retained in the normalized output.

    Returns:
        str: Normalized text with control characters removed, whitespace collapsed,
        and length capped to ``limit`` characters when ``limit`` is positive.
    """

    sanitized = _CONTROL_CHARS.sub(" ", text)
    sanitized = _WHITESPACE.sub(" ", sanitized).strip()
    if limit > 0:
        return sanitized[:limit]
    return sanitized


__all__ = ["normalize_search_text"]
