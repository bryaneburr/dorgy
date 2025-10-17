"""CLI integration tests for `dorgy search`."""

from __future__ import annotations

import json
import os
from pathlib import Path

from click.testing import CliRunner

from dorgy.cli import cli


def _env_with_home(tmp_path: Path) -> dict[str, str]:
    """Return environment variables pointing HOME to a temp directory."""

    env = dict(os.environ)
    env["HOME"] = str(tmp_path / "home")
    return env


def test_cli_search_json_results(tmp_path: Path) -> None:
    """`dorgy search --json` should return structured results."""

    root = tmp_path / "collection"
    root.mkdir()
    (root / "alpha.txt").write_text("alpha", encoding="utf-8")
    (root / "beta.txt").write_text("beta", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    search_result = runner.invoke(cli, ["search", str(root), "--json"], env=env)
    assert search_result.exit_code == 0

    payload = json.loads(search_result.output)
    assert payload["counts"]["total"] == 2
    assert payload["counts"]["matches"] == 2
    relative_paths = {entry["relative_path"] for entry in payload["results"]}
    assert any(path.endswith("alpha.txt") for path in relative_paths)
    assert any(path.endswith("beta.txt") for path in relative_paths)


def test_cli_search_filters_and_limits(tmp_path: Path) -> None:
    """Search filters (name/limit) should narrow results as expected."""

    root = tmp_path / "filtered"
    root.mkdir()
    (root / "alpha.txt").write_text("alpha", encoding="utf-8")
    (root / "notes.md").write_text("notes", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    name_result = runner.invoke(
        cli,
        ["search", str(root), "--json", "--name", "alpha*.txt"],
        env=env,
    )
    assert name_result.exit_code == 0
    name_payload = json.loads(name_result.output)
    assert name_payload["counts"]["matches"] == 1
    assert name_payload["results"][0]["relative_path"].endswith("alpha.txt")

    limited_result = runner.invoke(
        cli,
        ["search", str(root), "--json", "--limit", "1"],
        env=env,
    )
    assert limited_result.exit_code == 0
    limited_payload = json.loads(limited_result.output)
    assert limited_payload["counts"]["matches"] == 1
    assert limited_payload["counts"]["total"] == 2
    assert limited_payload["counts"]["truncated"] == 1


def test_cli_search_text_summary(tmp_path: Path) -> None:
    """Text output should surface a summary line."""

    root = tmp_path / "text"
    root.mkdir()
    (root / "only.txt").write_text("content", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    result = runner.invoke(cli, ["search", str(root)], env=env)
    assert result.exit_code == 0
    assert "Search summary for" in result.output
