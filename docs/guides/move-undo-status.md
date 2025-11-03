# Guide: Move, Undo, and Status

## Move (`dorgy mv`)

Move or rename tracked files while preserving history and search metadata.

```bash
dorgy mv path/to/file.pdf path/to/other/file.pdf
dorgy mv path/to/file.pdf moved/ --dry-run
```

Conflict strategies: `append_number` (default), `timestamp`, `skip`.
Search metadata refreshes in-place; no re-embedding. Warnings from Chromadb are emitted as notes.

## Status / Undo

Inspect prior plans and restore collections when needed.

```bash
dorgy status ./collection --json
dorgy undo ./collection --dry-run
dorgy undo ./collection
```

Undo uses snapshots under `.dorgy/` and updates state/history accordingly.
