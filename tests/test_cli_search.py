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
    env.setdefault("DORGY_USE_FALLBACKS", "1")
    env.setdefault(
        "DORGY__SEARCH__EMBEDDING_FUNCTION",
        "tests.fake_embeddings.simple_embedding_function",
    )
    return env


def test_cli_search_json_results(tmp_path: Path) -> None:
    """`dorgy search --json` should return structured results."""

    root = tmp_path / "collection"
    root.mkdir()
    (root / "alpha.txt").write_text("alpha", encoding="utf-8")
    (root / "beta.txt").write_text("beta", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root), "--with-search"], env=env)
    assert org_result.exit_code == 0

    search_result = runner.invoke(cli, ["search", str(root), "--json"], env=env)
    assert search_result.exit_code == 0

    payload = json.loads(search_result.output)
    assert payload["counts"]["total"] == 2
    assert payload["counts"]["matches"] == 2
    assert payload["counts"]["search_enabled"] in (True, False)
    relative_paths = {entry["relative_path"] for entry in payload["results"]}
    assert any(path.endswith("alpha.txt") for path in relative_paths)
    assert any(path.endswith("beta.txt") for path in relative_paths)
    for entry in payload["results"]:
        assert "document_id" in entry
        assert entry["score"] is None
        assert entry["snippet"] is None or isinstance(entry["snippet"], str)


def test_cli_search_filters_and_limits(tmp_path: Path) -> None:
    """Search filters (name/limit) should narrow results as expected."""

    root = tmp_path / "filtered"
    root.mkdir()
    (root / "alpha.txt").write_text("alpha", encoding="utf-8")
    (root / "notes.md").write_text("notes", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root), "--with-search"], env=env)
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
    assert name_payload["results"][0]["snippet"] is None or isinstance(
        name_payload["results"][0]["snippet"], str
    )

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
    assert limited_payload["results"][0]["document_id"]


def test_cli_search_text_summary(tmp_path: Path) -> None:
    """Text output should surface a summary line."""

    root = tmp_path / "text"
    root.mkdir()
    (root / "only.txt").write_text("content", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root), "--with-search"], env=env)
    assert org_result.exit_code == 0

    result = runner.invoke(cli, ["search", str(root)], env=env)
    assert result.exit_code == 0
    assert "Search summary for" in result.output


def test_cli_search_contains_requires_index(tmp_path: Path) -> None:
    """`--contains` should fail gracefully when no search index exists."""

    root = tmp_path / "no_index"
    root.mkdir()
    (root / "alpha.txt").write_text("alpha content", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    search_result = runner.invoke(
        cli,
        ["search", str(root), "--contains", "alpha"],
        env=env,
    )
    assert search_result.exit_code != 0
    assert "Search index is disabled" in search_result.output


def test_cli_search_contains_after_org(tmp_path: Path) -> None:
    """`--contains` should return matching documents when the index exists."""

    root = tmp_path / "contains"
    root.mkdir()
    (root / "alpha.txt").write_text("alpha apples", encoding="utf-8")
    (root / "beta.txt").write_text("beta bananas", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root), "--with-search"], env=env)
    assert org_result.exit_code == 0

    search_result = runner.invoke(
        cli,
        ["search", str(root), "--json", "--contains", "alpha"],
        env=env,
    )
    assert search_result.exit_code == 0

    payload = json.loads(search_result.output)
    assert payload["counts"]["matches"] == 1
    result_entry = payload["results"][0]
    assert result_entry["relative_path"].endswith("alpha.txt")
    assert result_entry["snippet"]


