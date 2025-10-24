"""CLI integration tests for `dorgy org`."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner
from PIL import Image

from dorgy.classification import VisionCaption
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
    assert "documents/doc.txt" in state_data["files"]
    record = state_data["files"]["documents/doc.txt"]
    assert record.get("hash")
    assert "Documents" in record.get("categories", [])
    assert record.get("rename_suggestion") == "doc"
    assert record.get("needs_review") is False
    final_path = root / "documents" / "doc.txt"
    assert final_path.exists()
    snapshot_path = root / ".dorgy" / "orig.json"
    assert snapshot_path.exists()
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    snapshot_paths = {entry["path"] for entry in snapshot.get("entries", [])}
    assert "doc.txt" in snapshot_paths


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
    record = state["files"]["documents/invoice.pdf"]
    assert "Documents" in record["categories"]
    assert record["rename_suggestion"] == "invoice"
    assert record.get("confidence") is not None
    assert record.get("needs_review") is False


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
    assert "LLM configuration:" in result.output
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
    config_path = Path(env["HOME"]) / ".dorgy" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("organization:\n  rename_files: true\n", encoding="utf-8")

    result = runner.invoke(cli, ["org", str(root)], env=env)

    assert result.exit_code == 0
    renamed = root / "documents" / "report-2020.TXT"
    assert renamed.exists()
    state_path = root / ".dorgy" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "documents/report-2020.TXT" in state["files"]
    assert state["files"]["documents/report-2020.TXT"]["rename_suggestion"] == "report-2020"


def test_cli_org_records_vision_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Vision metadata is persisted to state records when captioning is enabled."""

    root = tmp_path / "vision"
    root.mkdir()
    image_path = root / "receipt.png"
    Image.new("RGB", (64, 64), color="white").save(image_path)

    env = _env_with_home(tmp_path)
    config_path = Path(env["HOME"]) / ".dorgy" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("processing:\n  process_images: true\n", encoding="utf-8")

    class StubVisionCaptioner:
        """Stub captioner capturing prompt usage."""

        instances: list["StubVisionCaptioner"] = []

        def __init__(self, *args, **kwargs) -> None:  # pragma: no cover - simple stub
            self.calls: list[tuple[Path, str | None, str | None]] = []
            StubVisionCaptioner.instances.append(self)

        def caption(
            self,
            path: Path,
            *,
            cache_key: str | None,
            prompt: str | None = None,
        ) -> VisionCaption:
            self.calls.append((path, cache_key, prompt))
            return VisionCaption(
                caption="Receipt from ACME Corp",
                labels=["Finance", "Receipt"],
                confidence=0.95,
                reasoning="Test caption",
            )

        def save_cache(self) -> None:
            return None

    monkeypatch.setattr("dorgy.cli.VisionCaptioner", StubVisionCaptioner)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "org",
            str(root),
            "--classify-prompt",
            "Highlight receipts",
            "--structure-prompt",
            "Group receipts by vendor",
        ],
        env=env,
    )

    assert result.exit_code == 0
    assert StubVisionCaptioner.instances
    assert StubVisionCaptioner.instances[0].calls
    assert StubVisionCaptioner.instances[0].calls[0][2] == "Highlight receipts"

    state_path = root / ".dorgy" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    record = next(rec for rec in state["files"].values() if rec.get("vision_caption"))
    assert record["vision_caption"] == "Receipt from ACME Corp"
    assert record["vision_labels"] == ["Finance", "Receipt"]
    assert pytest.approx(record["vision_confidence"], rel=1e-3) == 0.95
    assert record["vision_reasoning"] == "Test caption"


