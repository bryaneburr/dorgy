"""Search index tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

from dorgy.search import SearchEntry, SearchIndex
from dorgy.state import FileRecord


def _client_factory(collection: MagicMock) -> Callable[[str], MagicMock]:
    """Return a factory that always yields ``collection``."""

    def _factory(_: str) -> MagicMock:
        return collection

    return _factory


def test_search_entry_from_record_normalizes_text() -> None:
    """SearchEntry.from_record should normalize text and metadata."""

    record = FileRecord(
        path="docs/note.txt",
        tags=["a"],
        categories=["b"],
        needs_review=True,
        last_modified=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
    )

    entry = SearchEntry.from_record(record, "Hello\x00   world\n\n")

    assert entry.document == "Hello world"
    assert entry.document_id == record.document_id
    assert entry.metadata["needs_review"] is True
    assert entry.metadata["last_modified"] == "2024-01-01T12:00:00+00:00"


def test_search_index_upsert_and_delete(tmp_path: Path) -> None:
    """SearchIndex should call Chromadb clients and persist manifests."""

    collection = MagicMock()
    client = MagicMock()
    client.get_or_create_collection.return_value = collection

    factory = _client_factory(client)
    index = SearchIndex(tmp_path, client_factory=factory)

    record = FileRecord(path="docs/a.txt")
    entry = SearchEntry.from_record(record, "Sample document")

    index.upsert([entry], total_documents=1)

    collection.upsert.assert_called_once()
    manifest_path = tmp_path / ".dorgy" / "search.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["documents"] == 1

    index.delete([record.document_id])
    manifest_after = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest_after["documents"] == 0
    collection.delete.assert_called_once_with(ids=[record.document_id])


def test_search_index_drop_removes_artifacts(tmp_path: Path) -> None:
    """drop should remove Chromadb directories and manifest files."""

    collection = MagicMock()
    client = MagicMock()
    client.get_or_create_collection.return_value = collection
    index = SearchIndex(tmp_path, client_factory=_client_factory(client))

    entry = SearchEntry(document_id="id1", document="text", metadata={"path": "a"})
    index.upsert([entry])

    chroma_dir = tmp_path / ".dorgy" / "chroma"
    manifest_path = tmp_path / ".dorgy" / "search.json"
    assert chroma_dir.exists()
    assert manifest_path.exists()

    index.drop()

    assert not chroma_dir.exists()
    assert not manifest_path.exists()


def test_search_index_status_defaults(tmp_path: Path) -> None:
    """Status should return defaults when no artifacts exist."""

    index = SearchIndex(tmp_path, client_factory=_client_factory(MagicMock()))

    status = index.status()

    assert status["enabled"] is False
    assert status["documents"] == 0
    assert status["version"] == 1
