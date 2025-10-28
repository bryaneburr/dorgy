# Phase 7 Search Progress Snapshot

- Org, watch, and mv flows continue to reuse the Chromadb lifecycle helpers. Search indexes are created on demand, manifests stay in sync, and metadata-only operations refresh existing entries without touching embeddings.
- `dorgy search` now exercises the full lifecycle: `--contains` issues Chromadb substring queries, `--init-store` rebuilds indexes from existing files (using ingestion+vision helpers), `--reindex` drops and fully rebuilds indexes in-place, `--drop-store` disables indexing cleanly, and both table/JSON outputs include `document_id`, `score`, and snippet fields. The command fails fast when search is disabled, guiding operators to initialize or re-enable the index before querying.
- Tests cover search-aware behaviours across org/watch/mv plus the new search flows (`tests/test_cli_org.py`, `tests/test_cli_watch.py`, `tests/test_cli_mv.py`, `tests/test_cli_search.py`, `tests/test_search_index.py`).
- Documentation, AGENTS notes, SPEC Phase 7, and the Chromadb plan have been refreshed with the latest CLI behaviour and lifecycle details.

## Work Remaining

1. Consider a `--reindex` wrapper for automation (full rebuild without filters) and decide whether to expose additional embedding metadata when available.
2. Monitor Chromadb telemetry changes (currently disabled by default) and document any follow-up controls if upstream behaviour shifts.
3. Continue running `uv run pytest` / `uv run pre-commit run --all-files` before promoting Phase 7 changes to `main`.

## Staged Files

- `src/dorgy/cli.py`
- `src/dorgy/search/AGENTS.md`
- `src/dorgy/search/__init__.py`
- `src/dorgy/search/index.py`
- `README.md`
- `ARCH.md`
- `SPEC.md`
- `notes/chromadb_search_plan.md`
- `tests/test_cli_search.py`
