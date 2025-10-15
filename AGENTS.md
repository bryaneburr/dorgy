# AGENT DIRECTIVES

- Use `uv` as the default Python environment manager for all development and CI tasks.
- Maintain feature branches for new work; merge to `main` only after linters and tests pass.
- Keep AGENTS.md files up to date for every module that introduces non-trivial coordination expectations.
- Configure and run pre-commit hooks before every push; hooks must format, lint, sort imports, and execute the Python test suite when source files change.
- Document any automation-facing behaviors or integration points directly in the relevant module's AGENTS.md file.
- Provide detailed Google-style docstrings for every Python module, class, and function; update existing docstrings when behavior or signatures change.

## Tracking & Coordination

- The primary implementation plan lives in `SPEC.md`; update phase status indicators when milestones move forward.
- Record working-session notes, blockers, and next actions in `notes/STATUS.md` at the end of each session.
- Use feature branches named `feature/<phase-or-scope>` and keep them in sync with pre-commit hooks (`uv run pre-commit run --all-files`) before opening PRs.
- Surface any new automation entry points or third-party integrations added during a phase in this file alongside module-specific AGENTS documents.
- Pre-commit stack currently runs Ruff (lint/format/imports), MyPy, and `uv run pytest`; install with `uv run pre-commit install` and keep hooks up to date via `uv run pre-commit autoupdate` when upgrading tooling.
- Configuration CLI (`dorgy config view|set|edit`) is live; ensure features that depend on settings document their expected keys and defaults in SPEC.md and validation logic.
