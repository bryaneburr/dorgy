# CONFIG COORDINATION NOTES

- Responsible for loading, validating, and persisting `~/.dorgy/config.yaml`; configuration helpers (`ensure_config`, `load_config`, `save_config`) delegate directly to `durango.ConfigManager`, so new fields must remain compatible with Durango's precedence rules (defaults → file → environment → overrides).
- Any module requiring configuration values should call `load_config(...)` instead of reading files directly; inject the helpers for testability when behaviour depends on configuration.
- Durango parses environment variables via `DORGY__*` keys; our wrapper pre-processes values with YAML semantics so structured overrides (lists/dicts) continue to work. Preserve this behaviour when extending environment handling.
- CLI and automation-supplied overrides must call `normalize_override_mapping` before handing data to the manager to keep dotted keys (`section.value`) interoperable with nested mappings.
- When adding new config fields, update `dorgy.config.models`, include defaults, and refresh environment documentation via `python scripts/generate_env_keys.py` so `DORGY__SECTION__KEY` examples stay accurate.
- `processing.preview_char_limit` sets the maximum characters stored in descriptor previews (default 2048) and is mirrored in ingestion metadata (`preview_limit_characters`); coordinate ingestion/classification tests and docs when tweaking it.
- `LLMSettings` accepts fully-qualified LiteLLM model strings via `llm.model`; avoid introducing auxiliary fields for provider selection so the LiteLLM identifier remains the single source of truth.
- CLI updates touching configuration must extend tests in `tests/test_config_cli.py` and, if new precedence rules apply, add coverage in `tests/test_config_manager.py`.
- Classification behaviour respects `organization.rename_files`; update docs/tests if you add additional renaming toggles.
- `ambiguity.confidence_threshold` defaults to 0.60; watchers and CLI summary logic assume values below this require review, so update related fixtures when tuning it.
- Current defaults enable vision captioning (`processing.process_images: true`) while keeping renaming opt-in (`organization.rename_files: false`); coordinate with ingestion/watch tests if these change.
- Verbosity defaults live under the `cli` block (`quiet_default`, `summary_default`, `status_history_limit`); ensure docs/tests reflect changes and preserve precedence rules.
- The `search` block controls Chromadb defaults (`default_limit`, `auto_enable_org`, `auto_enable_watch`, `embedding_function`). Embedding functions must be importable via `package.module:callable` (or dotted equivalent); validate strings early so CLI surfaces actionable errors rather than failing deep inside Chromadb.
- When `search.auto_enable_watch` is true, `dorgy.watch` should behave as if `--with-search` were passed. Keep doc/tests aligned when changing the default and ensure CLI flags continue to override the setting explicitly.
