# On-Disk Layout

Organized collections store metadata under a hidden `.dorgy/` folder at the collection root:

- `.dorgy/state.json` — current collection metadata (paths, hashes, document IDs, search status).
- `.dorgy/history.jsonl` — append-only operation history for automation and audits.
- `.dorgy/chroma/` — Chromadb index storage for semantic search.
- `.dorgy/search.json` — manifest describing the search index (counts, timestamps, enablement flags).
- `.dorgy/classifications.json` — cached classification results.
- `.dorgy/vision.json` — cached image captions when vision is enabled.
- `.dorgy/quarantine/` — destination for corrupted files when configured.
- `.dorgy/needs-review/` — staging area for low-confidence classifications.
- `.dorgy/watch.log` — rolling log written by `dorgy watch` batches.
- `.dorgy/dorgy.log` — shared CLI log.
- `.dorgy/orig.json` — snapshot of the original file structure used by `dorgy undo`.

See SPEC.md for additional context and lifecycle rules.

