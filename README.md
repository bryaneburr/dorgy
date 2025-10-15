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
```

### Project Conventions

- Manage work on feature branches (e.g., `feature/phase-0-foundations`) and run `uv run pre-commit run --all-files` before pushing.
- Track roadmap progress in `SPEC.md` and keep session updates in `notes/STATUS.md`.
- Use `uv run dorgy <command>` while the CLI lives in this repository; entry points log a placeholder message until later phases implement functionality.

Refer to `AGENTS.md` for automation guidelines and team coordination expectations.
