"""CLI integration tests for `dorgy org`."""

from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from dorgy.cli import cli


def _env_with_home(tmp_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["HOME"] = str((tmp_path / "home"))
    return env


def test_cli_org_persists_state(tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    (root / "doc.txt").write_text("hello world", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["org", str(root)], env=env)

    assert result.exit_code == 0
    state_path = root / ".dorgy" / "state.json"
    assert state_path.exists()
    state_data = json.loads(state_path.read_text(encoding="utf-8"))
    assert "doc.txt" in state_data["files"]
    assert state_data["files"]["doc.txt"].get("hash")


def test_cli_org_dry_run(tmp_path: Path) -> None:
    root = tmp_path / "dry"
    root.mkdir()
    (root / "note.txt").write_text("content", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["org", str(root), "--dry-run"], env=env)

    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert not (root / ".dorgy").exists()
