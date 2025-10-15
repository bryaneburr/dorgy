"""CLI integration tests for `dorgy org`."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from dorgy.cli import cli
from dorgy.ingestion.extractors import MetadataExtractor


def _env_with_home(tmp_path: Path) -> dict[str, str]:
    """Return environment variables pointing HOME to a temp directory.

    Args:
        tmp_path: Temporary directory provided by pytest.

    Returns:
        dict[str, str]: Environment mapping with HOME set.
    """
    env = dict(os.environ)
    env["HOME"] = str((tmp_path / "home"))
    return env


def test_cli_org_persists_state(tmp_path: Path) -> None:
    """Ensure `dorgy org` persists state data on success.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
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
    """Verify dry-run mode avoids creating state directories.

    Args:
        tmp_path: Temporary directory provided by pytest.
    """
    root = tmp_path / "dry"
    root.mkdir()
    (root / "note.txt").write_text("content", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["org", str(root), "--dry-run"], env=env)

    assert result.exit_code == 0
    assert "Dry run" in result.output
    assert not (root / ".dorgy").exists()


def test_cli_org_quarantine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure corrupted files are quarantined based on configuration.

    Args:
        tmp_path: Temporary directory provided by pytest.
        monkeypatch: Pytest monkeypatch fixture for patching modules.
    """
    root = tmp_path / "broken"
    root.mkdir()
    bad_file = root / "bad.txt"
    bad_file.write_text("oops", encoding="utf-8")

    env = _env_with_home(tmp_path)
    config_path = Path(env["HOME"]) / ".dorgy" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        "processing:\n  corrupted_files:\n    action: quarantine\n",
        encoding="utf-8",
    )

    class FailingExtractor(MetadataExtractor):
        """Extractor stub that raises from extract."""

        def extract(self, path: Path, mime_type: str):  # type: ignore[override]
            """Raise a ValueError to trigger quarantine behavior."""
            raise ValueError("broken")

        def preview(self, path: Path, mime_type: str):  # type: ignore[override]
            """Return None since no preview is generated."""
            return None

    monkeypatch.setattr("dorgy.cli.MetadataExtractor", FailingExtractor)

    runner = CliRunner()
    result = runner.invoke(cli, ["org", str(root)], env=env)

    assert result.exit_code == 0
    quarantine_file = root / ".dorgy" / "quarantine" / "bad.txt"
    assert quarantine_file.exists()
    assert not bad_file.exists()
