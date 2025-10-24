# Dorgy Architecture

`dorgy` is an AI-assisted command line toolkit that keeps file collections organized by running ingestion, classification, and restructuring pipelines on demand or continuously. The project is structured so the CLI stays responsive, automation surfaces consistent JSON payloads, and long-running services reuse the same core components that power one-off runs.

## System Overview

- Runtime is anchored by `main.py` and `src/dorgy/__main__.py`, which forward to `dorgy.cli.main`. The CLI is implemented with Click and loads heavy dependencies lazily so startup remains fast even on large environments.
- Commands funnel through shared helpers that normalize quiet/summary/JSON modes, yielding identical human and machine-readable outputs across organization, watch, search, move, status, undo, and config operations.
- Core workflows revolve around a pipeline that discovers candidate files, extracts metadata, classifies items with DSPy-backed or heuristic models, plans renames/moves, executes them safely, and records state for auditing and undo.
- Persistent metadata and caches live in `.dorgy/` under each collection root, enabling reversible operations and incremental processing.

## Runtime Flow

### CLI Entry & Command Dispatch

`dorgy.cli` exposes a Click group (`cli()`) with subcommands such as `org`, `watch`, `search`, `mv`, `undo`, `status`, and the nested `config` group. The module maintains `_LAZY_ATTRS` alongside `__getattr__`/`_load_dependency` to import heavyweight modules (classification, ingestion, watch, organization, state) only when a command actually needs them. UI behaviour (progress bars, summary lines, shared errors, JSON payloads) funnels through helpers so adding new commands automatically benefits from consistent UX.

### Organization & Watch Pipeline

1. **Configuration resolution** &mdash; `ConfigManager` loads defaults, file overrides, environment variables (`DORGY__*`), and CLI overrides via `resolve_with_precedence`. CLI mode flags (quiet/summary/JSON) are normalized through `resolve_mode_settings`.
2. **Ingestion** &mdash; `IngestionPipeline` wires `DirectoryScanner`, `TypeDetector`, `HashComputer`, and `MetadataExtractor` (plus optional `VisionCaptioner`) to enumerate files, capture metadata/preview text (capped by the configurable `processing.preview_char_limit`, default 2048, and recorded as `preview_limit_characters`), compute hashes, and emit structured descriptors. Stage callbacks drive progress output.
3. **Classification** &mdash; `ClassificationEngine` evaluates descriptors. When DSPy/models are available it invokes structured programs; otherwise it falls back to heuristics. Results are cached via `ClassificationCache`, and image captions use `VisionCache`. Prompt overrides travel through CLI options or prompt files and flow into the structure planner so folder proposals respect the same guidance. Needs-review routing compares the returned confidence against `ambiguity.confidence_threshold` (default 0.60) so automation can triage low-certainty decisions.
4. **Structure planning** &mdash; `StructurePlanner` suggests destination folders, while `OrganizerPlanner` turns classifications into `OperationPlan` instances containing renames, moves, metadata updates, and planner notes. Conflict strategies (`append_number`, `timestamp`, `skip`) are honored per config.
5. **Execution** &mdash; `OperationExecutor` stages files into `.dorgy/staging`, applies renames/moves (copy mode supported), emits `OperationEvent`s, and rolls back on failure. Delete operations generated during watch runs are gated by `processing.watch.allow_deletions`/`--allow-deletions`.
6. **State persistence & outputs** &mdash; `StateRepository` updates `state.json`, appends to `history.jsonl`, refreshes needs-review/quarantine directories, and stores original snapshots for undo. CLI helpers format rich tables, progress, summary lines, and standardized JSON payloads (`collect_error_payload`, `_handle_cli_error`, `_emit_watch_batch`, etc.).

### State-Oriented Commands

`status`, `search`, `mv`, and `undo` operate on stored `CollectionState`. Searches apply filters across tags/categories/timestamps, `mv` rewrites tracked paths while preserving history, and `undo` hands the last `OperationPlan` back to `OperationExecutor.rollback`. All commands surface JSON alongside human-readable output and reuse shared error payloads.

## Module Responsibilities

### CLI Layer (`src/dorgy/cli.py`, `src/dorgy/__init__.py`, `main.py`)

Implements command registration, lazy dependency loading, unified error handling, progress/output helpers, and graceful shutdown handling. `cli_options.py` defines reusable Click options (quiet, summary, JSON, dry-run, recursive) and `ModeResolution`. `cli_support.py` centralizes cross-command helpers: prompt resolution, classification orchestration (`run_classification`), decision/descriptor zipping, watch batch rendering, and summary computations. `dorgy.shutdown` installs SIGINT/SIGTERM handlers so Ctrl+C sets a shared event, allowing ingestion, classification, and watch loops to unwind quickly before the CLI exits with code 130.

### Configuration (`src/dorgy/config/`)

`ConfigManager` manages YAML files under `~/.dorgy/config.yaml`, ensuring files exist and layering precedence of defaults, disk overrides, environment variables, and CLI inputs. Models in `models.py` are Pydantic structures representing config sections (`cli`, `processing`, `organization`, `llm`). `resolver.py` flattens keys for environment variables and validates merged configs, while `exceptions.py` defines `ConfigError`.

### Ingestion (`src/dorgy/ingestion/`)

