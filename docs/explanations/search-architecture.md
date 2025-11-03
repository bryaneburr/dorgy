# Search Architecture

Search is built on Chromadb and managed per collection under `.dorgy/chroma`, with a manifest `.dorgy/search.json` and `state.search` metadata tracking enablement and timestamps.

- `dorgy org` auto-enables indexing unless `--without-search` is passed.
- `dorgy watch` mirrors the lifecycle; batches update the index by default.
- `dorgy mv` refreshes path metadata in-place without re-embedding, preserving `document_id`s.
- CLI surfaces warnings via notes instead of failing runs when Chromadb is unavailable.

See SPEC.md Phase 7 for the full plan and CLI expectations.

