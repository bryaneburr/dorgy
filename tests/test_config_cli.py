"""CLI tests for configuration commands."""

import os
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from dorgy.cli import cli
from dorgy.config import ConfigManager


def _env_with_home(tmp_path: Path) -> dict[str, Any]:
    """Return environment variables pointing HOME to a temporary directory.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        dict[str, Any]: Environment mapping with HOME set.
    """
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    return env


def _config_path(tmp_path: Path) -> Path:
    """Return the configuration path rooted at the temporary HOME.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        Path: Expected path to the configuration file.
    """
    return tmp_path / ".dorgy" / "config.yaml"


def test_config_view_creates_and_displays_config(tmp_path: Path) -> None:
    """Ensure `config view` bootstraps and displays configuration.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["config", "view"], env=env)

    assert result.exit_code == 0
    assert "llm:" in result.output


def test_config_set_updates_value_and_writes_diff(tmp_path: Path) -> None:
    """Ensure `config set` updates values and prints a diff.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["config", "set", "llm.temperature", "--value", "0.42"], env=env)

    assert result.exit_code == 0
    assert "0.42" in result.output

    manager = ConfigManager(config_path=_config_path(tmp_path))
    manager.ensure_exists()
    config = manager.load(include_env=False)
    assert config.llm.temperature == pytest.approx(0.42)


def test_config_edit_applies_changes(tmp_path: Path, monkeypatch) -> None:
    """Verify `config edit` persists modifications from the editor.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture for patching behavior.
    """
    runner = CliRunner()
    env = _env_with_home(tmp_path)

    manager = ConfigManager(config_path=_config_path(tmp_path))
    manager.ensure_exists()

    def _mock_edit(text: str, **_: Any) -> str:
        """Simulate a user editing the configuration file.

        Args:
            text: Original file contents presented to the editor.
            **_: Additional keyword arguments ignored by the stub.

        Returns:
            str: Modified text with the temperature updated.
        """
        return text.replace("temperature: 1.0", "temperature: 0.55")

    monkeypatch.setattr("dorgy.cli.click.edit", _mock_edit)

    result = runner.invoke(cli, ["config", "edit"], env=env)

    assert result.exit_code == 0
    assert "updated" in result.output.lower()

    config = manager.load(include_env=False)
    assert config.llm.temperature == pytest.approx(0.55)
