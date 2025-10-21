# AGENT DIRECTIVES

- Use `uv` as the default Python environment manager for all development and CI tasks.
- Maintain feature branches for new work; merge to `main` only after linters and tests pass.
- Keep AGENTS.md files up to date for every module that introduces non-trivial coordination expectations.
- Configure and run pre-commit hooks before every push; hooks must format, lint, sort imports, and execute the Python test suite when source files change.
- Document any automation-facing behaviors or integration points directly in the relevant module's AGENTS.md file.
- Provide detailed Google-style docstrings for every Python module, class, and function; update existing docstrings when behavior or signatures change.
- CLI commands share summary/quiet helpers and standardized JSON error payloads; extend those utilities when adding new commands and update tests accordingly.
- The watch service must reuse the organization pipeline helpers and surface batches via the shared CLI output helpers and JSON schema.
- Destructive watch removals are guarded by `processing.watch.allow_deletions`/`--allow-deletions`; when opt-out, suppress deletions but emit notes/JSON entries so automation can triage.
- Keep `ARCH.md` current as architecture or coordination patterns evolve; update the doc alongside substantive pipeline, module, or workflow changes.
- PyPI distribution work must run on a feature branch, complete TestPyPI validation, and update SPEC Phase 9 plus `notes/STATUS.md` before tagging/releases.
- CLI startup relies on lazy imports (`__getattr__` + `_load_dependency`); when adding new modules, extend the lazy map instead of reintroducing eager imports so `dorgy` remains responsive.
- GitHub Actions workflow `.github/workflows/ci.yml` enforces Ruff lint/format, MyPy (`uv run mypy src main.py`), and pytest via `uv` on pushes to `main` and pull requests; add new automated checks there to keep CI authoritative.

## Tracking & Coordination

- The primary implementation plan lives in `SPEC.md`; update phase status indicators when milestones move forward.
- Record working-session notes, blockers, and next actions in `notes/STATUS.md` at the end of each session.
- Use feature branches named `feature/<phase-or-scope>` and keep them in sync with pre-commit hooks (`uv run pre-commit run --all-files`) before opening PRs.
- Surface any new automation entry points or third-party integrations added during a phase in this file alongside module-specific AGENTS documents.
- When enabling image captioning (`processing.process_images`), document model expectations in SPEC/README, ensure `.dorgy/vision.json` caching semantics are respected, and forward CLI prompts so automation consumers receive consistent, context-aware metadata.
- Pre-commit stack currently runs Ruff (lint/format/imports), MyPy, and `uv run pytest`; install with `uv run pre-commit install` and keep hooks up to date via `uv run pre-commit autoupdate` when upgrading tooling.
- Configuration CLI (`dorgy config view|set|edit`) is live; ensure features that depend on settings document their expected keys and defaults in SPEC.md and validation logic.
