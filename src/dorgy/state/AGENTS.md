# STATE COORDINATION NOTES

- `StateRepository` owns persistence under `.dorgy/`; avoid manual file writes to state directories outside this module.
- Consumers should treat `StateError`/`MissingStateError` as recoverable and surface actionable messaging to users.
- When new metadata needs to be tracked, extend `CollectionState`/`FileRecord` models with timezone-aware fields; update serialization tests in `tests/test_state_repository.py` accordingly.
- Keep undo/original-structure logic centralized here; other modules should call repository helpers rather than touching `orig.json` directly.
- Operation history is persisted via `append_history` in `.dorgy/history.jsonl`; supply `OperationEvent` entries from the organization executor so automations can replay or audit changes.
- `write_original_structure` expects a payload with `generated_at` + `entries` (each entry containing `path`, `display_name`, `mime_type`, `hash`, `size_bytes`, `tags`); keep this schema stable unless CLI/tests are updated in tandem.
