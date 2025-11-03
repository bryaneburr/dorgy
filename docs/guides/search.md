# Guide: Search

Search is per-collection and lives under `<collection>/.dorgy/chroma` with a manifest at `<collection>/.dorgy/search.json`.

Quick usage:

```bash
# Substring search
dorgy search some/folder --contains "invoice"

# Semantic similarity (requires index)
dorgy search some/folder --search "tax return 2022"

# Initialize or rebuild the local store
dorgy search some/folder --init-store
dorgy search some/folder --reindex

# Drop the store and fall back to state-only filtering
dorgy search some/folder --drop-store
```

Results include persistent `document_id`s and optional similarity scores/snippets. Index lifecycle warnings are surfaced via CLI notes and JSON payloads rather than failing silently.
