"""Unit tests for configuration management."""

from pathlib import Path

import pytest

from dorgy.config import (
    ConfigError,
    DorgyConfig,
    ensure_config,
    load_config,
    resolve_with_precedence,
    save_config,
)


def test_ensure_exists_creates_default_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure ensure_exists creates the default configuration file.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture for environment variables.
    """
    monkeypatch.setenv("HOME", str(tmp_path))

    path = ensure_config()

    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "llm:" in text

    config = load_config(include_env=False)
    assert isinstance(config, DorgyConfig)


def test_resolve_with_precedence_respects_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirm precedence order of file, env, and CLI overrides.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture for environment variables.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    ensure_config()

    save_config({"llm": {"model": "gpt-4"}, "processing": {"max_file_size_mb": 64}})

    env = {"DORGY__LLM__TEMPERATURE": "0.7"}
    cli_overrides = {
        "llm.temperature": 0.2,
        "cli.quiet_default": True,
    }

    config = load_config(cli_overrides=cli_overrides, env_overrides=env)

    assert config.llm.model == "gpt-4"
    assert config.processing.max_file_size_mb == 64
    # CLI overrides take precedence over environment
    assert config.llm.temperature == pytest.approx(0.2)
    assert config.cli.quiet_default is True


def test_environment_values_support_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure environment overrides accept structured YAML payloads."""

    monkeypatch.setenv("HOME", str(tmp_path))
    ensure_config()

    env = {
        "DORGY__RULES": "[{'pattern': '.*', 'destination': 'outbox'}]",
        "DORGY__PROCESSING__LOCKED_FILES": "{'retry_attempts': 5}",
    }
    config = load_config(env_overrides=env)

    assert config.rules == [{"pattern": ".*", "destination": "outbox"}]
    assert config.processing.locked_files.retry_attempts == 5


def test_invalid_yaml_raises_config_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure invalid YAML raises ConfigError when loading configuration.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture for environment variables.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    path = ensure_config()

    path.write_text("- not-a-mapping", encoding="utf-8")

    with pytest.raises(ConfigError):
        load_config()


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
