# Quickstart

```bash
# Inspect available commands
dorgy --help

# Organize a directory in place (dry run first)
dorgy org ./documents --dry-run
dorgy org ./documents

# Monitor a directory and emit JSON batches
dorgy watch ./inbox --json --once

# Undo the latest plan
dorgy undo ./documents --dry-run
dorgy status ./documents --json
```

Tip: If you prefer `uv`, you can prefix commands with `uv run`.