def test_cli_search_init_store_builds_index(tmp_path: Path) -> None:
    """`--init-store` should rebuild the index and allow semantic queries."""

    root = tmp_path / "init"
    root.mkdir()
    (root / "gamma.txt").write_text("gamma grapes", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    init_result = runner.invoke(
        cli,
        ["search", str(root), "--json", "--init-store", "--search", "gamma"],
        env=env,
    )
    assert init_result.exit_code == 0

    payload = json.loads(init_result.output)
    assert payload["counts"]["matches"] == 1
    assert payload["results"][0]["relative_path"].endswith("gamma.txt")
    notes = payload.get("notes", {})
    assert any("Indexed" in entry for entry in notes.get("info", []))


def test_cli_search_drop_store_disables_index(tmp_path: Path) -> None:
    """`--drop-store` should remove Chromadb artifacts and keep metadata search."""

    root = tmp_path / "drop"
    root.mkdir()
    (root / "delta.txt").write_text("delta", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root), "--with-search"], env=env)
    assert org_result.exit_code == 0

    drop_result = runner.invoke(
        cli,
        ["search", str(root), "--json", "--drop-store"],
        env=env,
    )
    assert drop_result.exit_code == 0

    payload = json.loads(drop_result.output)
    assert payload["counts"]["matches"] == 1
    assert payload["results"][0]["relative_path"].endswith("delta.txt")
    notes = payload.get("notes", {})
    assert any("dropped" in entry.lower() for entry in notes.get("info", []))


def test_cli_search_reindex_refreshes_content(tmp_path: Path) -> None:
    """`--reindex` should rebuild the index and refresh stored snippets."""

    root = tmp_path / "reindex"
    root.mkdir()
    target = root / "alpha.txt"
    target.write_text("original apples", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root), "--with-search"], env=env)
    assert org_result.exit_code == 0

    # Modify the file to force a reindex change.
    moved = root / "documents" / "alpha.txt"
    moved.write_text("updated bananas", encoding="utf-8")

    reindex_result = runner.invoke(
        cli,
        ["search", str(root), "--json", "--reindex"],
        env=env,
    )
    assert reindex_result.exit_code == 0
    payload = json.loads(reindex_result.output)
    assert payload["counts"]["matches"] >= 1
    notes = payload.get("notes", {}).get("info", [])
    assert any("Reindexed" in entry for entry in notes)

    semantic_result = runner.invoke(
        cli,
        ["search", str(root), "--json", "--search", "updated"],
        env=env,
    )
    assert semantic_result.exit_code == 0
    semantic_payload = json.loads(semantic_result.output)
    first = semantic_payload["results"][0]
    assert "updated bananas" in (first["snippet"] or "")
    assert first["score"] is not None


def test_cli_search_semantic_requires_index(tmp_path: Path) -> None:
    """Semantic search should warn when the vector index is unavailable."""

    root = tmp_path / "semantic_missing"
    root.mkdir()
    (root / "alpha.txt").write_text("alpha apples", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root)], env=env)
    assert org_result.exit_code == 0

    search_result = runner.invoke(
        cli,
        ["search", str(root), "--json", "--search", "alpha"],
        env=env,
    )
    assert search_result.exit_code != 0
    assert "Search index is disabled" in search_result.output


def test_cli_search_semantic_results(tmp_path: Path) -> None:
    """Semantic queries should return scored results when the index exists."""

    root = tmp_path / "semantic_ok"
    root.mkdir()
    (root / "alpha.txt").write_text("alpha apples", encoding="utf-8")
    (root / "beta.txt").write_text("beta bananas", encoding="utf-8")

    runner = CliRunner()
    env = _env_with_home(tmp_path)

    org_result = runner.invoke(cli, ["org", str(root), "--with-search"], env=env)
    assert org_result.exit_code == 0

    search_result = runner.invoke(
        cli,
        ["search", str(root), "--json", "--search", "alpha"],
        env=env,
    )
    assert search_result.exit_code == 0

    payload = json.loads(search_result.output)
    assert payload["counts"]["matches"] >= 1
    first = payload["results"][0]
    assert first["relative_path"].endswith("alpha.txt")
    assert first["score"] is not None
    assert first["snippet"]
