# ORGANIZATION COORDINATION NOTES

- `OrganizerPlanner` maps classification decisions into rename and move operations; pass the collection root when building plans so conflict resolution stays within the target tree.
- `OperationExecutor` validates, applies, and persists plans to `.dorgy/last_plan.json`; use `rollback` to revert the latest applied plan (moves first, then renames).
- Conflict handling ensures both filesystem and planned destinations remain unique; update `tests/test_organization_scaffolding.py` when modifying conflict or undo semantics.
- CLI integration composes rename + move plans; avoid modifying descriptors in-place outside organized sections to keep state updates consistent.
