"""Chromadb-backed search index helpers."""

from __future__ import annotations

import json
import shutil
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from dorgy.state import DEFAULT_STATE_DIRNAME, FileRecord

from .text import normalize_search_text

CHROMA_DIRNAME = "chroma"
MANIFEST_FILENAME = "search.json"
DEFAULT_COLLECTION_NAME = "dorgy-documents"


def _build_metadata(
    record: FileRecord,
    extra_metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "path": record.path,
        "tags": ", ".join(record.tags),
        "categories": ", ".join(record.categories),
        "needs_review": record.needs_review,
        "hash": record.hash,
        "last_modified": record.last_modified.isoformat() if record.last_modified else None,
        "confidence": record.confidence,
    }
    if extra_metadata:
        metadata.update(extra_metadata)
    return metadata


class SearchIndexError(RuntimeError):
    """Raised when the search index cannot be created or accessed."""


@dataclass(slots=True)
class SearchEntry:
    """Payload describing a document destined for the search index.

    Attributes:
        document_id: Stable identifier used for Chromadb storage.
        document: Normalized textual content for the document.
        metadata: Metadata dictionary persisted alongside the entry.
    """

    document_id: str
    document: str
    metadata: dict[str, Any]

    @classmethod
    def from_record(
        cls,
        record: FileRecord,
        document: str,
        *,
        limit: int = 4096,
        extra_metadata: Mapping[str, Any] | None = None,
    ) -> "SearchEntry":
        """Build a search entry using a ``FileRecord`` as the metadata source."""

        normalized_document = normalize_search_text(document, limit=limit)
        metadata = _build_metadata(record, extra_metadata)
        return cls(document_id=record.document_id, document=normalized_document, metadata=metadata)


