# CLI COORDINATION NOTES

- Reuse the shared CLI helpers (`_emit_message`, `_emit_errors`, `_format_summary_line`, `_handle_cli_error`) when adding new commands or extending existing ones to preserve quiet/summary semantics and structured errors.
- Honour configuration-driven defaults from `ConfigManager` (`config.cli.quiet_default`, `config.cli.summary_default`, `config.cli.status_history_limit`) before applying command-line overrides.
- Keep `--summary`, `--quiet`, and `--json` validation logic aligned across commands; update integration tests when introducing new mutually exclusive flags.
- Machine-readable outputs should mirror dry-run and executed payloads, including `context` and `counts` metadata; extend tests in `tests/test_cli_org.py` for new JSON schemas.
