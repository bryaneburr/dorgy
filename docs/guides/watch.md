# Guide: Watch

`dorgy watch` runs the same pipeline continuously, batching changes with debouncing and surfacing JSON summaries for automation.

Examples:

```bash
dorgy watch . --once --json
dorgy watch ./inbox -r --allow-deletions
```

Notes:

- Deletions are guarded by `processing.watch.allow_deletions` / `--allow-deletions`.
  - When not allowed, deletions are suppressed and surfaced as notes/JSON entries.
- Search mirrors `org`: indexes update by default unless `--without-search` is passed (or config disables it).
- JSON includes batch IDs, timing, counts, notes, and removal details.
