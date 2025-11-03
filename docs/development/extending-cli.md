# Extending the CLI

- Add a command module under `src/dorgy/cli/commands/` exposing the Click callback and `register_<name>_command(cli)`.
- Use lazy imports via `dorgy.cli.lazy._load_dependency` to keep startup fast.
- Reuse helpers under `src/dorgy/cli/helpers/` for progress, messages, state, and search.
- Emit standardized errors via `_handle_cli_error` and keep quiet/summary/JSON behavior consistent.
- Update examples in README and add JSON contract docs if payloads change.
- Add/adjust tests under `tests/test_cli_*.py`.

See `src/dorgy/cli/AGENTS.md` for coordination details.

