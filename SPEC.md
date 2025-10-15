# dorgy

Dorgy is a python-based CLI app that automatically organizes your files.

## 1. Executive Summary

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
# with additional instructions
dorgy org . -r --prompt "Ensure documents from the same tax year are grouped together"

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
  provider: "local"  # local, openai, anthropic
  model: "llama3"    # for ollama
  api_key: null      # for cloud providers
  temperature: 0.1
  max_tokens: 2000

# Processing Options
processing:
  use_vision_models: false
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
  confidence_threshold: 0.80  # Flag for review if below this
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
        if classification.confidence >= 0.8:
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
            'needs_review': classification.confidence < 0.8
        }
```

## Implementation Plan

The project will progress through the following phases. Update the status column here as checkpoints are completed, and record day-to-day notes in `notes/STATUS.md`.

| Status | Phase | Scope Highlights |
| ------ | ----- | ---------------- |
| [x] | Phase 0 – Project Foundations | Scaffold `dorgy` package, Click entrypoint, `pyproject.toml` configured for `uv`, baseline docs (`README.md`, `AGENTS.md`) - CLI skeleton + pre-commit baseline + config/state scaffolding |
| [x] | Phase 1 – Config & State | Pydantic-backed config loader/writer targeting `~/.dorgy/config.yaml`, flag/env overrides, shared helpers – config CLI + state repository persistence |
| [~] | Phase 2 – Content Ingestion | File discovery with recursion/filters, adapters for `python-magic`, `Pillow`, `docling`, error channels |
| [ ] | Phase 3 – LLM & DSPy Integration | Implement `dorgyanizer` module, provider-agnostic LLM client, caching, low-confidence fallbacks |
| [ ] | Phase 4 – Organization Engine | Batch orchestration, conflict handling, `.dorgy` state writing, dry-run/JSON/output/rollback support |
| [ ] | Phase 5 – Watch Service | `watchdog` observer, debounce/backoff, safe concurrent writes, reuse ingestion pipeline |
| [ ] | Phase 6 – CLI Surface | Deliver `org`, `watch`, `config`, `search`, `mv`, `undo` commands with Rich/TQDM feedback |
| [ ] | Phase 7 – Search & Metadata APIs | `chromadb`-backed semantic search, tag/date filters, `mv` metadata updates |
| [ ] | Phase 8 – Testing & Tooling | `uv` workflow, pre-commit hooks (format/lint/import-sort/pytest), unit/integration coverage |

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
- Metadata extraction captures text/json previews, image EXIF data, and records when sampling/truncation occurs.
- Locked file handling supports skip/wait/copy actions; copy operations stage files safely before cleanup.
- Corrupted files respect the `quarantine` policy, with CLI feedback and state/log updates.
- `dorgy org` now wires the ingestion pipeline, dry-run preview, JSON output, and state persistence.

## Phase 3 – LLM & DSPy Integration Goals

- Convert `FileDescriptor` outputs into DSPy `FileClassification` and `FileRenaming` signatures, capturing reasoning, tags, and confidence scores.
- Introduce a provider-agnostic LLM client (local/cloud) with retry/backoff, prompt templates derived from SPEC examples, and caching via the state repository.
- Implement low-confidence handling: route items below the ambiguity threshold to `.dorgy/needs-review` and surface them in CLI summaries.
- Feed organization results back into `StateRepository` (categories, tags, rename suggestions) while preserving rollback data (`orig.json`).
- Extend CLI (`org`, `watch`, `search`, `mv`) to consume the classification pipeline, including prompt support and JSON/dry-run parity.
- Expand test coverage with mocked DSPy modules to validate prompt composition, caching, and confidence-based branching.

### Progress Summary
- Classification scaffolding with heuristic fallback is in place; DSPy program wiring remains.
- CLI `org` command now runs classification, records categories/tags/confidence, and honours `organization.rename_files` to control renaming.

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