class SearchIndex:
    """Manage a per-collection Chromadb index rooted under `.dorgy` directories."""

    def __init__(
        self,
        collection_root: str | Path,
        *,
        embedding_function: Any | None = None,
        client_factory: Callable[[str], Any] | None = None,
        state_dirname: str = DEFAULT_STATE_DIRNAME,
        collection_name: str = DEFAULT_COLLECTION_NAME,
    ) -> None:
        """Initialize the search index wrapper.

        Args:
            collection_root: Path to the organized collection root.
            embedding_function: Optional Chromadb embedding function override.
            client_factory: Optional factory used for testing/mocking Chromadb clients.
            state_dirname: Directory containing collection metadata (default: `.dorgy`).
            collection_name: Name of the Chromadb collection to manage.
        """

        self._root = Path(collection_root)
        self._embedding_function = embedding_function
        self._client_factory = client_factory
        self._state_dirname = state_dirname
        self._collection_name = collection_name
        self._index_dir = self._root / self._state_dirname / CHROMA_DIRNAME
        self._manifest_path = self._root / self._state_dirname / MANIFEST_FILENAME
        self._lock = threading.RLock()
        self._client: Any | None = None
        self._collection: Any | None = None
        self._manifest_version = 1

    @property
    def index_path(self) -> Path:
        """Return the filesystem path backing the Chromadb index."""

        return self._index_dir

    def status(self) -> dict[str, Any]:
        """Return diagnostic information about the managed search store."""

        manifest = self._load_manifest()
        return {
            "path": str(self._index_dir),
            "manifest": str(self._manifest_path),
            "enabled": self._index_dir.exists(),
            "version": manifest.get("version", self._manifest_version),
            "documents": manifest.get("documents", 0),
            "updated_at": manifest.get("updated_at"),
        }

    def initialize(self) -> None:
        """Create backing directories and manifest when missing."""

        with self._lock:
            self._ensure_index_dir()
            if not self._manifest_path.exists():
                manifest = {
                    "version": self._manifest_version,
                    "documents": 0,
                    "updated_at": None,
                }
                self._save_manifest(manifest)

    def upsert(
        self,
        entries: Sequence[SearchEntry],
        *,
        total_documents: int | None = None,
    ) -> None:
        """Insert or update documents inside the Chromadb collection.

        Args:
            entries: Iterable of search entries to persist.
            total_documents: Optional collection-wide document count to record in
                the manifest after the upsert concludes.
        """

        batch = list(entries)
        if not batch:
            return

        collection = self._collection_handle()
        ids = [entry.document_id for entry in batch]
        documents = [entry.document for entry in batch]
        metadatas = [entry.metadata for entry in batch]

        with self._lock:
            collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
            self._write_manifest_on_upsert(
                ids=ids,
                total_documents=total_documents,
            )

    def update_metadata(
        self,
        records: Sequence[tuple[FileRecord, Mapping[str, Any] | None]],
    ) -> None:
        """Update metadata for existing search entries without touching documents.

        Args:
            records: Sequence of (FileRecord, extra_metadata) tuples to refresh.
        """

        if not records:
            return
        collection = self._collection_handle()
        ids: list[str] = []
        metadatas: list[dict[str, Any]] = []
        for record, extra in records:
            ids.append(record.document_id)
            metadatas.append(_build_metadata(record, extra))
        with self._lock:
            collection.update(ids=ids, metadatas=metadatas)
            manifest = self._load_manifest()
            manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_manifest(manifest)

    def delete(
        self,
        document_ids: Sequence[str],
        *,
        total_documents: int | None = None,
    ) -> None:
        """Delete documents from Chromadb by ID.

        Args:
            document_ids: Identifiers to remove.
            total_documents: Optional new document count to persist after deletion.
        """

        unique_ids = list(dict.fromkeys(document_ids))
        if not unique_ids:
            return

        collection = self._collection_handle()
        with self._lock:
            collection.delete(ids=unique_ids)
            manifest = self._load_manifest()
            if total_documents is not None:
                manifest["documents"] = max(0, total_documents)
            else:
                manifest["documents"] = max(0, manifest.get("documents", 0) - len(unique_ids))
            manifest["version"] = self._manifest_version
            manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._save_manifest(manifest)

    def drop(self) -> None:
        """Remove Chromadb artifacts and the manifest."""

        with self._lock:
            self._collection = None
            self._client = None
            if self._index_dir.exists():
                shutil.rmtree(self._index_dir, ignore_errors=True)
            if self._manifest_path.exists():
                self._manifest_path.unlink()

    def _collection_handle(self) -> Any:
        """Return the Chromadb collection, creating it if necessary."""

        if self._collection is not None:
            return self._collection

        with self._lock:
            if self._collection is not None:
                return self._collection
            self._ensure_index_dir()
            if self._client_factory is not None:
                client = self._client_factory(str(self._index_dir))
            else:
                client = self._create_client()
            self._client = client
            kwargs: dict[str, Any] = {"name": self._collection_name}
            if self._embedding_function is not None:
                kwargs["embedding_function"] = self._embedding_function
            self._collection = client.get_or_create_collection(**kwargs)
            return self._collection

    def _create_client(self) -> Any:
        """Instantiate a Chromadb PersistentClient."""

        try:
            import chromadb  # type: ignore
        except ImportError as exc:
            raise SearchIndexError(
                "Chromadb is required for search indexing. "
                "Install optional dependencies via `uv sync`."
            ) from exc
        self._ensure_index_dir()
        return chromadb.PersistentClient(path=str(self._index_dir))

    def _ensure_index_dir(self) -> None:
        """Ensure the Chromadb directory exists."""

        self._index_dir.mkdir(parents=True, exist_ok=True)

    def _write_manifest_on_upsert(
        self,
        *,
        ids: Sequence[str],
        total_documents: int | None,
    ) -> None:
        """Update the manifest to reflect an upsert operation."""

        manifest = self._load_manifest()
        manifest["version"] = self._manifest_version
        if total_documents is not None:
            manifest["documents"] = total_documents
        else:
            manifest["documents"] = max(manifest.get("documents", 0), len(set(ids)))
        manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
        self._save_manifest(manifest)

    def _load_manifest(self) -> dict[str, Any]:
        """Return the manifest payload, falling back to defaults when absent."""

        if not self._manifest_path.exists():
            return {
                "version": self._manifest_version,
                "documents": 0,
                "updated_at": None,
            }
        try:
            data = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {
                "version": self._manifest_version,
                "documents": 0,
                "updated_at": None,
            }
        data.setdefault("version", self._manifest_version)
        data.setdefault("documents", 0)
        data.setdefault("updated_at", None)
        return data

    def _save_manifest(self, manifest: Mapping[str, Any]) -> None:
        """Persist the manifest to disk."""

        self._manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self._manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=False),
            encoding="utf-8",
        )


__all__ = ["SearchEntry", "SearchIndex", "SearchIndexError"]
