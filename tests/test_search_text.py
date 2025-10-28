"""Tests for search text normalization."""

from __future__ import annotations

from dorgy.search import normalize_search_text


def test_normalize_search_text_collapses_whitespace() -> None:
    """Whitespace and control characters should be normalized."""

    raw = "Hello\x00  world\t\r\nThis is a test"
    normalized = normalize_search_text(raw)
    assert normalized == "Hello world This is a test"


def test_normalize_search_text_limit() -> None:
    """The helper should truncate when the limit is positive."""

    text = "abcdef"
    assert normalize_search_text(text, limit=3) == "abc"
    assert normalize_search_text(text, limit=0) == "abcdef"
