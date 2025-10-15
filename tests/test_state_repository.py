"""State repository tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from dorgy.state import (
    DEFAULT_STATE_DIRNAME,
    CollectionState,
    MissingStateError,
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
