"""Unit tests for configuration management."""

from pathlib import Path

import pytest

from dorgy.config import (
    ConfigError,
    ConfigManager,
    DorgyConfig,
    flatten_for_env,
    resolve_with_precedence,
)


def _fresh_manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConfigManager:
    monkeypatch.setenv("HOME", str(tmp_path))
    return ConfigManager()


def test_ensure_exists_creates_default_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _fresh_manager(tmp_path, monkeypatch)

    path = manager.ensure_exists()

    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "Dorgy configuration file" in text
    assert "Last updated:" in text

    config = manager.load(include_env=False)
    assert isinstance(config, DorgyConfig)


def test_resolve_with_precedence_respects_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manager = _fresh_manager(tmp_path, monkeypatch)
    manager.ensure_exists()

    manager.save({"llm": {"model": "gpt-4"}, "processing": {"max_file_size_mb": 64}})

    env = {"DORGY__LLM__TEMPERATURE": "0.7"}
    cli = {"llm.temperature": 0.2}

    config = manager.load(cli_overrides=cli, env_overrides=env)

    assert config.llm.model == "gpt-4"
    assert config.processing.max_file_size_mb == 64
    # CLI overrides take precedence over environment
    assert config.llm.temperature == pytest.approx(0.2)


def test_invalid_yaml_raises_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _fresh_manager(tmp_path, monkeypatch)
    manager.ensure_exists()

    manager.config_path.write_text("- not-a-mapping", encoding="utf-8")

    with pytest.raises(ConfigError):
        manager.load()


def test_flatten_for_env_round_trips_defaults() -> None:
    flat = flatten_for_env(DorgyConfig())

    assert flat["DORGY__LLM__PROVIDER"] == "local"
    assert flat["DORGY__PROCESSING__MAX_FILE_SIZE_MB"] == "100"


def test_resolve_with_precedence_invalid_value_raises() -> None:
    with pytest.raises(ConfigError):
        resolve_with_precedence(
            defaults=DorgyConfig(),
            file_overrides={"processing": {"max_file_size_mb": "not-an-int"}},
        )
