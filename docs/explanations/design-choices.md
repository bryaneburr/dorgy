# Design Choices

- Per-collection search stores keep semantic indexes portable.
- Deletion guard avoids destructive surprises in watch mode; suppressed deletions surface as notes/JSON.
- CLI helpers centralize quiet/summary/JSON behavior and standardized error payloads.
- Lazy CLI imports keep startup snappy and improve testability.
- Persistent `document_id`s allow stable references across rename/move/undo flows.

See ARCH.md and SPEC.md for deeper rationale and trade-offs.

