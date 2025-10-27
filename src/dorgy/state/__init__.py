"""State persistence helpers for the Dorgy CLI."""

from __future__ import annotations

import json
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from .errors import MissingStateError, StateError
from .models import CollectionState, FileRecord, OperationEvent, SearchState

DEFAULT_STATE_DIRNAME = ".dorgy"


class StateRepository:
    """Manage the persistence of collection metadata."""

    def __init__(self, base_dirname: str = DEFAULT_STATE_DIRNAME) -> None:
        """Initialize the repository with an optional base directory name.

        Args:
            base_dirname: Name of the directory that stores collection state.
        """
        self._base_dirname = base_dirname

    @property
    def base_dirname(self) -> str:
        """Return the directory name used for collection metadata.

        Returns:
            str: Name of the directory that stores state artifacts.
        """
        return self._base_dirname

    def load(self, root: Path) -> CollectionState:
        """Load collection state for the given root.

        Args:
            root: Root path of the collection.

        Returns:
            CollectionState: Deserialized state model for the collection.

        Raises:
            MissingStateError: If no state file is present.
            StateError: If stored data cannot be parsed.
        """
        directory = self._state_dir(root)
        state_path = directory / "state.json"
        if not state_path.exists():
            raise MissingStateError(f"No collection state found at {state_path}")

        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StateError(f"Invalid collection state data: {exc}") from exc

        state = CollectionState.model_validate(data)
        mutated = self._normalize_state(state)
        if mutated:
            self._persist_state(root, state, ensure_dirs=False, touch_updated=False)
        return state

    def save(self, root: Path, state: CollectionState) -> None:
        """Persist collection state for the given root.

        Args:
            root: Root path of the collection.
            state: State model to serialize to disk.
        """
        self._normalize_state(state)
        self._persist_state(root, state, ensure_dirs=True, touch_updated=True)

    def append_history(self, root: Path, events: Iterable[OperationEvent]) -> None:
        """Append operation history events to the collection log.

        Args:
            root: Root path of the collection.
            events: Iterable of events to append.
        """
        events = list(events)
        if not events:
            return

        directory = self.initialize(root)
        history_path = directory / "history.jsonl"
        with history_path.open("a", encoding="utf-8") as history_file:
            for event in events:
                payload = event.model_dump(mode="json")
                history_file.write(json.dumps(payload))
                history_file.write("\n")

    def read_history(self, root: Path, limit: int = 10) -> list[OperationEvent]:
        """Return the most recent operation history entries for the collection.

        Args:
            root: Root path of the collection.
            limit: Maximum number of events to return (most recent first).

        Returns:
            list[OperationEvent]: Parsed operation events in reverse chronological order.
        """

        if limit <= 0:
            return []

        history_path = self._state_dir(root) / "history.jsonl"
        if not history_path.exists():
            return []

        buffer: deque[str] = deque(maxlen=limit)
        with history_path.open("r", encoding="utf-8") as history_file:
            for line in history_file:
                line = line.strip()
                if not line:
                    continue
                buffer.append(line)

        events: list[OperationEvent] = []
        for raw in reversed(buffer):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise StateError(f"Invalid history entry: {exc}") from exc
            events.append(OperationEvent.model_validate(payload))
        return events

    def initialize(self, root: Path) -> Path:
        """Prepare the metadata directories for a tracked collection.

        Args:
            root: Root path of the collection.

        Returns:
            Path: Directory containing the state artifacts.
        """
        directory = self._state_dir(root)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "needs-review").mkdir(exist_ok=True)
        (directory / "quarantine").mkdir(exist_ok=True)
        (directory / "orig.json").touch(exist_ok=True)
        (directory / "history.jsonl").touch(exist_ok=True)
        return directory

    def write_original_structure(self, root: Path, tree: dict[str, Any]) -> None:
        """Persist the original structure snapshot for undo operations.

        Args:
            root: Root path of the collection.
            tree: Representation of the original directory structure.
        """
        directory = self.initialize(root)
        (directory / "orig.json").write_text(json.dumps(tree, indent=2), encoding="utf-8")

    def load_original_structure(self, root: Path) -> dict[str, Any] | None:
        """Load the original structure snapshot if present.

        Args:
            root: Root path of the collection.

        Returns:
            dict[str, Any] | None: Original structure mapping if available.

        Raises:
            StateError: If the stored structure cannot be parsed.
        """
        path = self._state_dir(root) / "orig.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StateError(f"Invalid orig.json data: {exc}") from exc

    def _state_dir(self, root: Path) -> Path:
        """Return the path to the state directory for a collection.

        Args:
            root: Root path of the collection.

        Returns:
            Path: State directory for the collection.
        """
        return root / self._base_dirname

    def _persist_state(
        self,
        root: Path,
        state: CollectionState,
        *,
        ensure_dirs: bool,
        touch_updated: bool,
    ) -> None:
        """Write the state JSON payload to disk.

        Args:
            root: Collection root path.
            state: State model to serialize.
            ensure_dirs: Whether supporting directories should be created.
            touch_updated: Whether to bump ``updated_at`` to now.
        """

        directory = self.initialize(root) if ensure_dirs else self._state_dir(root)
        if touch_updated:
            updated_at = datetime.now(timezone.utc)
        else:
            normalized_updated = _ensure_timezone(state.updated_at)
            if normalized_updated is None:
                normalized_updated = datetime.now(timezone.utc)
            updated_at = normalized_updated
        state.updated_at = updated_at

        normalized_created = _ensure_timezone(state.created_at)
        if normalized_created is None:
            normalized_created = updated_at
        state.created_at = normalized_created
        payload = state.model_dump(mode="json")
        (directory / "state.json").write_text(
            json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8"
        )
        (directory / "dorgy.log").touch(exist_ok=True)

    def _normalize_state(self, state: CollectionState) -> bool:
        """Normalize timestamps, search metadata, and document IDs.

        Args:
            state: Collection state loaded from disk.

        Returns:
            bool: ``True`` when mutations were applied.
        """

        mutated = False
        normalized_created = _ensure_timezone(state.created_at) or state.created_at
        if normalized_created is not state.created_at:
            state.created_at = normalized_created
            mutated = True
        normalized_updated = _ensure_timezone(state.updated_at) or state.updated_at
        if normalized_updated is not state.updated_at:
            state.updated_at = normalized_updated
            mutated = True

        if state.search is None:
            state.search = SearchState()
            mutated = True
        else:
            normalized_indexed = _ensure_timezone(state.search.last_indexed_at)
            if normalized_indexed is not state.search.last_indexed_at:
                state.search.last_indexed_at = normalized_indexed
                mutated = True

        for record in state.files.values():
            if not getattr(record, "document_id", None):
                record.document_id = uuid4().hex
                mutated = True
            normalized_last_modified = _ensure_timezone(record.last_modified)
            if normalized_last_modified is not record.last_modified:
                record.last_modified = normalized_last_modified
                mutated = True

        return mutated


def _ensure_timezone(value: datetime | None) -> datetime | None:
    """Return a timezone-aware variant of ``value`` when available."""

    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


__all__ = [
    "StateRepository",
    "DEFAULT_STATE_DIRNAME",
    "CollectionState",
    "FileRecord",
    "SearchState",
    "OperationEvent",
    "StateError",
    "MissingStateError",
]
