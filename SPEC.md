# dorgy

Dorgy is a python-based CLI app that automatically organizes your files.

## 1. Executive Summary

Refer to the [architecture overview](ARCH.md) for a detailed breakdown of runtime components, pipelines, and data flow; keep the document in sync with the phases outlined here.

An automated file organization system that leverages LLMs to intelligently categorize, rename, and structure files across various formats. The system processes documents, images, and other file types using advanced document understanding, metadata extraction, and semantic analysis.

### Primary Use Cases
- Organize scanned physical documents automatically
- Continuous monitoring and organization of new files (e.g., Downloads folder)
- Batch organization of existing file collections
- Smart cleanup and deduplication

## Usage

### Examples

```bash
# Organize the files in the current directory
dorgy org .

# Organize the files in the current directory
# and include all subfolders (recursive)
dorgy org . -r

# Organize the files in the current directory
# with additional classification and structure instructions
dorgy org . -r \
  --classify-prompt "Highlight tax documents" \
  --structure-prompt "Group files by tax year"

# Supply classification instructions from a file
dorgy org . --classify-prompt-file prompts/tax-guidelines.txt

# Organize the ~/Downloads directory
dorgy org ~/Downloads

# Organize the contents of the ~/Downloads
# directory by copying the files to another
# directory as they are organized
dorgy org ~/Downloads --output some/folder/

# Output a description of the new file tree
# and how files are organized without executing
# the operation
dorgy org . --dry-run

# Output a description of proposed file organization
# in JSON format without executing the operation
dorgy org . --json

# Watch a directory and automatically organize
# new files as they arrive
dorgy watch .
dorgy watch . -r --output some/folder # with options/flags

# Watch a directory using classification instructions stored in a prompt file
dorgy watch . --once --json --classify-prompt-file prompts/watch-guidance.txt

# Config
dorgy config edit # edit config
dorgy config view # view config
dorgy config set some_key --value some_value # set config value

# Search within organized directory
dorgy search some/folder/ --search "Text for semantic search" --tags "Finance, Tax, Invoice" --before "Aug 31st 2025"

# Move a file/directory within an organized collection of files,
# which will update the collection's metadata
dorgy mv some/folder/dir/file.pdf some/folder/other_dir/file.pdf

# Undo (restore to original file structure)
dorgy undo some/folder/
```

## Tech

### Core Dependencies

```
# File Processing
docling>=1.0.0              # Document understanding
watchdog>=3.0.0             # File system monitoring
Pillow>=10.0.0              # Image processing & EXIF

# LLM & AI
dspy>=2.0.0                 # LLM operations
chromadb                    # Vector store and collection metadata

# CLI & UI
click>=8.0.0                # CLI framework
rich>=13.0.0                # Terminal formatting
tqdm                        # Progress bars

# Utilities
pyyaml                      # Config files
python-magic                # File type detection
xxhash                      # Fast hashing
pydantic                    # Internal data models
```

### Main Config

Stored at `~/.dorgy/config.yaml`

```yaml
# LLM Configuration
llm:
  model: "openai/gpt-5"  # Fully qualified <provider>/<model> identifier
  api_base_url: null     # Optional override for custom gateways
  api_key: null          # Only required for hosted providers
  temperature: 1.0
  max_tokens: 25000

# Processing Options
processing:
  process_images: false
  process_audio: false
  follow_symlinks: false
  process_hidden_files: false
  max_file_size_mb: 100  # Sample files larger than this
  sample_size_mb: 10     # Size of sample for large files

  # Locked file handling
  locked_files:
    action: "copy"  # copy, skip, wait
    retry_attempts: 3
    retry_delay_seconds: 5
  
  # Corrupted file handling
  corrupted_files:
    action: "skip"  # skip, quarantine

  # Watch service tuning
  watch:
    debounce_seconds: 2.0
    max_batch_interval_seconds: 10.0
    max_batch_items: 128
    error_backoff_seconds: 5.0
    max_error_backoff_seconds: 60.0

# Organization Strategies
organization:  
  # Naming conflicts
  conflict_resolution: "append_number"  # append_number, timestamp, skip
  
  # Date-based organization
  use_dates: true
  date_format: "YYYY-MM"
  
  # Language handling
  preserve_language: false  # false = treat as English, true = treat as original language
  
  # Metadata preservation
  preserve_timestamps: true
  preserve_extended_attributes: true

# Ambiguity Handling
ambiguity:
  confidence_threshold: 0.60  # Flag for review if below this
  max_auto_categories: 3      # Max tags/categories per file

# Performance
performance:
  batch_size: 10
  parallel_workers: 4

# Safety
safety:
  dry_run: false
  auto_backup: true
  rollback_on_error: true

# Logging
logging:
  level: "WARNING"  # DEBUG, INFO, WARNING, ERROR
  max_size_mb: 100
  backup_count: 5

# CLI Defaults
cli:
  quiet_default: false
  summary_default: false
  status_history_limit: 5

# User-defined Rules (optional)
rules:
  # Example: Force certain patterns to specific categories
  - pattern: "invoice-*.pdf"
    category: "Finance/Invoices"
    priority: high
  - pattern: "*.tax"
    category: "Finance/Taxes"
    priority: high
```

