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
    record = state_data["files"]["doc.txt"]
    assert record.get("hash")
    assert "Documents" in record.get("categories", [])
    assert record.get("rename_suggestion") == "doc"
    assert record.get("needs_review") is True


def test_cli_org_classification_updates_state(tmp_path: Path) -> None:
    """Classification decisions should persist to state records."""

    root = tmp_path / "classified"
    root.mkdir()
    (root / "invoice.pdf").write_text("amount", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)
    config_path = Path(env["HOME"]) / ".dorgy" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("organization:\n  rename_files: false\n", encoding="utf-8")

    result = runner.invoke(cli, ["org", str(root)], env=env)

    assert result.exit_code == 0
    state_path = root / ".dorgy" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    record = state["files"]["invoice.pdf"]
    assert "Documents" in record["categories"]
    assert record["rename_suggestion"] == "invoice"
    assert record.get("confidence") is not None
    assert record.get("needs_review") is True


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


def test_cli_org_renames_files_when_enabled(tmp_path: Path) -> None:
    """Files are renamed when classification suggests a new name."""

    root = tmp_path / "rename"
    root.mkdir()
    original = root / "Report 2020.TXT"
    original.write_text("budget", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["org", str(root)], env=env)

    assert result.exit_code == 0
    renamed = root / "report-2020.TXT"
    assert renamed.exists()
    state_path = root / ".dorgy" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "report-2020.TXT" in state["files"]
    assert state["files"]["report-2020.TXT"]["rename_suggestion"] == "report-2020"
