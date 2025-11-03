# JSON: Errors

Commands emit standardized JSON errors when `--json` is active.

Shape:

```json
{
  "error": {
    "code": "string",
    "message": "human-readable",
    "details": { "optional": "structured metadata" }
  }
}
```

Common codes: `config_error`, `missing_state`, `cli_error`, `internal_error`, `llm_unavailable`, `llm_response_error`, `watch_runtime_error`.

Source: `src/dorgy/cli/helpers/messages.py` (`_handle_cli_error`).

