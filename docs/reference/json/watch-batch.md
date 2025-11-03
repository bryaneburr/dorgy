# JSON: Watch Batch

`dorgy watch` emits a JSON payload per batch (or an array in `--once --json`). Typical fields:

```json
{
  "context": {
    "batch_id": "uuid",
    "started_at": "ISO-8601",
    "completed_at": "ISO-8601",
    "duration_seconds": 1.23,
    "llm": { "model": "...", "summary": "..." }
  },
  "counts": {
    "processed": 10,
    "needs_review": 1,
    "quarantined": 0,
    "renames": 3,
    "moves": 2,
    "deletes": 0,
    "conflicts": 0,
    "errors": 0
  },
  "notes": ["..."],
  "removals": [
    { "path": "...", "kind": "deleted|moved_out", "executed": false }
  ]
}
```

Notes surface Chromadb/indexing issues instead of failing the batch.

