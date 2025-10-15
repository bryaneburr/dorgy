"""Configuration management scaffolding for Dorgy."""

from __future__ import annotations

from pathlib import Path

from .models import DorgyConfig

DEFAULT_CONFIG_PATH = Path("~/.dorgy/config.yaml")


class ConfigManager:
    """Placeholder manager responsible for loading and saving configuration."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = (config_path or DEFAULT_CONFIG_PATH).expanduser()

    @property
    def config_path(self) -> Path:
        """Return the resolved configuration path."""
        return self._config_path

    def load(self) -> DorgyConfig:
        """Load configuration data from disk."""
        raise NotImplementedError("ConfigManager.load will be implemented in Phase 1.")

    def save(self, config: DorgyConfig) -> None:
        """Persist configuration data to disk."""
        raise NotImplementedError("ConfigManager.save will be implemented in Phase 1.")

    def ensure_exists(self) -> Path:
        """Create a configuration file with defaults if one does not exist."""
        raise NotImplementedError("ConfigManager.ensure_exists will be implemented in Phase 1.")


__all__ = ["ConfigManager", "DEFAULT_CONFIG_PATH", "DorgyConfig"]
