# Implementation Plan

1. Phase 0 – Project Foundations: scaffold a dorgy Python package with Click entrypoint, pyproject.toml configured for uv, docstring-based CLI help, and baseline AGENTS/README updates describing automation hooks.
2. Phase 1 – Config & State: implement config loader/editor targeting ~/.dorgy/config.yaml with Pydantic models, default generation, override cascade (CLI flags → env vars → file), and read/write helpers used across commands.
3. Phase 2 – Content Ingestion Pipeline: build pluggable file discovery that respects recursion, size filters, symlinks, and hidden/locked handling; integrate python-magic, Pillow, and docling adapters to produce normalized FileDescriptor objects with previews, metadata, hashes, and error channels (needs-review, quarantine).
4. Phase 3 – LLM & DSPy Integration: wrap DSPy signatures into a dorgyanizer module with provider-agnostic LLM client, prompt templating, fallback heuristics for low-confidence outputs, and caching of inference results in .dorgy/chroma; ensure deterministic dry-run JSON formats.
5. Phase 4 – Organization Engine: create orchestrator that batches descriptors, calls classifier/renamer/structure modules, resolves naming conflicts, preserves timestamps, writes .dorgy state (orig.json, logs, quarantine), and supports --dry-run, --json, --output, and rollback on errors.
6. Phase 4.5 – CLI Polish & UX (new)
   - Provide richer feedback across CLI commands (summaries, consistent color/wording, optional quiet mode).
   - Align JSON/text outputs and expose additional flags (`org` execution JSON, adjustable history limits).
   - Harden error handling with actionable `click.ClickException` messages and structured JSON errors.
   - Expand tests/documentation to cover new UX, ensuring README examples stay accurate.
7. Phase 5 – Watch Service: integrate watchdog observer with debounce and backoff, share pipeline with org, ensure concurrent-safe writes, and persist incremental metadata updates while honoring config for locked/corrupted files.
8. Phase 6 – CLI Surface: deliver watch, search, mv commands with Rich/TQDM feedback and consistent option parsing.
9. Phase 7 – Search & Metadata APIs: use chromadb collections to power semantic and tag/date filters, maintain FileRecord index on each organization run, and update entries when mv executes (with validation of destination).
10. Phase 8 – Testing & Tooling: configure uv pip compile lock, add pre-commit (formatting, lint, import sort, pytest), implement unit/integration tests for pipeline stages and CLI workflows (including dry-run/undo), and document automation expectations in AGENTS plus SPEC alignment updates.

## Phase 4.5 – CLI Polish & UX Scope

1. Command Output Consistency
   - Harmonize summary lines across `org`, `undo`, `status`, and future commands (consistent color, punctuation, pluralization).
   - Introduce optional `--quiet/--summary` toggles to reduce noise for scripting.
   - Ensure `org` reports destination root (especially when `--output` is used) and includes counts of renames/moves/conflicts in both text and JSON.

2. JSON/Automation Enhancements
   - Extend `org` execution path to support `--json` output mirroring dry-run payloads (final plan, state changes, history entry).
   - Add JSON modes to other inspection commands as needed (e.g., `status --json` already implemented; revisit `search` and future commands).
   - Standardize JSON error responses (e.g., `{"error": {"code": "...", "message": "...", "details": ...}}`).

3. Error Handling Improvements
   - Audit `click.ClickException` messaging for clarity and remediation hints (missing state, malformed history/snapshot, permission issues).
   - Ensure structured JSON is returned when JSON flags are provided, even on failure (non-zero exit code with payload).
   - Add validation for mutually exclusive flags or unsupported combinations with helpful errors.

4. Configuration Integration
   - Allow CLI options (e.g., `--history`, `--quiet`, potential future defaults) to fall back to configuration or env variables.
   - Document new config keys in `SPEC.md`/`README.md`, update `ConfigManager` tests if defaults change.

5. Testing & Documentation
   - Expand CLI integration tests to cover new flags, quiet/summary modes, JSON error cases, and polished messaging.
   - Update README “Current CLI Highlights” and examples to reflect refined outputs/flags.
   - Note coordination expectations in `AGENTS.md` for consistent CLI UX and shared helper functions.

