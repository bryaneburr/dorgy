# Configuration Reference

Configuration precedence: CLI flags > environment variables (`DORGY__SECTION__KEY`) > `~/.dorgy/config.yaml` file > internal defaults.

Important keys:

- `llm` — model (`provider/name`), `api_base_url`, `api_key`, `temperature`, `max_tokens`.
- `processing` — ingestion/watch toggles; `watch.debounce_seconds`, `watch.allow_deletions`.
- `organization` — `conflict_resolution`, `rename_files`, timestamp preservation.
- `cli` — `quiet_default`, `summary_default`, `progress_enabled`.
- `search` — `default_limit`, `auto_enable_org`, `auto_enable_watch`, `embedding_function`.

See SPEC.md (“Main Config”) for the fully annotated example and current defaults.

