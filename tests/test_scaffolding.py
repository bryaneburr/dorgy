"""Tests validating scaffolding placeholders that remain unimplemented."""

from dorgy.state import DEFAULT_STATE_DIRNAME, StateRepository


def test_state_repository_base_dirname_default() -> None:
    repo = StateRepository()

    assert repo.base_dirname == DEFAULT_STATE_DIRNAME
