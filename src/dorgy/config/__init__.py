"""Configuration utilities built directly on Durango."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Mapping

import yaml
from durango import ConfigManager as DurangoConfigManager
from durango.exceptions import (
    ConfigFileError as DurangoConfigFileError,
)
from durango.exceptions import (
    ConfigValidationError as DurangoConfigValidationError,
)
from durango.exceptions import (
    UnsupportedFormatError,
)
from durango.sources.file import FileSourceConfig, ensure_config_file, load_config_file

from .exceptions import ConfigError
from .models import DorgyConfig
from .resolver import flatten_for_env, normalize_override_mapping, resolve_with_precedence

CONFIG_IDENTIFIER = "DORGY"
DEFAULT_CONFIG_PATH = Path("~/.dorgy/config.yaml")
_CONFIG_ERRORS = (
    DurangoConfigFileError,
    DurangoConfigValidationError,
    UnsupportedFormatError,
)


def create_manager(config_path: Path | None = None) -> DurangoConfigManager[DorgyConfig]:
    """Return a Durango ConfigManager configured for Dorgy."""

    return DurangoConfigManager(
        settings_type=DorgyConfig,
        identifier=CONFIG_IDENTIFIER,
        default_file=_resolve_path(config_path),
    )


def load_config(
    *,
    config_path: Path | None = None,
    include_env: bool = True,
    env_overrides: Mapping[str, Any] | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
) -> DorgyConfig:
    """Load configuration using Durango precedence rules.

    Args:
        config_path: Optional override for the configuration file location.
        include_env: Whether to include environment-based overrides.
        env_overrides: Explicit environment mapping (defaults to ``os.environ``).
        cli_overrides: Overrides supplied by the CLI layer.

    Returns:
        DorgyConfig: Fully merged configuration model.

    Raises:
        ConfigError: If the configuration cannot be parsed or validated.
    """
    manager = create_manager(config_path)
    environ: Mapping[str, Any] | None
    if include_env:
        source = env_overrides if env_overrides is not None else os.environ
        environ = _prepare_environment(source)
    else:
        environ = {}

    overrides: Mapping[str, Any] | None = None
    if cli_overrides:
        overrides = normalize_override_mapping(cli_overrides, source_name="cli")

    try:
        return manager.load(overrides=overrides, environ=environ)
    except _CONFIG_ERRORS as exc:
        raise ConfigError(str(exc)) from exc


def ensure_config(config_path: Path | None = None) -> Path:
    """Create the configuration file with defaults if it does not exist."""

    resolved = _resolve_path(config_path)
    file_config = FileSourceConfig(default_path=resolved)
    ensure_config_file(resolved, config=file_config, data=DorgyConfig().model_dump())
    return resolved


def load_file_overrides(config_path: Path | None = None) -> dict[str, Any]:
    """Return raw overrides stored on disk."""

    resolved = _resolve_path(config_path)
    file_config = FileSourceConfig(default_path=resolved)
    try:
        return load_config_file(resolved, config=file_config)
    except _CONFIG_ERRORS as exc:
        raise ConfigError(str(exc)) from exc


def save_config(data: DorgyConfig | Mapping[str, Any], *, config_path: Path | None = None) -> None:
    """Persist configuration values to disk."""

    resolved = _resolve_path(config_path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    payload = data.model_dump(mode="python") if isinstance(data, DorgyConfig) else dict(data)
    serialized = yaml.safe_dump(payload, sort_keys=False)
    resolved.write_text(serialized, encoding="utf-8")


def read_config_text(config_path: Path | None = None) -> str:
    """Return the raw configuration file contents."""

    resolved = _resolve_path(config_path)
    if not resolved.exists():
        return ""
    return resolved.read_text(encoding="utf-8")


def _resolve_path(path: Path | None) -> Path:
    return (path or DEFAULT_CONFIG_PATH).expanduser()


def _prepare_environment(env: Mapping[str, Any]) -> dict[str, Any]:
    """Parse environment overrides using YAML semantics for nested structures."""

    parsed: dict[str, Any] = {}
    for key, value in env.items():
        if not isinstance(key, str):
            continue
        if not key.startswith(f"{CONFIG_IDENTIFIER}__"):
            parsed[key] = value
            continue
        if isinstance(value, str):
            try:
                parsed[key] = yaml.safe_load(value)
                continue
            except yaml.YAMLError:
                parsed[key] = value
                continue
        parsed[key] = value
    return parsed


__all__ = [
    "CONFIG_IDENTIFIER",
    "DEFAULT_CONFIG_PATH",
    "ConfigError",
    "DorgyConfig",
    "create_manager",
    "ensure_config",
    "flatten_for_env",
    "load_config",
    "load_file_overrides",
    "normalize_override_mapping",
    "read_config_text",
    "resolve_with_precedence",
    "save_config",
]
