# JSON: Search Results

Search results include state-derived filters and, when the index is enabled, Chromadb data.

Key fields:

- `document_id` — persistent identifier stable across org/watch/mv/undo flows.
- `score` — similarity score for semantic results (optional).
- `snippet` — excerpt from the indexed document payload (optional).

Index lifecycle is managed per collection under `.dorgy/chroma` with a manifest at `.dorgy/search.json`.

