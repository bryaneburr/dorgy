# ORGANIZATION COORDINATION NOTES

- `OrganizerPlanner` maps classification decisions into rename and move operations; pass the collection root when building plans so conflict resolution stays within the target tree. The `conflict_strategy` argument should come from `organization.conflict_resolution` (`append_number`, `timestamp`, or `skip`), and `timestamp_provider` can be injected during tests for deterministic outputs.
- `OperationExecutor` validates, applies, and persists plans to `.dorgy/last_plan.json`; use `rollback` to revert the latest applied plan (moves first, then renames).
- Conflict handling ensures both filesystem and planned destinations remain unique and appends notes summarizing how collisions were resolved; update `tests/test_organization_scaffolding.py` when modifying conflict or undo semantics.
- CLI integration composes rename + move plans; avoid modifying descriptors in-place outside organized sections to keep state updates consistent.
- CLI prints `plan.notes` when present so contributors should keep messages concise and user-facing.
