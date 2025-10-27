"""Lifecycle helpers for managing per-collection search indexes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from dorgy.state import CollectionState, SearchState

from .index import SearchEntry, SearchIndex


def ensure_index(
    root: str | Path,
    state: CollectionState,
    *,
    embedding_function: Any | None = None,
) -> SearchIndex:
    """Ensure the Chromadb store for ``root`` exists and mark search as enabled.

    Args:
        root: Collection root path.
        state: Collection state being updated.
        embedding_function: Optional embedding factory passed to Chromadb.

    Returns:
        SearchIndex: Initialized index wrapper for the collection.
    """

    if state.search is None:
        state.search = SearchState()
    state.search.enabled = True
    index = SearchIndex(root, embedding_function=embedding_function)
    index.initialize()
    return index


def update_entries(
    index: SearchIndex,
    state: CollectionState,
    entries: Sequence[SearchEntry],
) -> None:
    """Upsert search entries and update metadata on the collection state.

    Args:
        index: Initialized search index.
        state: Collection state being updated.
        entries: Entries to add or update.
    """

    if state.search is None:
        state.search = SearchState()
    index.upsert(entries, total_documents=len(state.files))
    state.search.last_indexed_at = datetime.now(timezone.utc)
    state.search.version = 1


def drop_index(root: str | Path, state: CollectionState) -> None:
    """Remove Chromadb artifacts for ``root`` and disable search.

    Args:
        root: Collection root path.
        state: Collection state being updated.
    """

    index = SearchIndex(root)
    index.drop()
    if state.search is None:
        state.search = SearchState()
    state.search.enabled = False
    state.search.last_indexed_at = None


__all__ = ["ensure_index", "update_entries", "drop_index"]
