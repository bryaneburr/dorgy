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

## How batching handles bursty changes

- The watcher queues every filesystem event and flushes them in batches after a short debounce window (or when the batch hits the configured size/interval), so adding ten files rapidly produces one organized batch instead of ten separate runs.
- Each time a batch is about to run, the service re-validates that every candidate file still exists on disk. If a file was deleted or moved again while waiting in the queue, it simply drops out instead of raising an error.
- Move and delete events always generate `removals` entries in the CLI/JSON payload. Those entries capture whether the removal was executed, the reason (deleted, moved within, moved out), and—when deletions are disabled—the suppression cause so automation can react.
