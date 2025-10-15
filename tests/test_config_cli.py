"""CLI tests for configuration commands."""

import os
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from dorgy.cli import cli
from dorgy.config import ConfigManager


def _env_with_home(tmp_path: Path) -> dict[str, Any]:
    env = dict(os.environ)
    env["HOME"] = str(tmp_path)
    return env


def _config_path(tmp_path: Path) -> Path:
    return tmp_path / ".dorgy" / "config.yaml"


def test_config_view_creates_and_displays_config(tmp_path: Path) -> None:
    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["config", "view"], env=env)

    assert result.exit_code == 0
    assert "llm:" in result.output


def test_config_set_updates_value_and_writes_diff(tmp_path: Path) -> None:
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
    runner = CliRunner()
    env = _env_with_home(tmp_path)

    manager = ConfigManager(config_path=_config_path(tmp_path))
    manager.ensure_exists()

    def _mock_edit(text: str, **_: Any) -> str:
        return text.replace("temperature: 0.1", "temperature: 0.55")

    monkeypatch.setattr("dorgy.cli.click.edit", _mock_edit)

    result = runner.invoke(cli, ["config", "edit"], env=env)

    assert result.exit_code == 0
    assert "updated" in result.output.lower()

    config = manager.load(include_env=False)
    assert config.llm.temperature == pytest.approx(0.55)
