# Implementation Plan

1. Phase 0 – Project Foundations: scaffold a dorgy Python package with Click entrypoint, pyproject.toml configured for uv, docstring-based CLI help, and baseline AGENTS/README updates describing automation hooks.
2. Phase 1 – Config & State: implement config loader/editor targeting ~/.dorgy/config.yaml with Pydantic models, default generation, override cascade (CLI flags → env vars → file), and read/write helpers used across commands.
3. Phase 2 – Content Ingestion Pipeline: build pluggable file discovery that respects recursion, size filters, symlinks, and hidden/locked handling; integrate python-magic, Pillow, and docling adapters to produce normalized FileDescriptor objects with previews, metadata, hashes, and error channels (needs-review, quarantine).
4. Phase 3 – LLM & DSPy Integration: wrap DSPy signatures into a dorgyanizer module with provider-agnostic LLM client, prompt templating, fallback heuristics for low-confidence outputs, and caching of inference results in .dorgy/chroma; ensure deterministic dry-run JSON formats.
5. Phase 4 – Organization Engine: create orchestrator that batches descriptors, calls classifier/renamer/structure modules, resolves naming conflicts, preserves timestamps, writes .dorgy state (orig.json, logs, quarantine), and supports --dry-run, --json, --output, and rollback on errors.
6. Phase 5 – Watch Service: integrate watchdog observer with debounce and backoff, share pipeline with org, ensure concurrent-safe writes, and persist incremental metadata updates while honoring config for locked/corrupted files.
7. Phase 6 – CLI Surface: deliver org, watch, config (view/set/edit), search, mv, and undo commands using Click; include Rich/TQDM feedback, structured logging, and consistent option parsing across commands.
8. Phase 7 – Search & Metadata APIs: use chromadb collections to power semantic and tag/date filters, maintain FileRecord index on each organization run, and update entries when mv executes (with validation of destination).
9. Phase 8 – Testing & Tooling: configure uv pip compile lock, add pre-commit (formatting, lint, import sort, pytest), implement unit/integration tests for pipeline stages and CLI workflows (including dry-run/undo), and document automation expectations in AGENTS plus SPEC alignment updates.

## Risks & Open Questions: 
Clarify scope of streaming previews for large binaries, provider credentials storage, and concurrency model for watch-induced LLM calls to avoid rate limits; confirm expected minimum Python version and offline behavior.

# Next Steps 
Confirm assumptions above, prioritize MVP slice (likely Phases 0–4 + 8 minus watch/search), then branch off (feature/dorgy-mvp) and begin implementation with uv-managed env and pre-commit hooks.