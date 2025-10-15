"""Tests validating scaffolding placeholders that remain unimplemented."""

from pathlib import Path

import pytest

from dorgy.state import DEFAULT_STATE_DIRNAME, CollectionState, StateRepository


def test_state_repository_methods_raise_not_implemented(tmp_path: Path) -> None:
    repo = StateRepository()
    root = tmp_path / "collection"

    assert repo.base_dirname == DEFAULT_STATE_DIRNAME

    with pytest.raises(NotImplementedError):
        repo.load(root)
    with pytest.raises(NotImplementedError):
        repo.save(root, CollectionState(root=str(root)))
    with pytest.raises(NotImplementedError):
        repo.initialize(root)
