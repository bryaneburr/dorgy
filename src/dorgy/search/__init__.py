"""Search indexing helpers for Dorgy."""

from .index import SearchEntry, SearchIndex, SearchIndexError
from .text import normalize_search_text

__all__ = [
    "SearchEntry",
    "SearchIndex",
    "SearchIndexError",
    "normalize_search_text",
]