### Organized Collections

When `dorgy` organizes a collection of files, it creates a `.dorgy/` directory at the top top level of the organized directory.

Inside this directory are the following data:
- `.dorgy/chroma/`: `chromadb` chroma store for collection
- `.dorgy/quarantine`: For corrupted files if config `processing.corrupted_files.action = 'quarantine'`
- `.dorgy/needs-review`: For files that fall below `ambiguity.confidence_threshold`
- `.dorgy/dorgy.log`: Log file
- `.dorgy/orig.json`: Original file structure, so we can restore the files to their original pre-organizational structure using `dorgy undo`

### DSPy Integration Strategy

#### DSPy Signatures

```python
import dspy

class FileClassification(dspy.Signature):
    """Classify a file into categories and generate relevant tags."""
    
    # Inputs
    filename: str = dspy.InputField(desc="The filename")
    file_type: str = dspy.InputField(desc="File type (pdf, jpg, etc)")
    content_preview: str = dspy.InputField(desc="Preview of file content")
    metadata: str = dspy.InputField(desc="Extracted metadata (JSON)")
    
    # Outputs
    primary_category: str = dspy.OutputField(desc="Main category for organization")
    secondary_categories: list[str] = dspy.OutputField(desc="Additional relevant categories")
    tags: list[str] = dspy.OutputField(desc="Descriptive tags")
    confidence: float = dspy.OutputField(desc="Confidence score 0-1")
    reasoning: str = dspy.OutputField(desc="Brief explanation of classification")


class FileRenaming(dspy.Signature):
    """Generate a descriptive filename for a file."""
    
    filename: str = dspy.InputField()
    file_type: str = dspy.InputField()
    content_preview: str = dspy.InputField()
    metadata: str = dspy.InputField()
    category: str = dspy.InputField(desc="Assigned category")
    
    suggested_name: str = dspy.OutputField(desc="Descriptive filename without extension")
    reasoning: str = dspy.OutputField(desc="Why this name")


class FolderStructureProposal(dspy.Signature):
    """Propose an optimal folder structure for organizing files."""
    
    file_list: str = dspy.InputField(desc="List of files with their classifications")
    existing_structure: str = dspy.InputField(desc="Current folder structure if any")
    
    proposed_structure: str = dspy.OutputField(desc="Hierarchical folder structure (JSON)")
    reasoning: str = dspy.OutputField(desc="Explanation of structure")


class DuplicateDetection(dspy.Signature):
    """Determine if two files are semantic duplicates."""
    
    file1_info: str = dspy.InputField()
    file2_info: str = dspy.InputField()
    
    is_duplicate: bool = dspy.OutputField()
    similarity_score: float = dspy.OutputField()
    reasoning: str = dspy.OutputField()
```

#### DSPy Module Example