def test_cli_org_prompt_file_overrides_inline_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ensure `--classify-prompt-file` overrides inline prompts for organization runs."""

    root = tmp_path / "prompt-file"
    root.mkdir()
    Image.new("RGB", (32, 32), color="white").save(root / "invoice.png")

    prompt_file = tmp_path / "instructions.txt"
    prompt_content = "Line one\nLine two with detail"
    prompt_file.write_text(prompt_content, encoding="utf-8")

    class StubVisionCaptioner:
        """Stub captioner capturing prompt usage."""

        instances: list["StubVisionCaptioner"] = []

        def __init__(self, *args, **kwargs) -> None:  # pragma: no cover - simple stub
            self.calls: list[tuple[Path, str | None, str | None]] = []
            StubVisionCaptioner.instances.append(self)

        def caption(
            self,
            path: Path,
            *,
            cache_key: str | None,
            prompt: str | None = None,
        ) -> VisionCaption:
            self.calls.append((path, cache_key, prompt))
            return VisionCaption(
                caption="Receipt from ACME Corp",
                labels=["Finance", "Receipt"],
                confidence=0.95,
                reasoning="Test caption",
            )

        def save_cache(self) -> None:
            return None

    monkeypatch.setattr("dorgy.cli.VisionCaptioner", StubVisionCaptioner)

    runner = CliRunner()
    env = _env_with_home(tmp_path)
    config_path = Path(env["HOME"]) / ".dorgy" / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("processing:\n  process_images: true\n", encoding="utf-8")
    result = runner.invoke(
        cli,
        [
            "org",
            str(root),
            "--classify-prompt",
            "This should be ignored",
            "--classify-prompt-file",
            str(prompt_file),
            "--structure-prompt",
            "Structure invoices by accounting period",
        ],
        env=env,
    )

    assert result.exit_code == 0
    assert StubVisionCaptioner.instances
    assert StubVisionCaptioner.instances[0].calls
    recorded_prompt = StubVisionCaptioner.instances[0].calls[0][2]
    assert recorded_prompt == prompt_content


def test_cli_undo_dry_run_shows_snapshot(tmp_path: Path) -> None:
    """Undo dry-run should surface snapshot details for user confirmation."""

    root = tmp_path / "history"
    root.mkdir()
    (root / "note.txt").write_text("content", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    undo_result = runner.invoke(cli, ["undo", str(root), "--dry-run"], env=env)

    assert undo_result.exit_code == 0
    assert "Snapshot captured" in undo_result.output
    assert "note.txt" in undo_result.output
    assert "Recent history" in undo_result.output
    assert "RENAME" in undo_result.output or "MOVE" in undo_result.output


def test_cli_undo_json(tmp_path: Path) -> None:
    """Undo JSON output should return structured plan and history details."""

    root = tmp_path / "json"
    root.mkdir()
    (root / "budget.txt").write_text("2024", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    dry_json = runner.invoke(cli, ["undo", str(root), "--dry-run", "--json"], env=env)
    assert dry_json.exit_code == 0
    payload = json.loads(dry_json.output)
    assert payload["plan"] is not None
    assert payload["snapshot"] is not None
    assert isinstance(payload.get("history"), list)

    apply_json = runner.invoke(cli, ["undo", str(root), "--json"], env=env)
    assert apply_json.exit_code == 0
    applied = json.loads(apply_json.output)
    assert applied["rolled_back"] is True
    assert applied["plan"] is not None


def test_cli_org_supports_output_relocation(tmp_path: Path) -> None:
    """Organizing into an output directory should copy files into the new root."""

    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "receipt.txt").write_text("paid", encoding="utf-8")

    output_root = tmp_path / "organized"

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(
        cli,
        ["org", str(source_root), "--output", str(output_root)],
        env=env,
    )

    assert result.exit_code == 0
    final_path = output_root / "documents" / "receipt.txt"
    assert final_path.exists()
    # Originals remain when copying into an output directory.
    assert (source_root / "receipt.txt").exists()
    state_path = output_root / ".dorgy" / "state.json"
    assert state_path.exists()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert "documents/receipt.txt" in state["files"]


def test_cli_status_requires_state(tmp_path: Path) -> None:
    """Status should fail when no state has been recorded yet."""

    root = tmp_path / "nostate"
    root.mkdir()

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["status", str(root)], env=env)

    assert result.exit_code != 0
    assert "No organization state" in result.output


def test_cli_status_outputs_summary(tmp_path: Path) -> None:
    """Status command should show a summary of the collection."""

    root = tmp_path / "status"
    root.mkdir()
    (root / "todo.txt").write_text("tasks", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    status_result = runner.invoke(cli, ["status", str(root)], env=env)

    assert status_result.exit_code == 0
    assert "Status for" in status_result.output
    assert "Files tracked" in status_result.output
    assert "Recent history" in status_result.output
    assert "Status summary for" in status_result.output


def test_cli_status_json(tmp_path: Path) -> None:
    """Status JSON output should include state, snapshot, and history data."""

    root = tmp_path / "status-json"
    root.mkdir()
    (root / "invoice.txt").write_text("paid", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    status_result = runner.invoke(cli, ["status", str(root), "--json"], env=env)
    assert status_result.exit_code == 0
    payload = json.loads(status_result.output)
    assert payload["counts"]["files"] >= 1
    assert "history" in payload
    assert "snapshot" in payload


def test_cli_org_summary_mode_outputs_summary_line(tmp_path: Path) -> None:
    """Summary mode should surface only the final summary line."""

    root = tmp_path / "summary-mode"
    root.mkdir()
    (root / "project.txt").write_text("notes", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["org", str(root), "--summary"], env=env)

    assert result.exit_code == 0
    assert "Organization summary for" in result.output
    assert "Organization preview" not in result.output


def test_cli_org_quiet_mode_is_silent(tmp_path: Path) -> None:
    """Quiet mode should suppress non-error output."""

    root = tmp_path / "quiet-mode"
    root.mkdir()
    (root / "report.txt").write_text("content", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["org", str(root), "--quiet"], env=env)

    assert result.exit_code == 0
    assert result.output.strip() == ""


def test_cli_status_json_error_when_state_missing(tmp_path: Path) -> None:
    """Status JSON should surface standardized error payloads when state is absent."""

    root = tmp_path / "missing-status"
    root.mkdir()

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(cli, ["status", str(root), "--json"], env=env)

    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "cli_error"
    assert "No organization state" in payload["error"]["message"]


def test_cli_undo_summary_mode(tmp_path: Path) -> None:
    """Undo summary mode should emit only the summary line."""

    root = tmp_path / "undo-summary"
    root.mkdir()
    (root / "draft.txt").write_text("text", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    undo_result = runner.invoke(cli, ["undo", str(root), "--summary"], env=env)

    assert undo_result.exit_code == 0
    assert "Undo summary for" in undo_result.output
    assert "Rolled back" not in undo_result.output


def test_cli_undo_removes_empty_directories(tmp_path: Path) -> None:
    """Undo should remove directories created during organization when they are empty."""

    root = tmp_path / "undo-cleanup"
    root.mkdir()
    original_file = root / "letter.txt"
    original_file.write_text("hello", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    apply_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert apply_result.exit_code == 0

    destination_dir = root / "documents"
    destination_file = destination_dir / "letter.txt"
    assert destination_file.exists()

    undo_result = runner.invoke(cli, ["undo", str(root)], env=env)
    assert undo_result.exit_code == 0

    assert original_file.exists()
    assert not destination_dir.exists()


def test_cli_status_respects_quiet_default(tmp_path: Path) -> None:
    """Status command should honor the CLI quiet default from configuration."""

    root = tmp_path / "quiet-default"
    root.mkdir()
    (root / "doc.txt").write_text("text", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    config_path = Path(env["HOME"]) / ".dorgy" / "config.yaml"
    config_path.write_text("cli:\n  quiet_default: true\n", encoding="utf-8")

    status_result = runner.invoke(cli, ["status", str(root)], env=env)

    assert status_result.exit_code == 0
    assert status_result.output.strip() == ""
