"""Tests for Phase 0 scaffolding placeholders."""

from pathlib import Path

import pytest

from dorgy.config import (
    DEFAULT_CONFIG_PATH,
    ConfigManager,
    DorgyConfig,
    flatten_for_env,
    resolve_with_precedence,
)
from dorgy.state import DEFAULT_STATE_DIRNAME, CollectionState, StateRepository


def test_config_manager_defaults_use_expected_path() -> None:
    manager = ConfigManager()

    assert manager.config_path == DEFAULT_CONFIG_PATH.expanduser()

    with pytest.raises(NotImplementedError):
        manager.load()
    with pytest.raises(NotImplementedError):
        manager.save(DorgyConfig())
    with pytest.raises(NotImplementedError):
        manager.ensure_exists()

    with pytest.raises(NotImplementedError):
        resolve_with_precedence(defaults=DorgyConfig())
    with pytest.raises(NotImplementedError):
        flatten_for_env(DorgyConfig())


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
