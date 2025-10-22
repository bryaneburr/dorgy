# CONFIG COORDINATION NOTES

- Responsible for loading, validating, and persisting `~/.dorgy/config.yaml`; use `ConfigManager` to respect precedence (CLI > env > file > defaults).
- Any module requiring configuration values should depend on the manager rather than reading files directly; prefer injecting `ConfigManager` instances for testability.
- When adding new config fields, update `dorgy.config.models`, include defaults, and document expected environment variable names (`DORGY__SECTION__KEY`).
- `processing.preview_char_limit` sets the maximum characters stored in descriptor previews (default 2048) and is mirrored in ingestion metadata (`preview_limit_characters`); coordinate ingestion/classification tests and docs when tweaking it.
- `LLMSettings` accepts fully-qualified LiteLLM model strings via `llm.model`; avoid introducing auxiliary fields for provider selection so the LiteLLM identifier remains the single source of truth.
- CLI updates touching configuration must extend tests in `tests/test_config_cli.py` and, if new precedence rules apply, add coverage in `tests/test_config_manager.py`.
- Classification behaviour respects `organization.rename_files`; update docs/tests if you add additional renaming toggles.
- `ambiguity.confidence_threshold` defaults to 0.60; watchers and CLI summary logic assume values below this require review, so update related fixtures when tuning it.
- Current defaults enable vision captioning (`processing.process_images: true`) while keeping renaming opt-in (`organization.rename_files: false`); coordinate with ingestion/watch tests if these change.
- Verbosity defaults live under the `cli` block (`quiet_default`, `summary_default`, `status_history_limit`); ensure docs/tests reflect changes and preserve precedence rules.
