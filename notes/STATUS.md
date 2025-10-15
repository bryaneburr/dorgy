# Status Log

## 2025-10-14
- Initialized tracking scheme; updated `SPEC.md` implementation phases and expanded coordination directives in `AGENTS.md`.
- Added this status log to capture ongoing progress, blockers, and next steps.
- Created feature branch `feature/phase-0-foundations` and confirmed `uv` tooling availability (`uv --version`, `uv run python -V`).
- Scaffolded package structure in `src/dorgy`, introduced Click-based CLI skeleton, and wired console entry point along with `python -m dorgy`.
- Updated `pyproject.toml` for package metadata, dependencies, `uv` management, and console script; regenerated `uv.lock`.
- Added baseline README guidance and marked Phase 0 status as in progress within `SPEC.md`.
- Standardized local Python to 3.11 by updating `.python-version`, so uv commands automatically use the compatible interpreter.
- Established pre-commit configuration (Ruff lint/format/imports, MyPy, `uv run pytest`), added tool configs in `pyproject.toml`, and documented workflow updates in README/AGENTS.
- Added scaffolding for configuration and state management modules (placeholders plus Pydantic models) with accompanying tests to keep future implementations guided.
- Documented Phase 1 scope and added resolver placeholders outlining precedence (CLI > env > file > defaults) along with tests asserting the current NotImplemented status.
- Next actions: outline CLI command behaviors for Phase 1, design the config load/save workflow ahead of implementation, and capture ingestion pipeline assumptions in SPEC.md.

## 2025-10-15
- Merged Phase 0 foundations into `main` and created `feature/phase-1-config` for the next stage of work.
- Updated `SPEC.md` to mark Phase 0 complete and Phase 1 in progress; captured ingestion pipeline assumptions.
- Implemented configuration persistence/resolution (file/env/CLI precedence), wired `dorgy config view|set|edit`, and added unit/CLI tests.
- Documented configuration usage in README/AGENTS to guide future contributors.
- Delivered state repository persistence helpers (`state.json`, `orig.json`, review/quarantine folders) with tests covering round-trips and error handling.
- Phase 1 complete; SPEC table updated accordingly. Upcoming focus: integrate configuration/state usage into future commands and begin Phase 2 ingestion scaffolding.

## 2025-10-16
- Created `feature/phase-2-ingestion` branch and expanded SPEC with detailed ingestion architecture goals/deliverables.
- Next actions: scaffold ingestion modules (`discovery`, `detectors`, `extractors`, `pipeline`), introduce Pydantic models for descriptors, and add placeholder tests.