## Risks & Open Questions
- Need to balance richer output with backwards compatibility for existing scripts (decide default verbosity carefully).
- JSON schema stability considerations for future tooling integration; may want to formalize schemas or versioning.
- Additional flags/config may require reconciliation with upcoming watch/mv implementations.

## Next Steps
- Kick off Phase 5 watch service work on `feature/phase-5-watch`, focusing on event debouncing and safe reuse of the ingestion/organization pipeline.
- Extend the polished CLI UX (summary helpers, JSON payloads, config defaults) to upcoming commands (`watch`, `mv`, `search`) as they come online.
- Continue updating documentation/tests alongside new automation entry points to preserve deterministic behaviour before broader CLI rollout.

## Phase 5 – Watch Service Implementation Plan

### Goals
- Continuously monitor one or more directories for new/modified files and feed them through the ingestion → classification → organization pipeline.
- Respect existing config toggles (hidden files, size limits, locked/corrupted policies, rename settings, ambiguity thresholds).
- Ensure concurrent runs are safe: avoid duplicate processing, stage operations atomically (reuse executor staging), and handle transient errors with backoff.
- Provide CLI ergonomics mirroring `dorgy org` (dry-run, JSON preview, prompt injection, output relocation); allow per-run overrides.
- Persist incremental state updates so the collection remains consistent (history, snapshots, state.json) after each batch.

### Milestones
1. **Scaffolding & Configuration**
   - Add `watch` options to config defaults (`processing.watch` section for debounce/backoff).
   - Update `SPEC.md`/`README.md` to surface watch expectations; add AGENT guidance.
   - Create `feature/phase-5-watch` branch.

2. **File System Monitoring Layer**
   - Integrate `watchdog` observer with handlers for `created`/`modified` events (skip deletes for MVP).
   - Implement debounce/coalescing to batch events (e.g., configurable interval).
   - Respect recursion toggle and filters from config; reuse `DirectoryScanner` for initial priming if necessary.

3. **Pipeline Reuse & Task Scheduling**
   - Adapt ingestion pipeline to accept incremental file lists; consider staging directories for locked files as in Phase 4.
   - Reuse classification cache and organization planner/executor; ensure copy-mode works when `--output` is supplied.
   - Implement a work queue/async loop to serialize organization runs (prevent overlapping plans).

4. **CLI Command (`dorgy watch`)**
   - Provide flags: `--recursive`, `--output`, `--debounce`, `--json`, `--classify-prompt`, `--structure-prompt`, `--once` (process and exit) for testing.
   - Support dry-run mode (log what would be processed without applying changes).
   - Show live feedback (Rich progress or summaries) and log to `.dorgy/watch.log`.

5. **State Persistence & Resilience**
   - After each batch, update `state.json`, append history entries, refresh snapshots (consider incremental strategy to avoid large snapshots each time).
   - Handle exceptions gracefully (retry with exponential backoff, skip problematic files with clear errors).
   - Ensure graceful shutdown (flush pending events, close observer).

6. **Testing & Tooling**
   - Unit tests for debounce logic, queue processing, and configuration adapters.
   - Integration tests using temp directories and synthetic watchdog events (pytest watchdog fixtures or manual triggers).
   - Document testing strategy for real file system events (manual checklist for QA).

### Risks & Open Questions
- Long-running observer resource management (threading, signal handling) within CLI execution.
- Interaction with DSPy classification latency; may need worker threads or async pipeline to avoid blocking event loop.
- Snapshot size growth with frequent runs; consider incremental metadata or periodic pruning.
- Windows/macOS path handling and watchdog compatibility.
- Coordination with future Phase 6 CLI polish (ensure watch command aligns with quiet/JSON options planned in Phase 4.5).

### Next Steps
- Finalize configuration schema updates and planning details in `SPEC.md`.
- Kick off implementation on `feature/phase-5-watch`, prioritizing configuration + monitoring scaffolding.
- Schedule follow-up checkpoints for pipeline integration and CLI wiring.

## Phase 5.5 – Watch Deletions & External Moves

### Goals
- Detect `deleted` and `moved` events leaving the collection and treat them as removals in state/history.
- Differentiate between moves within the collection (rename/update state) and those exiting the watched roots.
- Provide opt-in safeguards (config/CLI) so destructive actions are explicit, auditable, and undo-aware.
- Maintain JSON/summary parity with existing CLI output, reflecting deletion counts and error details.

