## Dorgy

Dorgy is a Python CLI that will organize your files with AI assistance. The current focus is establishing the project foundations (CLI scaffolding, packaging, automation hooks) before implementing the full pipeline described in `SPEC.md`.

### Getting Started

```bash
# Install dependencies with uv
uv sync

# Install pre-commit hooks (one-time)
uv run pre-commit install

# Inspect the CLI (commands are placeholders for now)
uv run dorgy --help

# Run lint/format/tests via hooks
uv run pre-commit run --all-files

# View or modify configuration
uv run dorgy config view
uv run dorgy config set llm.temperature --value 0.25
```

### Project Conventions

- Manage work on feature branches (e.g., `feature/phase-0-foundations`) and run `uv run pre-commit run --all-files` before pushing.
- Track roadmap progress in `SPEC.md` and keep session updates in `notes/STATUS.md`.
- Use `uv run dorgy <command>` while the CLI lives in this repository; entry points log a placeholder message until later phases implement functionality.

Refer to `AGENTS.md` for automation guidelines and team coordination expectations.

### Current CLI Highlights

```bash
# Organize a directory in place
uv run dorgy org ./documents

# Organize into a separate output directory (preserves originals)
uv run dorgy org ./inbox --output ./organized

# Preview undo information (text or JSON)
uv run dorgy undo ./documents --dry-run
uv run dorgy undo ./documents --dry-run --json

# Inspect collection status and recent history
uv run dorgy status ./documents
uv run dorgy status ./documents --json

# Search tracked metadata with filters or JSON output
uv run dorgy search ./documents --name "*.pdf" --limit 10
uv run dorgy search ./documents --json

# Move or rename tracked files while updating state/history
uv run dorgy mv ./documents/invoice.pdf ./documents/archive/invoice.pdf
uv run dorgy mv ./documents/invoice.pdf ./documents/archive/ --conflict-strategy timestamp

# Monitor directories once or continuously
uv run dorgy watch ./inbox --once
uv run dorgy watch ./inbox --debounce 1.5 --json
uv run dorgy watch ./inbox --allow-deletions --json

# Limit output to summary lines or silence non-errors
uv run dorgy org ./documents --summary
uv run dorgy status ./documents --quiet

# Emit machine-readable execution payloads
uv run dorgy org ./documents --json
```

### Configuration Notes

- Configuration lives at `~/.dorgy/config.yaml`. Run `uv run dorgy config view` to inspect the effective settings (including environment overrides).
- Update individual values via `uv run dorgy config set section.key --value <value>` or edit the entire file with `uv run dorgy config edit` (validation runs before saving).
- Environment variables follow the `DORGY__SECTION__KEY` naming convention and take precedence over file values; CLI-provided overrides always win for a given invocation.
- Locked/corrupted file handling is governed by `processing.locked_files` and `processing.corrupted_files`; use `copy|skip|wait` or `quarantine|skip` to steer ingestion behaviour.
- Automatic renaming can be toggled with `organization.rename_files`; set to `false` to keep original filenames while still recording suggestions in state.
- Classification uses DSPy by default once you configure the `llm` block (provider/model/api_key or api_base_url). Set `DORGY_USE_FALLBACK=1` only if you intentionally want the lightweight heuristic classifier.
- Organized files are relocated into category folders derived from classification decisions (e.g., `Documents/`); undo data is captured in `.dorgy/last_plan.json` and `dorgy.log`.
- Use the `cli` section to control verbosity defaults (`quiet_default`, `summary_default`), progress indicators (`progress_enabled`), default search limits (`search_default_limit`), move conflict handling (`move_conflict_strategy`), and the status history limit; environment overrides follow `DORGY__CLI__QUIET_DEFAULT`, etc.
- Configure watch behaviour under `processing.watch` (debounce, batch sizing, error backoff, `allow_deletions`) to match your filesystem activity profile before running `dorgy watch`. Destructive removals are opt-in—either set `processing.watch.allow_deletions: true` or pass `--allow-deletions`; otherwise removals are suppressed and surfaced in watch notes/JSON, which now include batch `started_at`/`completed_at` timestamps.
- Control ingestion/classification throughput via `processing.parallel_workers`; increase this value to issue multiple requests in parallel when your provider supports concurrent calls.
- Enable `processing.process_images` to invoke the DSPy-backed vision captioner. Captions and labels are cached per file hash in `.dorgy/vision.json`, enrich descriptor previews/tags, and flow into both DSPy classification prompts and the heuristic fallback. The configured `llm` provider/model must support multimodal inputs; otherwise the captioner will raise a clear CLI error. Inline prompts supplied via `--prompt` are forwarded to the captioner so image summaries follow the same guidance as text classification.
