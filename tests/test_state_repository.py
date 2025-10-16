"""State repository tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dorgy.state import (
    DEFAULT_STATE_DIRNAME,
    CollectionState,
    MissingStateError,
    OperationEvent,
    StateError,
    StateRepository,
)
from dorgy.state.models import FileRecord


def _state(tmp_path: Path) -> CollectionState:
    """Return a sample collection state configured for tests.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        CollectionState: Sample collection populated with one file record.
    """
    file = FileRecord(path="docs/file.pdf", tags=["tag"], categories=["Finance"], confidence=0.9)
    return CollectionState(root=str(tmp_path), files={file.path: file})


def test_initialize_creates_expected_structure(tmp_path: Path) -> None:
    """Ensure initialize prepares the collection directory structure.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    repo = StateRepository()

    directory = repo.initialize(tmp_path)

    assert directory == tmp_path / DEFAULT_STATE_DIRNAME
    assert (directory / "needs-review").is_dir()
    assert (directory / "quarantine").is_dir()
    assert (directory / "orig.json").exists()
    assert (directory / "history.jsonl").exists()


def test_save_and_load_round_trip(tmp_path: Path) -> None:
    """Ensure save followed by load returns the same collection state.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    repo = StateRepository()
    state = _state(tmp_path)

    repo.save(tmp_path, state)
    loaded = repo.load(tmp_path)

    assert loaded.root == state.root
    assert loaded.files.keys() == state.files.keys()
    assert loaded.updated_at >= loaded.created_at


def test_load_missing_state_raises(tmp_path: Path) -> None:
    """Verify loading without state raises MissingStateError.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    repo = StateRepository()

    with pytest.raises(MissingStateError):
        repo.load(tmp_path)


def test_load_invalid_state_raises(tmp_path: Path) -> None:
    """Ensure invalid JSON payload raises StateError on load.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    repo = StateRepository()
    directory = repo.initialize(tmp_path)
    (directory / "state.json").write_text("not json", encoding="utf-8")

    with pytest.raises(StateError):
        repo.load(tmp_path)


def test_original_structure_helpers(tmp_path: Path) -> None:
    """Confirm original structure helpers persist and recover snapshots.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    repo = StateRepository()
    tree = {"docs": ["file.pdf"]}

    repo.write_original_structure(tmp_path, tree)
    loaded = repo.load_original_structure(tmp_path)

    assert loaded == tree


def test_append_history_persists_events(tmp_path: Path) -> None:
    """Ensure operation history events are appended to the history log."""

    repo = StateRepository()
    event = OperationEvent(
        timestamp=datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc),
        operation="rename",
        source="old.txt",
        destination="new.txt",
        conflict_strategy="append_number",
        conflict_applied=True,
        notes=["rename applied"],
    )

    repo.append_history(tmp_path, [event])

    history_path = tmp_path / DEFAULT_STATE_DIRNAME / "history.jsonl"
    assert history_path.exists()
    lines = history_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["operation"] == "rename"
    assert payload["conflict_applied"] is True
    assert payload["destination"] == "new.txt"


def test_read_history_returns_recent_events(tmp_path: Path) -> None:
    """`read_history` should parse the latest entries in reverse chronological order."""

    repo = StateRepository()
    base_timestamp = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    events = [
        OperationEvent(
            timestamp=base_timestamp,
            operation="rename",
            source="old.txt",
            destination="new.txt",
        ),
        OperationEvent(
            timestamp=base_timestamp.replace(minute=5),
            operation="move",
            source="new.txt",
            destination="archive/new.txt",
        ),
    ]

    repo.append_history(tmp_path, events)

    fetched = repo.read_history(tmp_path, limit=1)
    assert len(fetched) == 1
    assert fetched[0].operation == "move"
    fetched_all = repo.read_history(tmp_path, limit=5)
    assert [entry.operation for entry in fetched_all] == ["move", "rename"]
