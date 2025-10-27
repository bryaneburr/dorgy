# SEARCH COORDINATION NOTES

- `SearchIndex` always targets `<collection>/.dorgy/chroma` and keeps a peer manifest at `<collection>/.dorgy/search.json`; never write to global `~/.dorgy` locations so collections stay portable.
- Use `SearchEntry.from_record` (or equivalent helpers) to ensure `FileRecord.document_id`, tags, categories, needs-review flags, and timestamps are normalized consistently before talking to Chromadb. Text payloads must be sanitized via `normalize_search_text`.
- `SearchIndex` acquires a threading lock around Chromadb operations; reuse the instance for org/watch/mv/search flows instead of instantiating multiple clients per command.
- Inject custom Chromadb clients via the constructor’s `client_factory` in tests to avoid touching real persistence; unit tests must cover manifest updates for both upsert and delete paths.
- Configuration defaults live under `config.search.*` (default limit, auto-enable toggles, optional embedding function). Keep CLI flags and docs aligned with these settings and deprecate `cli.search_default_limit` by reading it only when the new block is unset.
- When adding lifecycle commands (`--with-search`, `--init-store`, `--drop-store`, etc.), update SPEC/README/ARCH plus this file so automation consumers know how to initialize or audit the index.
