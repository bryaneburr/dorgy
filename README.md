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

### Configuration Notes

- Configuration lives at `~/.dorgy/config.yaml`. Run `uv run dorgy config view` to inspect the effective settings (including environment overrides).
- Update individual values via `uv run dorgy config set section.key --value <value>` or edit the entire file with `uv run dorgy config edit` (validation runs before saving).
- Environment variables follow the `DORGY__SECTION__KEY` naming convention and take precedence over file values; CLI-provided overrides always win for a given invocation.
- Locked/corrupted file handling is governed by `processing.locked_files` and `processing.corrupted_files`; use `copy|skip|wait` or `quarantine|skip` to steer ingestion behaviour.
- Automatic renaming can be toggled with `organization.rename_files`; set to `false` to keep original filenames while still recording suggestions in state.
- Classification runs locally using heuristics by default; set `DORGY_ENABLE_DSPY=1` (with DSPy installed/configured) to enable LLM-backed classification and rename suggestions.
- Organized files are relocated into category folders derived from classification decisions (e.g., `Documents/`); undo data is captured in `.dorgy/last_plan.json` and `dorgy.log`.
