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
    """Return a ConfigManager rooted under a temporary HOME.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture for environment variables.

    Returns:
        ConfigManager: Manager instance bound to the temporary location.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    return ConfigManager()


def test_ensure_exists_creates_default_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure ensure_exists creates the default configuration file.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture for environment variables.
    """
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
    """Confirm precedence order of file, env, and CLI overrides.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture for environment variables.
    """
    manager = _fresh_manager(tmp_path, monkeypatch)
    manager.ensure_exists()

    manager.save({"llm": {"model": "gpt-4"}, "processing": {"max_file_size_mb": 64}})

    env = {"DORGY__LLM__TEMPERATURE": "0.7"}
    cli_overrides = {
        "llm.temperature": 0.2,
        "cli.quiet_default": True,
    }

    config = manager.load(cli_overrides=cli_overrides, env_overrides=env)

    assert config.llm.model == "gpt-4"
    assert config.processing.max_file_size_mb == 64
    # CLI overrides take precedence over environment
    assert config.llm.temperature == pytest.approx(0.2)
    assert config.cli.quiet_default is True


def test_invalid_yaml_raises_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure invalid YAML raises ConfigError when loading configuration.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture for environment variables.
    """
    manager = _fresh_manager(tmp_path, monkeypatch)
    manager.ensure_exists()

    manager.config_path.write_text("- not-a-mapping", encoding="utf-8")

    with pytest.raises(ConfigError):
        manager.load()


def test_flatten_for_env_round_trips_defaults() -> None:
    """Verify flatten_for_env produces expected defaults."""
    flat = flatten_for_env(DorgyConfig())

    assert flat["DORGY__LLM__MODEL"] == "openai/gpt-5"
    assert flat["DORGY__LLM__TEMPERATURE"] == "1.0"
    assert flat["DORGY__LLM__MAX_TOKENS"] == "25000"
    assert flat["DORGY__LLM__API_BASE_URL"] == "null"
    assert "DORGY__LLM__PROVIDER" not in flat
    assert flat["DORGY__PROCESSING__MAX_FILE_SIZE_MB"] == "100"
    assert flat["DORGY__CLI__QUIET_DEFAULT"] == "False"
    assert flat["DORGY__CLI__SUMMARY_DEFAULT"] == "False"
    assert flat["DORGY__CLI__STATUS_HISTORY_LIMIT"] == "5"


def test_resolve_with_precedence_invalid_value_raises() -> None:
    """Ensure invalid override values raise ConfigError."""
    with pytest.raises(ConfigError):
        resolve_with_precedence(
            defaults=DorgyConfig(),
            file_overrides={"processing": {"max_file_size_mb": "not-an-int"}},
        )


def test_llm_defaults_updated() -> None:
    """Ensure new LLM defaults are reflected in the configuration."""

    settings = DorgyConfig().llm
    assert settings.model == "openai/gpt-5"
    assert settings.temperature == pytest.approx(1.0)
    assert settings.max_tokens == 25_000
    assert settings.api_base_url is None