### Milestones
1. **Event Taxonomy & Queue Plumbing**
   - Extend `_WatchEventHandler` to capture delete/move events with both source/destination paths.
   - Introduce a lightweight event model carrying `kind`, `src`, `dest`, and timestamps; update batching logic to group by root.
   - Flag candidates that no longer exist or whose destinations are outside the root as removals before ingestion.

2. **Planner & Executor Enhancements**
   - Add `DeleteOperation` (and optional `MoveOperation` link) to organization models with serialization and history notes.
   - Teach watch batch processing to emit delete operations (no ingestion/classification needed).
   - Update `OperationExecutor`/state repo helpers so deletes drop `CollectionState` entries, append history events, and log tombstones.
   - Ensure undo logic either reconstructs deletes from snapshots or clearly reports non-restorable operations.

3. **CLI & Configuration**
   - Introduce `processing.watch.allow_deletions` (default `false`) plus `--allow-deletions` flag to opt into destructive behavior.
   - Expand `_emit_watch_batch` summaries/JSON schema with `deleted` counts and removal metadata.
   - Emit actionable warnings in dry-run or when deletions are suppressed due to config.

4. **Testing & Documentation**
   - Add integration tests covering: delete, move-out, move-within, and rename scenarios (dry-run + destructive paths).
   - Create targeted unit tests for `DeleteOperation`, history writes, and state persistence.
   - Document workflow changes in README/SPEC, update AGENTS (watch + organization) with coordination notes, and capture safeguards in STATUS/IMPL logs.

### Risks & Safeguards
- Permanent deletion without recycle-bin integration; mitigate via config defaults, dry-run previews, and explicit confirmations.
- Concurrency race conditions if files fluctuate during batching; rely on snapshot metadata and conservative error handling.
- JSON consumers must tolerate new fields; version schema expectations in docs.

### Next Steps
- Prototype event classification (delete vs. internal move) with unit coverage.
- Sketch `DeleteOperation` data model and extend executor/history flows.
- Draft CLI UX (flags/messages) and circulate for review before wiring destructive behavior.


## Phase 5.8 – Vision-Enriched Classification

### Objectives
- Deliver multimodal understanding so image-heavy collections benefit from captions, tags, and richer reasoning instead of MIME-only heuristics.
- Respect `processing.process_images` and allow automation to opt-in/out at runtime while keeping ingestion/watch pipelines deterministic when vision is disabled.
- Minimize duplicate inference cost by caching caption/tag payloads and reusing them across organization runs and watch batches.

### Scope & Milestones
1. **Vision Provider Integration**
   - Implement a `VisionCaptioner` DSPy module that declares a signature using `dspy.Image` inputs and reuses the configured `llm` provider/model; surface informative errors if the model does not support vision.
   - Add rate-limit/backoff handling plus structured error reporting so vision failures degrade gracefully.

2. **Ingestion Pipeline Updates**
   - When `process_images` is true and the mime is `image/*`, invoke the DSPy captioner (passing along user prompts) to obtain a caption + key labels; persist results on the `FileDescriptor` (`preview`, `tags`, and `metadata["vision_caption"]`/`["vision_labels"]`).
   - Store vision outputs in the classification cache keyed by content hash and reuse them for subsequent runs (ingestion and watch).
   - Capture timing/skip reasons in debug logs and expose suppressed vision work in dry-run/JSON outputs for auditability.

3. **Classification & Organization Enhancements**
   - Update DSPy prompt assembly to include caption/labels snippets, and refresh fallback heuristics to leverage the additional tags.
   - Adjust structure planner payloads so tree proposals can group images based on captions/categories.
   - Add regression tests ensuring both DSPy and fallback flows produce richer categories for representative image fixtures.

4. **Documentation & Coordination**
   - Document configuration prerequisites and provider-specific considerations in SPEC Phase 5.8, README, and AGENTS (classification + ingestion).
   - Update CLI help/flags to mention vision behaviour and provide guidance when the feature is disabled.
   - Note ongoing tasks, blockers, and automation touchpoints in `notes/STATUS.md` during implementation.

### Dependencies & Sequencing
- Requires classification cache schema adjustments; coordinate with any concurrent cache work to avoid conflicts.
- Lean on existing ingestion extractors and watch batching infrastructure (Phase 5/5.5) to schedule caption jobs.
- DSPy program updates must follow any prompt/template refactors from Phase 3 to prevent regressions.

