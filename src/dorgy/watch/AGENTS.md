# WATCH SERVICE COORDINATION NOTES

- `WatchService` reuses the ingestion → classification → organization flow; avoid bypassing these helpers when adding new triggers.
- Batches write incremental updates to `.dorgy/state.json`, `.dorgy/history.jsonl`, and `.dorgy/watch.log`; keep these side effects in sync with `dorgy org` when extending behaviour.
- Debounce, batch sizing, and error backoff honour `processing.watch` configuration—extend the Pydantic model/tests whenever new tuning knobs are introduced.
- CLI integrations should go through `WatchService.process_once`/`WatchService.watch` and render output with the shared CLI helpers (`_emit_watch_batch`, JSON payload schema) to preserve UX consistency.
- Watch tests live in `tests/test_cli_watch.py`; add service-level unit tests there when adding new batching behaviours or failure handling.
