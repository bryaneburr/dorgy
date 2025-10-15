# CONFIG COORDINATION NOTES

- Responsible for loading, validating, and persisting `~/.dorgy/config.yaml`; use `ConfigManager` to respect precedence (CLI > env > file > defaults).
- Any module requiring configuration values should depend on the manager rather than reading files directly; prefer injecting `ConfigManager` instances for testability.
- When adding new config fields, update `dorgy.config.models`, include defaults, and document expected environment variable names (`DORGY__SECTION__KEY`).
- CLI updates touching configuration must extend tests in `tests/test_config_cli.py` and, if new precedence rules apply, add coverage in `tests/test_config_manager.py`.
- Classification behaviour respects `organization.rename_files`; update docs/tests if you add additional renaming toggles.