### Risks & Mitigations
- **Inference Cost/Latency:** Batch caption requests where providers allow and honour user-specified limits; log skip reasons for transparency.
- **Provider Capability Drift:** Encapsulate prompt/response parsing per adapter with fixtures so upgrades require minimal changes.
- **Security/Privacy:** Provide configuration/CLI switches to fully disable remote vision calls; log when files are skipped due to policy.
- **Cache Staleness:** Include hash + model/version metadata in cache entries and invalidate when models change.

### Success Criteria
- Enabling `processing.process_images` yields human-readable captions and labels stored on descriptors and visible in CLI/JSON outputs, produced via the DSPy image signature with user prompts applied when provided.
- Classification decisions for images reference caption content (tags, reasoning) and tests verify improved categorization vs. pre-vision baselines.
- Watch and re-run flows reuse cached captions without redundant provider calls, with metrics confirming cache hits.
- Documentation clearly communicates configuration, limitations, and troubleshooting steps for the vision pipeline.


## Phase 6 – CLI Surface Implementation Plan

### Objectives
- Expose a cohesive CLI that covers day-to-day workflows (`org`, `watch`, `search`, `mv`, `status`, `undo`, `config`) with consistent option parsing, shared output helpers, and JSON/quiet/summary parity.
- Ensure commands operate on per-collection state without requiring manual `.dorgy` inspection, and provide actionable errors when prerequisites (state, config, LLM availability) are missing.
- Establish reusable CLI tooling (context managers, decorators, prompt helpers) so subsequent phases can plug in additional functionality without duplicating boilerplate.

### Scope & Milestones
1. **Command Baseline & Option Harmonization**
   - Audit existing command signatures; align short/long flags (`--json`, `--quiet`, `--summary`, `--dry-run`, `--output`) and ensure help text follows the shared conventions.
   - Introduce a `dorgy.cli_options` module housing reusable Click option factories and validation helpers (mutually exclusive flags, path resolution, config fallbacks).
   - Update command docstrings/help examples to reflect the standard flag set.

2. **`dorgy search` Implementation**
   - Deliver read-only search that queries the existing `.dorgy/state.json` (Phase 7 will swap in semantic index).
   - Support filters for filename glob, tags, categories, needs-review, and modified date range.
   - Provide paginated/limited output with `--json`, `--summary`, and default Rich table rendering (fallback to plain text if Rich unavailable).
   - Add integration tests covering empty state, basic matches, combined filters, and JSON output.

3. **`dorgy mv` Implementation**
   - Implement move/rename command that updates the filesystem, state records, and history using the organization executor.
   - Support `--dry-run`, `--json`, conflict strategies (reusing organization planner logic), and validation for cross-collection moves.
   - Ensure undo entries capture mv operations, and CLI prompts highlight irreversible actions when targeting outside the collection.
   - Test cases: rename within collection, move to new folder, conflict resolution, invalid targets.

4. **Progress & Status Enhancements**
   - Wire Rich/TQDM progress bars for long-running `org` and `watch --once` operations (configurable via verbosity/quiet flags).
   - Surface command summaries back through the existing `_emit_message` helpers while respecting quiet/summary defaults.
   - Extend watch JSON payload schema/documentation to include progress timestamps and batch identifiers consumed by future automation.
   - Add debug-level timing instrumentation around classification calls to highlight slow provider responses.

5. **Configuration & Defaults**
   - Expand config schema with CLI defaults relevant to Phase 6 (e.g., `cli.move_conflict_strategy`, `cli.search_default_limit`, `cli.progress_enabled`).
   - Update `ConfigManager` precedence tests and README/SPEC documentation to describe new keys.
   - Ensure `flatten_for_env` exposes new settings and CLI commands respect them via shared option factories.
   - Introduce `processing.parallel_workers` so ingestion and classification can scale concurrency when providers and hardware allow.

6. **Documentation & Coordination**
   - Refresh README “Current CLI Highlights” with examples for `search` and `mv`, including JSON and quiet invocations.
   - Add or update AGENTS.md entries for CLI modules describing shared helpers, option factories, and progress UI expectations.
   - Capture implementation notes and dependencies in `notes/STATUS.md` after each working session.