```python
class dorgyanizer(dspy.Module):
    def __init__(self):
        super().__init__()
        self.classifier = dspy.ChainOfThought(FileClassification)
        self.renamer = dspy.ChainOfThought(FileRenaming)
        self.structure_proposer = dspy.ChainOfThought(FolderStructureProposal)
    
    def forward(self, file_info):
        # Classify the file
        classification = self.classifier(
            filename=file_info['filename'],
            file_type=file_info['type'],
            content_preview=file_info['content'][:1000],
            metadata=json.dumps(file_info['metadata'])
        )
        
        # Generate new name if needed
        if classification.confidence >= 0.6:
            new_name = self.renamer(
                filename=file_info['filename'],
                file_type=file_info['type'],
                content_preview=file_info['content'][:1000],
                metadata=json.dumps(file_info['metadata']),
                category=classification.primary_category
            )
        else:
            new_name = None
        
        return {
            'classification': classification,
            'suggested_name': new_name,
            'needs_review': classification.confidence < 0.6
        }
```

## Implementation Plan

The project will progress through the following phases. Update the status column here as checkpoints are completed, and record day-to-day notes in `notes/STATUS.md`.

| Status | Phase | Scope Highlights |
| ------ | ----- | ---------------- |
| [x] | Phase 0 – Project Foundations | Scaffold `dorgy` package, Click entrypoint, `pyproject.toml` configured for `uv`, baseline docs (`README.md`, `AGENTS.md`) - CLI skeleton + pre-commit baseline + config/state scaffolding |
| [x] | Phase 1 – Config & State | Pydantic-backed config loader/writer targeting `~/.dorgy/config.yaml`, flag/env overrides, shared helpers – config CLI + state repository persistence |
| [x] | Phase 2 – Content Ingestion | File discovery with recursion/filters, adapters for `python-magic`, `Pillow`, `docling`, error channels |
| [x] | Phase 3 – LLM & DSPy Integration | Implement `dorgyanizer` module, provider-agnostic LLM client, caching, low-confidence fallbacks |
| [x] | Phase 4 – Organization Engine | Batch orchestration, conflict handling, `.dorgy` state writing, dry-run/JSON/output/rollback support |
| [x] | Phase 4.5 – CLI Polish & UX | Consistent summaries, `--summary/--quiet` toggles, executed `--json` parity, CLI config defaults, structured error payloads |
| [x] | Phase 5 – Watch Service | `watchdog` observer with debounce/backoff, batch pipeline reuse, incremental state/log updates, `dorgy watch` CLI |
| [x] | Phase 5.5 – Watch Deletions & External Moves | Detect removals/moves-out, DeleteOperation support, opt-in safeguards, deletion-aware summaries/JSON |
| [ ] | Phase 5.8 – Vision-Enriched Classification | Leverage `processing.process_images` to capture captions/tags, enrich descriptors with image summaries, extend classifier/tests/docs |
| [~] | Phase 6 – CLI Surface | Deliver `org`, `watch`, `config`, `search`, `mv`, `undo` commands with Rich/TQDM feedback |
| [ ] | Phase 7 – Search & Metadata APIs | `chromadb`-backed semantic search, tag/date filters, `mv` metadata updates |
| [~] | Phase 8 – Testing & Tooling | `uv` workflow, pre-commit hooks (format/lint/import-sort/pytest), unit/integration coverage |
| [~] | Phase 9 – Distribution & Release Prep | PyPI metadata polish, TestPyPI validation, release documentation, CI gating for publishing |

## Work Tracking

- Status legend: `[ ]` not started · `[~]` in progress · `[x]` complete

- Keep this specification synchronized with scope decisions and phase statuses.
- Maintain a session log in `notes/STATUS.md` capturing progress, blockers, and planned next actions after each working block.
- Use feature branches per phase (e.g., `feature/phase-0-foundations`) and merge only after pre-commit hooks and tests pass.
- Capture automation-facing behaviors or integration updates in module-level `AGENTS.md` files when introduced.

## Phase 1 – Config & State Details

### Goals
- Deliver a configuration management layer that reads defaults from `SPEC.md`, merges user overrides from `~/.dorgy/config.yaml`, environment variables, and CLI flags.
- Provide persistence helpers that can bootstrap missing config files with commented examples.
- Wire the CLI `config` subcommands (`view`, `set`, `edit`) to the configuration manager with minimal UX niceties (pretty table output via Rich, validation errors surfaced to the user).
- Establish state repository contracts for saving collection metadata; implementation remains skeletal but should support in-memory stubs for testing downstream features.

