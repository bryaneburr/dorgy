# CLI COORDINATION NOTES

- `app.py` defines the root Click group and registers commands exposed by `commands/*.py`; add new commands by creating a module that exports both the Click callback and `register_<name>_command(cli)`.
- Keep heavy dependencies lazy: commands should rely on `_load_dependency` from `dorgy.cli.lazy` so startup remains fast and tests can monkeypatch imported classes.
- Reuse helpers under `helpers/` for logging/progress/state/search logic (`helpers/messages.py`, `helpers/progress.py`, `helpers/state.py`, etc.) to preserve consistent quiet/summary/JSON behaviour across commands.
- Any CLI feature that touches automation-facing payloads must update `helpers/messages` so JSON and Rich outputs remain aligned; extend or adjust related tests under `tests/test_cli_*.py`.
- Update `ARCH.md`, `SPEC.md`, and `notes/STATUS.md` whenever CLI surface area or coordination expectations change; `helpers` docstrings should stay Google-style to guide contributors.
- Before merging CLI changes, run `uv run pre-commit run --all-files` and ensure new options are reflected in `README.md` examples plus `SPEC.md` configuration tables.