### Deliverables
- Updated CLI package with standardized options/utilities and implemented `search`/`mv`.
- New/updated tests: CLI integration (`tests/test_cli.py`, `tests/test_cli_search.py`, `tests/test_cli_mv.py`), unit tests for option helpers, config tests for new defaults.
- Documentation updates across README, SPEC Phase 6 section, and AGENTS files.
- Progress instrumentation (Rich/TQDM) behind configuration toggles.

### Dependencies & Sequencing
- Requires Phase 5.5 deletions work merged (state/history schema) to avoid conflicts while adding move logic.
- Search relies on the structure of `.dorgy/state.json`; any schema adjustments must land before semantic indexing (Phase 7).
- Progress feedback hooks should reuse output helpers introduced in Phase 4.5; ensure any new Rich dependencies are optional and documented.

### Risks & Mitigations
- **CLI Option Drift:** Shared option factories reduce duplication; add unit tests that assert option signatures across commands.
- **State Corruption via `mv`:** Reuse existing executor/history pipeline with thorough tests; guard against cross-device moves with explicit error messaging.
- **Progress UI Failures in Headless Environments:** Detect Rich availability and terminal capabilities, falling back to plain text with a warning.
- **Config Backwards Compatibility:** Default new config keys to no-op values (e.g., `progress_enabled: true`) and log warnings rather than failing when unset.

### Success Criteria
- Running `uv run dorgy --help` lists all primary commands with cohesive help text and consistent flags.
- `dorgy search` and `dorgy mv` operate end-to-end (filesystem + state/history) with passing integration tests and documented examples.
- Progress indicators appear for long-running operations when supported, and can be disabled via config/flags.
- Documentation (README, SPEC Phase 6, AGENTS) accurately reflects the CLI surface and configuration knobs.

## Phase 7 – Search & Metadata APIs Implementation Plan

### Objectives
- Introduce a persistent metadata/search service powered by ChromaDB so collections support semantic, tag, and temporal queries beyond the existing state JSON.
- Keep the CLI surface cohesive by extending `dorgy search` and related commands to leverage the new index while preserving backward-compatible JSON schemas.
- Ensure metadata updates propagate across organization, watch, and manual moves so the search index stays consistent without manual rebuilds.

### Scope & Milestones
1. **Indexing Foundations**
   - Add a ChromaDB client wrapper (`dorgy.search`) with configuration (path, embedding model, batch size).
   - Extend ingestion/organization workflows to upsert descriptors into the index (text content, tags, categories, hashes, timestamps).
   - Persist index metadata per collection (e.g., `.dorgy/index/manifest.json`) and document repository lifecycle (create, compact, rebuild).

2. **Search CLI Enhancements**
   - Update `dorgy search` to hit the vector index for semantic queries while supporting hybrid filters (tags, categories, time, needs-review).
   - Add `--reindex` and `--refresh` maintenance commands to rebuild or sync the index when files change outside Dorgy.
   - Emit enriched JSON payloads (scores, matched metadata) and expand tests covering semantic vs. lexical searches.

3. **Metadata Synchronization**
   - Wire watch service and `dorgy mv` to update/remap index entries on renames, moves, deletions; ensure suppressed operations log reconciliation notes.
   - Backfill existing collections by reading `.dorgy/state.json` and replaying history; expose `dorgy search sync` helper for automation.
   - Guard against stale entries by tracking hash/version fields and pruning missing files during maintenance.

4. **Developer Experience & Observability**
   - Provide debug logging/timing for indexing stages similar to ingestion/classification progress.
   - Document environment requirements (Chroma models, embeddings) and surface configuration defaults in README/SPEC/AGENTS.
   - Add regression tests asserting index consistency after organization runs, watch batches, and manual moves.

### Risks & Mitigations
- **Large collections**: Use batched upserts and configurable limits to avoid memory spikes; document tuning options.
- **Search quality drift**: Allow swapping embedding providers via config and add sanity tests using fixtures.
- **Index corruption**: Implement manifest checksums and provide rebuild commands with clear CLI prompts.

### Success Criteria
- `dorgy search` returns semantic results (with scores) alongside existing filter support and passes new integration tests.
- Watch and organization flows update the ChromaDB index without manual intervention; index manifests remain in sync with `.dorgy/state.json`.
- Documentation (README, SPEC Phase 7, AGENTS) covers index configuration, maintenance commands, and automation expectations.
