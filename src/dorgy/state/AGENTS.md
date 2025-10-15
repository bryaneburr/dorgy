# STATE COORDINATION NOTES

- `StateRepository` owns persistence under `.dorgy/`; avoid manual file writes to state directories outside this module.
- Consumers should treat `StateError`/`MissingStateError` as recoverable and surface actionable messaging to users.
- When new metadata needs to be tracked, extend `CollectionState`/`FileRecord` models with timezone-aware fields; update serialization tests in `tests/test_state_repository.py` accordingly.
- Keep undo/original-structure logic centralized here; other modules should call repository helpers rather than touching `orig.json` directly.
