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
   - Provide flags: `--recursive`, `--output`, `--debounce`, `--json`, `--prompt`, `--once` (process and exit) for testing.
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


