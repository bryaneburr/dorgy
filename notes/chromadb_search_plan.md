# Chromadb Search Integration Plan

## Overview & Store Location
- Deliver Chromadb-backed search that runs per collection and stores data **inside that collection’s `.dorgy` directory** (`<collection>/.dorgy/chroma`). No artifacts belong in the global `~/.dorgy` config directory so collections remain self-contained and portable.
- Keep state (`state.json`), CLI outputs, and automation JSON in sync while extending existing pipelines (org/watch/mv/search) rather than introducing ad-hoc flows.

## Work Breakdown

### 1. Document Identity & State Schema
- Extend `FileRecord` with a persistent `document_id: str` plus an optional `search` metadata block on `CollectionState` (fields such as `enabled`, `version`, `last_indexed_at`).
- Teach `StateRepository.load/save` to backfill IDs for older records (assign `uuid4().hex` when missing), persist search metadata, and ensure timestamps remain timezone-aware.
- Update every path that builds or mutates `FileRecord` entries (`descriptor_to_record`, `org`, `watch`, `mv`, undo/status) so IDs flow through renames, moves, and re-org runs.
- Add unit tests confirming IDs survive `dorgy mv` and watch deletions, plus repository tests covering auto-migration.

### 2. Search Text Extraction Pipeline
- Confirm Docling previews already output flattened text; when available, capture markdown/plaintext variants (e.g., `export_to_markdown`) and attach normalized text to descriptors via a helper (sanitize control chars, enforce preview limit).
- For non-text files use vision captions/descriptions (`metadata["vision_caption"]`, labels) so we always have meaningful content.
- Centralize normalization in a helper (new module or `cli_support`) so both org and watch reuse identical search payloads; update ingestion tests to cover metadata additions.

### 3. Search Index Infrastructure (Per-Collection `.dorgy/chroma`)
- Introduce `dorgy.search.index.SearchIndex` that wraps `chromadb.PersistentClient(path=<collection>/.dorgy/chroma)` using a threading lock for safety.
- Responsibilities: create/drop the local store, expose `status()`, batch `upsert` using `document_id` as the Chromadb ID, store normalized documents plus metadata (relative path, tags, categories, mime, timestamps, needs_review), and delete entries when files are removed.
- Keep a small manifest (e.g., `.dorgy/search.json`) with version/doc counts to help CLI checks. Handle missing Chromadb gracefully by surfacing actionable errors.
- Support lexical filters by using `where_document={"$contains": ...}` and leave embeddings generation pluggable; if we add custom embedding functions later, wire them through config.

### 4. Lifecycle Controls & Pipeline Integration
- Config: add `search` options (e.g., `auto_enable_org`, `auto_enable_watch`, `default_limit`, `embedding_function`) to `dorgy.config.models` plus docs/env vars.
- CLI flags:
  - `dorgy org`: `--with-search/--without-search` toggles. When search is enabled (flag or state), build/update the Chromadb store right after saving state. Copy-mode writes index under the destination collection’s `.dorgy`.
  - `dorgy watch`: `--with-search` opt-in, but also auto-detect existing search state and keep it updated. Watch batches call `SearchIndex.upsert` for processed files and `delete` when `allow_deletions` removes items.
  - `dorgy mv`: after state/history updates, call into the index to update metadata (no embedding recompute) so queries still resolve the renamed path.
- Provide helper utilities (`dorgy.search.lifecycle.ensure_index()`, `update_entries()`, `drop_index()`) so org/watch/mv share code and keep `.dorgy/chroma` authoritative per collection.
- Status: org + watch + mv reuse the lifecycle helpers; next up are `dorgy search --init-store/--drop-store` plumbing and Chromadb-backed query flags.

### 5. Search Command Enhancements
- `dorgy search` should fail fast with a friendly message when `state.search.enabled` is false or `.dorgy/chroma` is missing, guiding users to initialize search via `dorgy org --with-search` or `dorgy search --init-store`.
- Add CLI options:
  - `--contains TEXT` for substring queries (`where_document={"$contains": TEXT}`), combinable with semantic `--search`.
  - `--init-store` to (re)create the index from existing state without re-running org; uses ingestion/metadata extraction to regenerate previews before upserting.
  - `--drop-store` to delete `.dorgy/chroma`/`search.json` and mark state as search-disabled.
  - Potential `--reindex` convenience to rebuild the store in-place.
- Use Chromadb `collection.query` for semantic lookups, merging results with state metadata for display. Push tag/category filters into `where` clauses (store normalized lists in metadata) and keep existing CLI filtering semantics for safety.
- Enrich JSON/table outputs with `document_id`, similarity `score`, and a short snippet from the stored document text; respect `--json`, `--summary`, and `--quiet`.
- ✅ `--contains`, `--init-store`, `--reindex`, and `--drop-store` now share the lifecycle helpers so substring search works even after a standalone rebuild. Search indexing is enabled by default during `org`/`watch` runs (use `--without-search` to skip), friendly errors guide users to initialize when disabled, and JSON/table outputs surface `document_id`, optional scores, distances, spaces, and document snippets for automation.
- ✅ The CLI now refuses to run when search is disabled, directing operators to `dorgy search --init-store` / `dorgy org --with-search` before executing substring or semantic queries.
- 🔜 Wire semantic queries via `collection.query`: ensure embeddings are generated during indexing, return similarity scores in CLI/JSON output, and instruct users to initialize the vector store when embeddings are unavailable.

### 6. Store Creation/Deletion UX
- Ensure initialization always targets `<collection>/.dorgy/chroma` and never global paths. Provide clear console messages indicating the exact directory.
- When dropping a store, remove the directory (best-effort), update `state.search`, and warn that watch/org runs will skip index updates until reenabling.
- Guard destructive operations with confirmations or `--force` when run interactively.

### 7. Tests, Docs, and Coordination
- Tests: new unit coverage for `SearchIndex`, ingestion payload helpers, CLI flows (`tests/test_cli_org.py`, `tests/test_cli_watch.py`, `tests/test_cli_search.py`, `tests/test_cli_mv.py`) covering search enablement, contains queries, deletions, and friendly errors when search is disabled.
- Documentation: refresh `README.md`, `ARCH.md`, `SPEC.md` (Phase 7 status + `.dorgy/chroma` layout), root and module-level `AGENTS.md` files, and add Google-style docstrings for new modules.
- Notes: append session summary to `notes/STATUS.md` when implementation wraps, capturing blockers/next steps for search rollout.
- Tooling: manage dependencies via `uv` (update `pyproject.toml`/`uv.lock`), and extend CI/pre-commit tests if new modules require dedicated checks.
- ✅ Added CLI/Chromadb tests for `--contains`/`--init-store`/`--drop-store`, refreshed README/ARCH/SPEC/search AGENTS guidance, and logged the progress snapshot plus semantic-query coverage and the stricter “index required” behaviour.

With the per-collection `.dorgy/chroma` constraint explicit, this plan keeps Chromadb indexing aligned with Dorgy’s existing architecture and automation expectations.
