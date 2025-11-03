# JSON: Move (`dorgy mv`)

Example payload (abridged):

```json
{
  "context": {
    "root": "/abs/collection",
    "source": ".../old.pdf",
    "requested_destination": ".../new.pdf",
    "resolved_destination": ".../new.pdf",
    "strategy": "append_number|timestamp|skip",
    "dry_run": false,
    "skipped": false
  },
  "counts": { "moved": 1, "skipped": 0, "conflicts": 0, "changes": 1 },
  "plan": { "moves": [/* planned operation */], "notes": [] },
  "changes": [ { "from": "old/key", "to": "new/key" } ],
  "notes": ["optional"],
  "history": [ /* OperationEvent entries */ ],
  "state": { "path": "/abs/collection/.dorgy/state.json", "files_tracked": 42 }
}
```

See `src/dorgy/cli/commands/mv.py` for field details and `helpers/messages.py` for shared error/summary behavior.

