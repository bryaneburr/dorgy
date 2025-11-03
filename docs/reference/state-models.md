# State Models (High-Level)

High-level fields referenced by CLI and automation contracts (subject to evolution):

- File record: path, hash, tags/categories, timestamps, persistent `document_id`.
- Collection state: files mapping, `search` enablement and schema/version metadata.
- History events: operation, source/destination, notes, timestamps.

Exact internal classes may change; rely on CLI/JSON contracts for automation.

