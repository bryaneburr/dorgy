"""CLI integration tests for `dorgy watch`."""

from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from dorgy.cli import cli


def _env_with_home(tmp_path: Path) -> dict[str, str]:
    """Return environment variables pointing HOME to a temp directory.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        dict[str, str]: Environment mapping with HOME set.
    """
    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    return env


def test_cli_watch_once_persists_state(tmp_path: Path) -> None:
    """Ensure `dorgy watch --once` organizes files and persists state.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """

    root = tmp_path / "data"
    root.mkdir()
    (root / "memo.txt").write_text("watch me", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["watch", str(root), "--once"], env=env)

    assert result.exit_code == 0
    state_path = root / ".dorgy" / "state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["files"]  # at least one file tracked
    watch_log = root / ".dorgy" / "watch.log"
    assert watch_log.exists()
    assert "Watch batch" in result.output


def test_cli_watch_once_json(tmp_path: Path) -> None:
    """`dorgy watch --once --json` should emit structured batch data.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """

    root = tmp_path / "json"
    root.mkdir()
    (root / "report.txt").write_text("content", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["watch", str(root), "--once", "--json"], env=env)

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert "batches" in payload
    assert payload["batches"]
    batch = payload["batches"][0]
    assert batch["counts"]["processed"] == 1
    assert batch["context"]["source_root"].endswith("json")