The pipeline discovers files, filters by size/hidden/locking rules, computes hashes for deduplication, extracts MIME-aligned metadata and previews, and optionally stages or copies content. `DirectoryScanner`, `TypeDetector`, `HashComputer`, and `MetadataExtractor` are modular so tests can stub components. `IngestionPipeline` coordinates threading, emits stage callbacks, enforces sample limits for large files, honours `processing.preview_char_limit`, and captures errors/needing-review flags. It also polls the shared shutdown event so Ctrl+C interrupts long-running extractions without leaving staging artefacts behind.

### Classification (`src/dorgy/classification/`)

Wraps DSPy programs and language model coordination. `engine.py` houses `ClassificationEngine` with optional DSPy dependencies and fallback heuristics gated by `DORGY_USE_FALLBACKS`. `models.py` defines requests/decisions/batches; `exceptions.py` provides typed errors; `cache.py` and `vision.py` manage JSON caches for decisions and captions. `structure.py` computes destination folder recommendations, and `dspy_logging.py` scopes DSPy logging for reproducibility. `LLMSettings` consumes LiteLLM-style `llm.model` strings as the sole identifier for remote or local backends, and the CLI surfaces the active LLM metadata (model, parameters, fallback state) in both human and JSON outputs for auditing.

### Organization (`src/dorgy/organization/`)

`planner.py` translates classification results into rename/move/metadata steps while respecting conflict strategies, destination overrides, and notes for users. `executor.py` executes plans with staging directories, rollback safeguards, and event emission. `models.py` defines `OperationPlan`, `MoveOperation`, `RenameOperation`, `MetadataOperation`, and delete/quarantine types relied upon by watch and undo workflows.

### State & History (`src/dorgy/state/`)

`StateRepository` encapsulates persistence inside `.dorgy/`, storing `CollectionState` (per-file metadata, tags, categories, confidence, needs-review flags), original structure snapshots (`orig.json`), history logs (`history.jsonl`), and rolling notes/needs-review/quarantine subdirectories. Errors raise `StateError`/`MissingStateError`. State is the backbone for search, status, move, and undo commands and for watch batch summaries.

### Watch Service (`src/dorgy/watch/service.py`)

`WatchService` monitors directories via `watchdog` observers (optional dependency). It normalizes filesystem events, debounces bursts, and batches descriptors before handing them to the same ingestion/classification/organization pipeline. Batch results are returned as `WatchBatchResult` objects with counts, errors, planner notes, JSON payloads, and suppressed deletions (when `processing.watch.allow_deletions` is false or `--allow-deletions` is omitted). Watch runs honour copy mode, dry-run, prompt overrides, CLI output helpers, and the shared shutdown event so Ctrl+C stops observers and queued work promptly.

### CLI Support & Shared Utilities

- `cli_support.py` &mdash; classification caching keys, descriptor-to-state conversions, summary builders, error payload assembly, and helper functions (`build_original_snapshot`, `descriptor_to_record`, `relative_to_collection`).
- `cli_options.py` &mdash; consolidated Click option decorators so commands stay aligned with global UX.
- `classification/vision.py` &mdash; integrates image captioning, caching captions in `.dorgy/vision.json` and respecting prompts forwarded from the CLI.

## Data & Caching Layout

- `.dorgy/state.json` &mdash; serialized `CollectionState` for the collection root.
- `.dorgy/history.jsonl` &mdash; append-only record of `OperationEvent`s, powering `status` and audit tooling.
- `.dorgy/orig.json` &mdash; original tree snapshot captured before applying plans, leveraged by undo.
- `.dorgy/staging/` &mdash; temporary workspace used by `OperationExecutor` for safe renames/moves.
- `.dorgy/classifications.json` &mdash; persisted decision cache, enabling incremental runs.
- `.dorgy/vision.json` &mdash; cached image captions to avoid redundant model calls.
- `.dorgy/needs-review/` and `.dorgy/quarantine/` &mdash; holding areas for files that need manual attention or were isolated by the pipeline.

## Automation & Tooling Surface

- `tasks.py` exposes Invoke tasks that wrap `uv` (`sync`, `tests`, `lint`, `ci`, `release`, `tag-version`) so local workflows mirror CI.
- `.github/workflows/ci.yml` runs Ruff (lint/format/imports), MyPy (`uv run mypy src main.py`), and pytest via `uv` on pushes and PRs. Any new automated checks should be wired through this workflow and kept consistent with Invoke tasks.
- `SPEC.md` tracks phased roadmap deliverables, while `notes/STATUS.md` captures working-session notes, blockers, and next actions. Architecture changes that influence automation contracts or integration points should be reflected there and in module-specific `AGENTS.md` files.

## Extensibility Notes

1. New CLI commands should import heavy collaborators lazily and reuse `cli_options` decorators plus `cli_support` output helpers to stay aligned with summary/quiet/JSON semantics.
2. Pipeline extensions (detectors, metadata extraction, planners) should plug into existing interfaces so watch and organization runs automatically benefit.
3. Any new automation entry point or third-party integration must document expectations in the relevant module `AGENTS.md` and update caches/state schema comments as needed.
4. When enabling new model capabilities (e.g., additional captioning backends), ensure prompt forwarding, cache semantics, and `.dorgy` persistence remain consistent so downstream automation continues to operate.
