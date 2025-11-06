# Extending the Pipeline

- Prefer calling `load_config()`/`ensure_config()` for configuration needs; avoid reading files directly.
- Preserve `document_id`s and update `state.search` consistently.
- When modifying move/rename behavior, ensure Chromadb metadata refresh occurs without re-embedding.
- Respect `processing.preview_char_limit` and caches (`classifications.json`, `vision.json`).
- Keep `.dorgy/search.json` manifests accurate and propagate Chromadb warnings via CLI notes.

See `src/dorgy/config/AGENTS.md` and `SPEC.md` for expectations and defaults.
