"""CLI integration tests for the `dorgy version` command."""

from __future__ import annotations

import json
import os
import tomllib
from importlib import metadata
from pathlib import Path

from click.testing import CliRunner

from dorgy.cli import cli


def _expected_version() -> str:
    """Return the expected Dorgy version using package metadata or pyproject."""

    try:
        return metadata.version("dorgy")
    except metadata.PackageNotFoundError:
        pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        return data["project"]["version"]


def _env_with_home(tmp_path: Path) -> dict[str, str]:
    """Return environment variables directing HOME to a temp location."""

    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    return env


def test_version_command_outputs_version(tmp_path: Path) -> None:
    """`dorgy version` should print the current version."""

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["version"], env=env)

    assert result.exit_code == 0
    assert _expected_version() in result.output
    assert "Python" in result.output


def test_version_command_supports_json(tmp_path: Path) -> None:
    """`dorgy version --json` should emit structured metadata."""

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["version", "--json"], env=env)

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["version"] == _expected_version()
    assert payload["python_version"].startswith("3.")
    assert payload["source"]
