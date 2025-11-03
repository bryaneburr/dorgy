# Configuration

Dorgy reads configuration from `~/.dorgy/config.yaml`, environment variables (`DORGY__SECTION__KEY`), and CLI flags (highest precedence).

Key blocks:

- `llm`: model identifier, base URL, API key, temperature, max tokens.
- `processing`: image captioning, preview limits, recursion, watch settings.
- `organization`: conflict resolution, renaming, timestamp preservation.
- `ambiguity`: confidence threshold and auto-category limits.
- `cli`: quiet/summary defaults, progress flag, status history limit.
- `search`: default limit, auto-enable for org/watch, embedding function override.

Example (abridged):

```yaml
llm:
  model: openai/gpt-4o
  api_base_url: null
  api_key: null
  temperature: 1.0
  max_tokens: 25000

processing:
  process_images: true
  preview_char_limit: 2048
  recurse_directories: false
  watch:
    debounce_seconds: 2.0
    allow_deletions: false

search:
  default_limit: 5
  auto_enable_org: true
  auto_enable_watch: true
  embedding_function: null
```

See SPEC.md for the full configuration reference and defaults.

