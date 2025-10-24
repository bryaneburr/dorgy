# CLI COORDINATION NOTES

- Reuse the shared CLI helpers (`_emit_message`, `_emit_errors`, `_format_summary_line`, `_handle_cli_error`) when adding new commands or extending existing ones to preserve quiet/summary semantics and structured errors.
- Honour configuration-driven defaults from `ConfigManager` (`config.cli.quiet_default`, `config.cli.summary_default`, `config.cli.status_history_limit`) before applying command-line overrides.
- Keep `--summary`, `--quiet`, and `--json` validation logic aligned across commands; update integration tests when introducing new mutually exclusive flags.
- Machine-readable outputs should mirror dry-run and executed payloads, including `context` and `counts` metadata; extend tests in `tests/test_cli_org.py` for new JSON schemas.
- JSON payloads must expose `context.llm` (model, temperature, fallback state); keep CLI/watch tests updated whenever the LLM metadata schema evolves.
- Leverage option factories in `dorgy.cli.options` (JSON/summary/quiet/dry-run/etc.) and `resolve_mode_settings` to keep flag behaviour consistent; new commands should not reimplement this logic.
- `--classify-prompt`/`--classify-prompt-file` provide classifier guidance and must override inline text with UTF-8 file contents; ensure JSON payloads/tests continue to serialize these values alongside the legacy `context.prompt` field for automation compatibility. `--structure-prompt`/`--structure-prompt-file` thread separate guidance into structure planning and should default to the classification prompt when unset.
- Progress instrumentation lives behind `_ProgressScope` and should only activate when `config.cli.progress_enabled` and the console is interactive; disable automatically for JSON/quiet/summary contexts.
- `dorgy search` (and future read-only commands) operate solely on `StateRepository` data—respect filters, enforce config-driven defaults (e.g., `cli.search_default_limit`), and return results sorted/limited consistently across text and JSON outputs.
- `dorgy mv` must route operations through `OperationExecutor` so staging/rollback semantics remain intact; update state/history via repository helpers, guard `.dorgy` metadata folders, and expose conflict notes in both text and JSON responses.
- Watch JSON payloads now include `started_at`, `completed_at`, and `duration_seconds`; maintain these fields when extending watch automation hooks to keep downstream tooling stable.
- Ingestion and classification workers respect `processing.parallel_workers`; keep concurrency changes thread-safe and continue to emit debug timing logs so slow providers can be diagnosed.
- CLI command docstrings should remain single-line summaries so `dorgy --help` output stays concise; avoid embedding argument details inside the docstrings.
- Vision captioning depends on Pillow image plugins for some formats; the runtime auto-registers `pillow-heif`, `pillow-avif-plugin`/`pillow-avif`, and `pillow-jxl`/`pillow-jxl-plugin` when installed, so pull in the relevant optional dependency when testing HEIC/AVIF/JPEG XL assets.
