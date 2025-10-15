# INGESTION COORDINATION NOTES

- Discovery, detection, hashing, and extraction should flow through `IngestionPipeline`; avoid bypassing scanner/detector/extractor components.
- Respect configuration-driven filters (hidden files, sizes, symlinks) by wiring `DirectoryScanner` parameters from `ConfigManager` when integrating with CLI commands.
- Expensive IO/LLM hand-offs belong after ingestion; keep this package focused on fast metadata extraction and flagging (`needs_review`, `quarantined`).
- Update/add tests in `tests/test_ingestion_pipeline.py` when extending pipeline behaviors or adding new adapters to ensure deterministic previews/metadata.
- Locked file policies (`copy|skip|wait`) and corrupted handling (`quarantine|skip`) are implemented inside `IngestionPipeline`; if you change these semantics, update staging/quarantine interactions and CLI tests.
