# INGESTION COORDINATION NOTES

- Discovery, detection, hashing, and extraction should flow through `IngestionPipeline`; avoid bypassing scanner/detector/extractor components.
- Respect configuration-driven filters (hidden files, sizes, symlinks) by wiring `DirectoryScanner` parameters from `ConfigManager` when integrating with CLI commands.
- Expensive IO/LLM hand-offs belong after ingestion; keep this package focused on fast metadata extraction and flagging (`needs_review`, `quarantined`).
- Update/add tests in `tests/test_ingestion_pipeline.py` when extending pipeline behaviors or adding new adapters to ensure deterministic previews/metadata.
- Locked file policies (`copy|skip|wait`) and corrupted handling (`quarantine|skip`) are implemented inside `IngestionPipeline`; if you change these semantics, update staging/quarantine interactions and CLI tests.
- Long-running ingestion stages must call `dorgy.shutdown.check_for_shutdown()` so Ctrl+C/SIGTERM can unwind worker pools without leaving staging artefacts; ensure new loops observe the shared shutdown event.
- `MetadataExtractor` accepts a `preview_char_limit` parameter that should be sourced from config (`processing.preview_char_limit`) so descriptors, watch batches, and classifiers share consistent context lengths; metadata always surfaces the effective limit under `preview_limit_characters`.