### Configuration Precedence
1. CLI flags (command-specific overrides)
2. Environment variables (`DORGY__SECTION__KEY` naming convention)
3. User config file at `~/.dorgy/config.yaml`
4. Built-in defaults defined in `dorgy.config.models`

### CLI Behavior Expectations
- `dorgy config view` prints the effective configuration using syntax-highlighted YAML.
- `dorgy config set SECTION.KEY --value VALUE` updates the persisted YAML and echoes the diff.
- `dorgy config edit` opens the file in `$EDITOR` (fallback to `vi`) and validates the result before saving; rollback if validation fails.

### Deliverables
- Concrete implementations for `ConfigManager.load/save/ensure_exists`.
- Utility for resolving settings with precedence (exposed via `dorgy.config.resolver` helper).
- Tests covering environment overrides, file persistence, and CLI command flows (using Click's `CliRunner`).
- Documentation updates in `README.md` and `AGENTS.md` describing configuration usage and automation hooks for the new behavior.

## Phase 2 – Content Ingestion Assumptions

- File discovery walks directories using `pathlib.Path.rglob` with filters applied for hidden files, symlinks, and size thresholds determined by config.
- `python-magic` resolves MIME types; `Pillow` and `docling` handle previews/metadata depending on file type.
- Large files above `processing.max_file_size_mb` will be sampled to `processing.sample_size_mb` before analysis.
- Locked files follow the `processing.locked_files` policy (copy/skip/wait) with configurable retries.
- `StateRepository` will persist `orig.json`, `needs-review/`, `quarantine/`, and other metadata under `.dorgy/`.

### Progress Summary
- Directory scanning honours hidden/symlink/size policies and flags oversized files for sampling.
- Metadata extraction captures text/json previews, image EXIF data, and respects the configurable `processing.preview_char_limit` (default 2048) while recording truncation metadata (`preview_limit_characters`, sampled character counts).
- Locked file handling supports skip/wait/copy actions; copy operations stage files safely before cleanup.
- Corrupted files respect the `quarantine` policy, with CLI feedback and state/log updates.
- `dorgy org` now wires the ingestion pipeline, dry-run preview, JSON output, and state persistence.
- Ctrl+C/SIGTERM now travels through a shared shutdown event so ingestion, classification, and watch loops unwind quickly before the CLI exits.

## Phase 3 – LLM & DSPy Integration Goals

- Convert `FileDescriptor` outputs into DSPy `FileClassification` and `FileRenaming` signatures, capturing reasoning, tags, and confidence scores.
- Introduce an LLM client (local/cloud) that accepts fully qualified `llm.model` strings, supports retry/backoff, derives prompts from SPEC examples, and caches responses via the state repository.
- Implement low-confidence handling: route items below the ambiguity threshold to `.dorgy/needs-review` and surface them in CLI summaries.
- Feed organization results back into `StateRepository` (categories, tags, rename suggestions) while preserving rollback data (`orig.json`).
- Extend CLI (`org`, `watch`, `search`, `mv`) to consume the classification pipeline, including prompt support and JSON/dry-run parity.
- Expand test coverage with mocked DSPy modules to validate prompt composition, caching, and confidence-based branching.

### Progress Summary
- Classification engine now uses DSPy by default; set `DORGY_USE_FALLBACKS=1` only for development/testing heuristics, and configuration pulls from `llm.model` plus optional API credentials with JSON-backed caching.
- LLM settings now wire `llm.model` (LiteLLM format) plus optional `api_base_url`/`api_key` directly into the DSPy client with defaults of temperature=1.0 and max_tokens=25000 for remote gateways.
- CLI `org` runs classification, records categories/tags/confidence, applies rename suggestions when enabled, and routes low-confidence items to review.

## Phase 4 – Organization Engine Plan

### Goals
- Transform classification decisions into concrete organization actions (renames, moves, metadata updates) governed by `organization` settings.
- Handle conflict resolution strategies (append number/timestamp/skip) and maintain undo metadata for every applied change.
- Support dry-run and JSON previews that surface the proposed operations before execution.
- Update `.dorgy` state/logging with the applied actions to power undo/redo workflows.
- Integrate the organization engine with CLI commands (`org`, `watch`, `mv`, `undo`) so users can inspect and apply plans confidently.

### Implementation Strategy
1. Implement an `Organizer` planner that consumes descriptors + decisions to build an ordered operation plan.
2. Execute the plan with transactional safeguards (staging directories, rollback and resume capabilities).
3. Extend CLI output to show planned/applicable operations, supporting dry-run/JSON parity and `--output` relocation modes.
4. Persist operation history (pre/post paths, timestamps, conflicts resolved) in state/log files alongside classification metadata.
5. Hook into undo/rollback (`dorgy undo`) by referencing the plan history and original structure snapshots.

### Deliverables
- `dorgy.organization` package with planner, executor, and configuration adapters.
- Comprehensive tests covering conflict resolution, rename/move execution, dry-run previews, and rollback safety nets.
- CLI integration tests validating state/log updates, rename toggles, and undo functionality.
- Documentation updates (README, AGENTS, SPEC) describing the organization engine workflow.

### Goals
- Build a reusable ingestion pipeline that discovers files, extracts metadata/previews, and produces `FileDescriptor` objects for downstream classification.
- Respect configuration toggles for recursion, hidden files, symlink handling, maximum sizes, and locked/corrupted file policies.
- Capture discovery/processing metrics for progress reporting and logging.

### Architecture Outline
- `dorgy.ingestion.discovery.DirectoryScanner`: surfaces candidate paths respecting filters and produces `PendingFile` records with basic filesystem metadata.
- `dorgy.ingestion.detectors.TypeDetector`: wraps `python-magic` and quick heuristics to determine MIME/type families.
- `dorgy.ingestion.extractors.MetadataExtractor`: coordinates `docling`, `Pillow`, and other adapters to generate previews/content snippets.
- `dorgy.ingestion.pipeline.IngestionPipeline`: orchestrates the above components, handles batching/parallelism, and emits `FileDescriptor` models along with error buckets (`needs_review`, `quarantine`).

### Deliverables
- Module scaffolding with Pydantic models for `PendingFile`, `FileDescriptor`, `IngestionResult`.
- Interfaces/classes with `NotImplementedError` placeholders for discovery, detection, and extraction behaviors.
- Tests confirming scaffolding entry points exist and raise `NotImplementedError` where implementation will follow.
- Documentation updates (README/AGENTS) highlighting ingestion pipeline layout and configuration touchpoints.

### Progress Summary
- Conflict resolution respects `organization.conflict_resolution` (append_number, timestamp, skip), and rename/move operations surface plan notes describing how collisions were handled; moves still place files into category folders derived from classification decisions.
- Operation history is appended to `.dorgy/history.jsonl` capturing timestamps, pre/post paths, conflict metadata, and reasoning for every rename/move.
- `orig.json` now stores per-run snapshots (`generated_at`, `entries`) based on ingestion descriptors, and `dorgy undo --dry-run` surfaces a preview of captured paths for rollback confirmation.
- Executor stages file mutations in `.dorgy/staging/<session>` before committing renames/moves, providing automatic rollback if conflicts occur mid-plan.
- `dorgy org --output PATH` copies organized files into the destination root (preserving originals), with state/history/logs stored under `PATH/.dorgy` so follow-up commands operate on the relocated collection.
- `dorgy undo` supports `--json` preview and execution output, exposing plan/snapshot/history details for tooling integrations.
- `dorgy status` reports collection summaries (state counts, recent history, snapshot metadata) in both text and JSON formats for inspection.
- Operation plans are applied via the CLI `org` command with JSON/dry-run previews, and undo metadata is captured in `.dorgy/last_plan.json` and `dorgy.log`.

## Phase 4.5 – CLI Polish & UX

## Phase 5 – Watch Service

- `dorgy watch` provides both one-shot (`--once`) and continuous monitoring modes with summary/quiet/JSON parity matching `dorgy org`.
- `WatchService` batches filesystem events using configurable debounce/backoff settings (`processing.watch`) and reuses ingestion/classification/organization pipelines.
- Batches persist incremental updates to `.dorgy/state.json`, `.dorgy/history.jsonl`, and `.dorgy/watch.log`, keeping the collection consistent with manual `org` runs.

### Goals
- Harmonize CLI summaries, providing `--summary/--quiet` toggles across `org`, `status`, and `undo` while surfacing destination and operation counts.
- Extend executed `--json` flows to mirror dry-run payloads with final plan details, state persistence metadata, and history entries.
- Standardize error handling with structured JSON payloads and configuration-driven defaults for verbosity controls.

### Deliverables
- Updated CLI commands with shared summary helpers, structured error emitters, and comprehensive flag validation (`--summary`, `--quiet`, `--json`).
- New `cli` configuration options (`quiet_default`, `summary_default`, `status_history_limit`) with environment override support and test coverage.
- Expanded CLI integration tests covering summary/quiet modes, JSON error payloads, and configuration fallbacks alongside refreshed documentation.

### Progress Summary
- `dorgy org`, `status`, and `undo` now share consistent summary messaging, expose `--summary/--quiet` toggles, and report destination roots plus rename/move/conflict counts.
- Executed `dorgy org --json` responses include context, counts, plan dumps, history events, and state metadata; dry-run parity retained.
- CLI defaults are configurable via the new `cli` block in `config.yaml` with precedence verified for file/CLI/env overrides and corresponding tests.
- JSON errors are emitted uniformly (`{"error": {"code": ..., "message": ...}}`), and new tests validate quiet defaults, summary output, and structured error responses.

## Phase 5.5 – Watch Deletions & External Moves

- Watch batches now normalize filesystem events into `WatchEvent` payloads so deletions, moves within the collection, and moves outside the watched roots are classified before ingestion runs.
- `processing.watch.allow_deletions` (default `false`) and the `dorgy watch --allow-deletions` flag gate destructive state updates, ensuring opt-in semantics for dropping history/state entries.
- `OperationPlan` and history logging include `DeleteOperation` entries with removal `kind` metadata; state repositories remove tracked files, append history, and write watch logs with deletion metrics when opt-in is enabled.
- CLI summaries/JSON payloads expose `deleted` counts, executed removal metadata (`removals`), and suppression details (`suppressed_deletions`), with summary helpers highlighting destructive actions.
- Added tests cover suppressed deletions, allowed deletions, internal moves, and external moves to confirm state persistence, history logging, and JSON surfaced details.

## Phase 5.8 – Vision-Enriched Classification

- `processing.process_images` enables multimodal captioning that generates textual descriptions, key entities, and confidence scores for images and other visual assets; descriptors carry these summaries so DSPy receives meaningful context.
- Captioning output is captured by a DSPy program that uses `dspy.Image` inputs with the configured LLM; results are stored alongside existing classification cache metadata and reused by ingest/watch pipelines.
- Classifier heuristics fall back to the captions/tags when DSPy is disabled, while CLI/JSON outputs expose the captured vision metadata for automation.
- Optional Pillow plugins (e.g., `pillow-heif`, `pillow-avif-plugin`, `pillow-avif`, `pillow-jxl`, `pillow-jxl-plugin`) are auto-registered when present so HEIC/AVIF/JPEG XL assets flow through the captioner without additional configuration.

### Goals
- Reuse the configured `llm.model` for captioning when `process_images` is true by invoking a dedicated DSPy signature that accepts `dspy.Image` inputs; surface clear errors when the model lacks vision capabilities.
- Extend ingestion to request captions when `process_images` is true, normalize summaries/labels into descriptors (`preview`, `metadata["vision_caption"]`, `tags`), and persist them in the classification cache for reuse.
- Thread user-provided prompts into caption requests so image summaries respect the same context as text classification.
- Update classification/organization flows to consume the enriched metadata, adjusting prompts (DSPy) and heuristics so images can be categorized beyond MIME types.
- Document configuration expectations (model requirements, error messaging) in SPEC, AGENTS, and CLI help.

### Deliverables
- `VisionCaptioner` DSPy module that wraps the existing LLM configuration, honors user prompts, and includes a caching strategy plus integration tests covering happy-path captions and failure fallback.
- Updated ingestion metadata extractor and classification cache schema supporting vision payloads plus migration handling for existing cache entries.
- Expanded classification engine tests ensuring DSPy payloads contain caption/text pairs, along with fixtures verifying heuristic improvements.
- CLI JSON payloads (`org`, `watch`) now emit a `vision` object per file when captions are available, and SPEC/AGENTS documentation captures the new automation hooks.
- Collection state records persist caption metadata (`vision_caption`, `vision_labels`, `vision_confidence`, `vision_reasoning`) so downstream history/export tooling retains image context.
- Image loading fallbacks rely on Pillow to convert unsupported formats to PNG before invoking DSPy, ensuring HEIC/AVIF/JXL/ICO/BMP assets participate in captioning when the relevant plugins are installed.

### Risks & Mitigations
- **Latency/Cost:** Run captioning asynchronously with retry/backoff and enforce per-run limits; provide CLI notes when captions are skipped due to model errors.
- **Model Drift:** Encapsulate backend-specific prompts/response parsing in adapters with unit tests; surface informative errors when API capabilities are missing.
- **Privacy/Security:** Honour `processing.process_images` or CLI flags to opt out per-run and log when files are skipped to aid auditing.

### Future Work – Image-only PDF OCR Plan
- **Detection:** Augment the ingestion pipeline to flag PDFs whose pages lack textual content after Docling extraction, treating them as image-only candidates.
- **Rendering:** Use a headless renderer (`pdf2image`, Poppler bindings, or Docling page rasterisation) to convert flagged pages into high-resolution images buffered in memory.
- **OCR Pass:** Invoke a configurable OCR engine (initially Tesseract via `pytesseract`) to extract text per page, merging results into the descriptor preview/metadata while capturing confidence metrics.
- **Caching & Reuse:** Store OCR text alongside the existing classification cache entries to avoid reprocessing unchanged PDFs; leverage document hash to key the cache.
- **CLI & Config:** Add configuration toggles (`processing.process_pdf_images`, OCR language choices) and surface progress/summary notes so users understand when OCR was applied or skipped.
- **Testing:** Provide fixtures covering mixed-content PDFs (text + image), true image-only scans, and multi-language documents to ensure detection heuristics and OCR fallbacks behave correctly.

## Phase 6 – CLI Surface

- Introduced `dorgy search` with glob, tag, category, needs-review, and date-range filters plus JSON output that mirrors prior CLI schemas; defaults (including result limits) honor `cli.search_default_limit`.
- Implemented `dorgy mv` using the organization executor to preserve staging/rollback guarantees while updating state/history; supports dry-run, JSON payloads, and configurable conflict strategies (append number, timestamp, skip).
- Added Rich-powered progress indicators for `dorgy org` and `dorgy watch --once`, automatically disabled for JSON/quiet/non-TTY contexts and controllable via `cli.progress_enabled`.
- Expanded CLI configuration with `cli.move_conflict_strategy` and `cli.search_default_limit` so automation can tune defaults, alongside the new `cli.progress_enabled` toggle for UI instrumentation.
- Watch JSON context now records `started_at`, `completed_at`, and `duration_seconds` alongside `batch_id`, enabling downstream automation to correlate processing timelines.
- Configurable concurrency (`processing.parallel_workers`) allows ingestion and classification batches to issue multiple calls in parallel while logging per-request timings for diagnosis.

## Phase 8 – Testing & Tooling

### Goals
- Keep automated quality gates aligned with local `uv` workflows so linting, typing, and tests run consistently before merges.
- Ensure CI surfaces actionable failures for Ruff lint/format checks, MyPy typing, and `uv run pytest` while respecting the project's toolchain directives.
- Extend documentation so contributors know where to enhance automation and add additional checks.

### Progress Summary
- Added GitHub Actions workflow `.github/workflows/ci.yml` that installs dependencies via `uv sync --extra dev --locked` and runs Ruff lint, Ruff format checks, `uv run mypy src main.py`, and pytest on pushes to `main` and pull requests.

### Next Actions
- Evaluate additional matrices (e.g., macOS, Windows) and caching once the core pipeline stabilizes, and wire future tooling upgrades through this workflow to keep automation authoritative.
