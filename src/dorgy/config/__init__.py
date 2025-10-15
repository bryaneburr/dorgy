"""Configuration management for Dorgy."""

from __future__ import annotations

import os
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import yaml

from .exceptions import ConfigError
from .models import DorgyConfig
from .resolver import flatten_for_env, resolve_with_precedence

DEFAULT_CONFIG_PATH = Path("~/.dorgy/config.yaml")
_CONFIG_HEADER = textwrap.dedent(
    """\
    # Dorgy configuration file
    # Generated automatically; manage via `dorgy config edit` or the `dorgy config set` command.
    # See SPEC.md for detailed field descriptions.
    """
)


class ConfigManager:
    """Load and persist configuration data, applying precedence rules."""

    def __init__(
        self,
        config_path: Path | None = None,
        *,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._config_path = (config_path or DEFAULT_CONFIG_PATH).expanduser()
        self._env = env if env is not None else os.environ

    @property
    def config_path(self) -> Path:
        """Return the resolved configuration path."""
        return self._config_path

    def load(
        self,
        *,
        cli_overrides: Mapping[str, Any] | None = None,
        include_env: bool = True,
        ensure_file: bool = True,
        env_overrides: Mapping[str, str] | None = None,
    ) -> DorgyConfig:
        """Load configuration data from disk, applying precedence rules."""
        if ensure_file:
            self.ensure_exists()

        file_data = self._read_file()
        env_data: Mapping[str, str] | None
        if include_env:
            env_data = env_overrides if env_overrides is not None else self._env
        else:
            env_data = None

        return resolve_with_precedence(
            defaults=DorgyConfig(),
            file_overrides=file_data,
            env_overrides=self._extract_env(env_data) if env_data else None,
            cli_overrides=cli_overrides,
        )

    def load_file_overrides(self) -> dict[str, Any]:
        """Return raw overrides stored on disk."""
        return self._read_file()

    def save(self, config: DorgyConfig | Mapping[str, Any]) -> None:
        """Persist configuration data to disk."""
        data = self._coerce_to_dict(config)
        self._write_file(data, include_header=True)

    def ensure_exists(self) -> Path:
        """Create a configuration file with defaults if one does not exist."""
        path = self._config_path
        if path.exists():
            return path

        self._write_file(DorgyConfig().model_dump(mode="python"), include_header=True)
        return path

    def read_text(self) -> str:
        """Return the current configuration file contents."""
        if not self._config_path.exists():
            return ""
        return self._config_path.read_text(encoding="utf-8")

    # Internal helpers -------------------------------------------------

    def _coerce_to_dict(self, value: DorgyConfig | Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(value, DorgyConfig):
            return value.model_dump(mode="python")
        return dict(value)

    def _read_file(self) -> dict[str, Any]:
        if not self._config_path.exists():
            return {}

        try:
            raw = yaml.safe_load(self._config_path.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise ConfigError(f"Failed to parse configuration file: {exc}") from exc

        if not isinstance(raw, dict):
            raise ConfigError("Configuration file must contain a mapping at the top level.")

        return raw

    def _write_file(self, data: Mapping[str, Any], *, include_header: bool = False) -> None:
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = yaml.safe_dump(dict(data), sort_keys=False)
        header = _CONFIG_HEADER if include_header else ""
        stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        timestamp = f"# Last updated: {stamp}\n"
        self._config_path.write_text(header + timestamp + serialized, encoding="utf-8")

    def _extract_env(self, env: Mapping[str, str]) -> dict[str, Any]:
        prefix = "DORGY__"
        overrides: dict[str, Any] = {}
        for key, raw_value in env.items():
            if not key.startswith(prefix):
                continue
            path = key[len(prefix) :].split("__")
            if not path:
                continue
            parsed_value: Any
            try:
                parsed_value = yaml.safe_load(raw_value)
            except yaml.YAMLError:
                parsed_value = raw_value

            self._assign_nested(overrides, [segment.lower() for segment in path], parsed_value)

        return overrides

    def _assign_nested(self, target: dict[str, Any], path: list[str], value: Any) -> None:
        current = target
        for segment in path[:-1]:
            existing = current.get(segment)
            if not isinstance(existing, dict):
                existing = {}
                current[segment] = existing
            current = existing
        current[path[-1]] = value


__all__ = [
    "ConfigManager",
    "DEFAULT_CONFIG_PATH",
    "DorgyConfig",
    "resolve_with_precedence",
    "flatten_for_env",
    "ConfigError",
]
