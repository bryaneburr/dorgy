# WATCH SERVICE COORDINATION NOTES

- `WatchService` reuses the ingestion → classification → organization flow; avoid bypassing these helpers when adding new triggers.
- Batches write incremental updates to `.dorgy/state.json`, `.dorgy/history.jsonl`, and `.dorgy/watch.log`; keep these side effects in sync with `dorgy org` when extending behaviour.
- Debounce, batch sizing, and error backoff honour `processing.watch` configuration—extend the Pydantic model/tests whenever new tuning knobs are introduced.
- Event handling now flows through `WatchEvent` instances; deletions/moves produce `DeleteOperation` entries with `kind` metadata that must be persisted to state, history, JSON payloads, and watch logs.
- Destructive removals stay disabled unless `processing.watch.allow_deletions` or `--allow-deletions` is set—keep suppression notes/JSON fields (`suppressed_deletions`, `removals`) accurate when tweaking behaviour.
- CLI integrations should go through `WatchService.process_once`/`WatchService.watch` and render output with the shared CLI helpers (`_emit_watch_batch`, JSON payload schema) to preserve UX consistency.
- Watch tests live in `tests/test_cli_watch.py`; add service-level unit tests there when adding new batching behaviours or failure handling.
- Honour `dorgy.shutdown` by polling the shared shutdown event inside long-running loops so Ctrl+C/SIGTERM winds down observers, queues, and worker pools without leaking resources.
