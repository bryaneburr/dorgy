"""CLI integration tests for `dorgy watch`."""

from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from dorgy.cli import cli
from dorgy.config import DorgyConfig
from dorgy.watch.service import WatchEvent, WatchService


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
    assert batch["context"]["llm"]["model"]
    assert "summary" in batch["context"]["llm"]


def test_cli_watch_prompt_file_overrides_inline_prompt(tmp_path: Path) -> None:
    """Ensure watch JSON payload reflects classification prompt file overrides."""

    root = tmp_path / "prompt-watch"
    root.mkdir()
    (root / "report.txt").write_text("content", encoding="utf-8")

    prompt_file = tmp_path / "prompt.txt"
    prompt_content = "Watch prompt\nSecond line"
    prompt_file.write_text(prompt_content, encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    result = runner.invoke(
        cli,
        [
            "watch",
            str(root),
            "--once",
            "--json",
            "--classify-prompt",
            "ignored prompt",
            "--classify-prompt-file",
            str(prompt_file),
            "--structure-prompt",
            "Structure batches by project",
        ],
        env=env,
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    batches = payload.get("batches", [])
    assert batches
    context = batches[0]["context"]
    assert context["classification_prompt"] == prompt_content
    assert context["structure_prompt"] == "Structure batches by project"
    assert context["prompt"] == prompt_content


def _state_paths(root: Path) -> set[str]:
    """Return the set of tracked relative paths for ``root``."""

    state_path = root / ".dorgy" / "state.json"
    data = json.loads(state_path.read_text(encoding="utf-8"))
    return set(data["files"].keys())


def _make_service(root: Path, *, allow_deletions: bool) -> WatchService:
    """Construct a watch service with predictable settings for tests."""

    config = DorgyConfig()
    config.organization.rename_files = False
    return WatchService(
        config,
        roots=[root],
        classification_prompt=None,
        structure_prompt=None,
        output=None,
        dry_run=False,
        recursive=False,
        allow_deletions=allow_deletions,
    )


def test_watch_deleted_requires_opt_in(tmp_path: Path) -> None:
    """Ensure deletions are suppressed until explicitly allowed."""

    root = tmp_path / "delete-root"
    root.mkdir()
    (root / "sample.txt").write_text("content", encoding="utf-8")

    service = _make_service(root, allow_deletions=False)
    initial_batch = service._run_batch(root, [WatchEvent(kind="scan", src=root)])
    assert initial_batch is not None

    initial_paths = _state_paths(root)
    assert initial_paths
    relative_entry = next(iter(initial_paths))
    tracked_path = root / Path(relative_entry)
    assert tracked_path.exists()

    tracked_path.unlink()

    batch = service._run_batch(root, [WatchEvent(kind="deleted", src=tracked_path)])
    assert batch is not None
    assert batch.counts["deletes"] == 0
    assert batch.suppressed_deletions
    assert batch.suppressed_deletions[0]["cause"] == "config"
    assert initial_paths.issubset(_state_paths(root))


def test_watch_deleted_removes_state_when_allowed(tmp_path: Path) -> None:
    """Ensure deletions drop state entries when opt-in is enabled."""

    root = tmp_path / "delete-allow"
    root.mkdir()
    (root / "report.txt").write_text("payload", encoding="utf-8")

    bootstrap = _make_service(root, allow_deletions=False)
    bootstrap._run_batch(root, [WatchEvent(kind="scan", src=root)])
    original_paths = _state_paths(root)
    assert original_paths
    relative_entry = next(iter(original_paths))
    tracked_path = root / Path(relative_entry)
    assert tracked_path.exists()

    tracked_path.unlink()

    allow_service = _make_service(root, allow_deletions=True)
    batch = allow_service._run_batch(root, [WatchEvent(kind="deleted", src=tracked_path)])
    assert batch is not None
    assert batch.counts["deletes"] == 1
    assert not batch.suppressed_deletions
    removals = batch.json_payload["removals"]
    assert removals and removals[0]["kind"] == "deleted"
    assert removals[0]["executed"] is True
    assert not _state_paths(root)


def test_watch_move_within_updates_state_without_opt_in(tmp_path: Path) -> None:
    """Internal moves should update state even without destructive opt-in."""

    root = tmp_path / "move-within"
    root.mkdir()
    (root / "photo.txt").write_text("image", encoding="utf-8")

    service = _make_service(root, allow_deletions=False)
    service._run_batch(root, [WatchEvent(kind="scan", src=root)])
    original_paths = _state_paths(root)
    assert len(original_paths) == 1
    original_entry = next(iter(original_paths))
    source_path = root / Path(original_entry)
    assert source_path.exists()

    moved_path = source_path.with_name("renamed.txt")
    source_path.rename(moved_path)

    batch = service._run_batch(
        root,
        [WatchEvent(kind="moved", src=source_path, dest=moved_path)],
    )
    assert batch is not None
    assert batch.counts["deletes"] == 1
    assert not batch.suppressed_deletions
    assert batch.json_payload["context"]["llm"]["model"]
    removals = batch.json_payload["removals"]
    assert removals and removals[0]["kind"] == "moved_within"
    new_paths = _state_paths(root)
    assert original_entry not in new_paths
    assert len(new_paths) == 1
    new_entry = next(iter(new_paths))
    assert "renamed" in new_entry or new_entry.endswith("photo.txt")


def test_watch_move_outside_requires_opt_in(tmp_path: Path) -> None:
    """Moves leaving the collection require explicit deletion opt-in."""

    root = tmp_path / "move-out"
    root.mkdir()
    (root / "note.txt").write_text("notes", encoding="utf-8")

    outside = tmp_path / "outside"
    outside.mkdir()

    service = _make_service(root, allow_deletions=False)
    service._run_batch(root, [WatchEvent(kind="scan", src=root)])
    tracked = _state_paths(root)
    assert tracked
    original_entry = next(iter(tracked))
    source_path = root / Path(original_entry)
    assert source_path.exists()

    destination = outside / source_path.name
    source_path.rename(destination)

    suppressed_batch = service._run_batch(
        root,
        [WatchEvent(kind="moved", src=source_path, dest=destination)],
    )
    assert suppressed_batch is not None
    assert suppressed_batch.json_payload["context"]["llm"]["model"]
    assert suppressed_batch.counts["deletes"] == 0
    assert suppressed_batch.suppressed_deletions
    assert suppressed_batch.suppressed_deletions[0]["kind"] == "moved_out"
    assert tracked.issubset(_state_paths(root))

    allow_service = _make_service(root, allow_deletions=True)
    executed_batch = allow_service._run_batch(
        root,
        [WatchEvent(kind="moved", src=source_path, dest=destination)],
    )
    assert executed_batch is not None
    assert executed_batch.json_payload["context"]["llm"]["model"]
    assert executed_batch.counts["deletes"] == 1
    removals = executed_batch.json_payload["removals"]
    assert removals and removals[0]["kind"] == "moved_out"
    assert removals[0]["executed"] is True
    assert not _state_paths(root)
