# Contributing

- Environment: use `uv sync --extra dev` and run commands via `uv run ...`.
- Pre-commit: `uv run pre-commit install`; run `uv run pre-commit run --all-files` before pushing.
- Branching: `feature/<scope>`; keep rebased until review.
- CI parity: `uv run invoke ci` locally (Ruff, MyPy, pytest).
- Docs: follow Google-style docstrings; keep module `AGENTS.md` files updated when automation-facing behavior changes.

See README.md → Contributing for more.

