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
- Prioritize Phase 4.5 tasks, create `feature/phase-4-5-cli-polish` branch.
- Implement enhancements iteratively with checkpoints (start with output consistency + JSON execution support, then extend to error handling/config integration).
- Maintain test coverage alongside documentation updates to keep CLI behavior deterministic ahead of Phase 5.
