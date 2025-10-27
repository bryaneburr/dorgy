"""CLI integration tests for `dorgy mv`."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from dorgy.cli import cli
from dorgy.search.index import DEFAULT_COLLECTION_NAME

chromadb = pytest.importorskip("chromadb")


def _env_with_home(tmp_path: Path) -> dict[str, str]:
    """Return environment variables pointing HOME to a temp directory."""

    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    env.setdefault("DORGY_USE_FALLBACKS", "1")
    return env


def _state_relative_path(root: Path) -> str:
    """Return the single relative path stored in the collection state."""

    state_path = root / ".dorgy" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["files"], "State file should contain at least one entry."
    return next(iter(state["files"].keys()))


def test_cli_mv_moves_file_and_updates_state(tmp_path: Path) -> None:
    """`dorgy mv` should move files and update state metadata."""

    root = tmp_path / "move"
    root.mkdir()
    (root / "sample.txt").write_text("content", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    relative_path = _state_relative_path(root)
    current_path = (root / Path(relative_path)).resolve()
    destination = (root / "archive" / Path(relative_path).name).resolve()

    mv_result = runner.invoke(cli, ["mv", str(current_path), str(destination)], env=env)
    assert mv_result.exit_code == 0
    assert destination.exists()
    assert not current_path.exists()

    updated_state = json.loads((root / ".dorgy" / "state.json").read_text(encoding="utf-8"))
    new_paths = set(updated_state["files"].keys())
    assert any(path.endswith(f"archive/{Path(relative_path).name}") for path in new_paths)


def test_cli_mv_dry_run_preserves_files(tmp_path: Path) -> None:
    """Dry-run mode should preview moves without side effects."""

    root = tmp_path / "dry-run"
    root.mkdir()
    (root / "note.txt").write_text("content", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    relative_path = _state_relative_path(root)
    current_path = (root / Path(relative_path)).resolve()
    destination = (root / "reports" / Path(relative_path).name).resolve()

    result = runner.invoke(
        cli,
        ["mv", str(current_path), str(destination), "--dry-run", "--json"],
        env=env,
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["context"]["dry_run"] is True
    assert payload["counts"]["moved"] == 1
    assert current_path.exists()
    assert not destination.exists()


def test_cli_mv_conflict_skip(tmp_path: Path) -> None:
    """Skip conflict strategy should leave files untouched when collisions occur."""

    root = tmp_path / "skip"
    root.mkdir()
    (root / "invoice.pdf").write_text("content", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    relative_path = _state_relative_path(root)
    current_path = (root / Path(relative_path)).resolve()
    destination_dir = root / "archive"
    destination_dir.mkdir()
    conflicting = destination_dir / Path(relative_path).name
    conflicting.write_text("conflict", encoding="utf-8")

    result = runner.invoke(
        cli,
        ["mv", str(current_path), str(destination_dir), "--conflict-strategy", "skip", "--json"],
        env=env,
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["counts"]["moved"] == 0
    assert payload["counts"]["skipped"] == 1
    assert current_path.exists()
    assert conflicting.exists()


def test_cli_mv_updates_search_metadata(tmp_path: Path) -> None:
    """Chromadb metadata should reflect new paths after moving files."""

    root = tmp_path / "mv-search"
    root.mkdir()
    (root / "alpha.txt").write_text("alpha", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root), "--with-search"], env=env)
    assert org_result.exit_code == 0

    state_data = json.loads((root / ".dorgy" / "state.json").read_text(encoding="utf-8"))
    relative_path = next(iter(state_data["files"].keys()))
    document_id = state_data["files"][relative_path]["document_id"]
    source_path = (root / Path(relative_path)).resolve()
    destination = (root / "archive" / source_path.name).resolve()

    mv_result = runner.invoke(cli, ["mv", str(source_path), str(destination)], env=env)
    assert mv_result.exit_code == 0

    client = chromadb.PersistentClient(path=str(root / ".dorgy" / "chroma"))
    collection = client.get_collection(DEFAULT_COLLECTION_NAME)
    record = collection.get(ids=[document_id])
    assert record["ids"] == [document_id]
    metadata = record["metadatas"][0]
    assert metadata["path"].endswith(f"archive/{source_path.name}")
