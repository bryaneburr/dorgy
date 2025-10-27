"""Search indexing helpers for Dorgy."""

from .index import SearchEntry, SearchIndex, SearchIndexError
from .lifecycle import drop_index, ensure_index, update_entries
from .text import descriptor_document_text, normalize_search_text

__all__ = [
    "SearchEntry",
    "SearchIndex",
    "SearchIndexError",
    "normalize_search_text",
    "descriptor_document_text",
    "ensure_index",
    "update_entries",
    "drop_index",
]
