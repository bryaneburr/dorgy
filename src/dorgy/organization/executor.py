"""Executor for organization plans."""

from __future__ import annotations

from pathlib import Path

from .models import OperationPlan


class OperationExecutor:
    """Apply operation plans with rollback support."""

    def __init__(self) -> None:
        self._last_plan: OperationPlan | None = None

    def apply(self, plan: OperationPlan, root: Path, dry_run: bool = False) -> None:
        """Apply the given plan by executing rename/move operations.

        Args:
            plan: Operation plan computed by the planner.
            root: Collection root path.
            dry_run: When true, only validate operations without executing them.
        """

        self._last_plan = plan

        if dry_run:
            self._validate(plan, root)
            return

        self._validate(plan, root)

        for rename_op in plan.renames:
            destination_parent = rename_op.destination.parent
            destination_parent.mkdir(parents=True, exist_ok=True)
            if rename_op.destination.exists() and rename_op.destination != rename_op.source:
                raise FileExistsError(f"Destination already exists: {rename_op.destination}")
            rename_op.source.rename(rename_op.destination)

        # Move operations are treated similarly to renames but include directory changes.
        for move_op in plan.moves:
            destination_parent = move_op.destination.parent
            destination_parent.mkdir(parents=True, exist_ok=True)
            if move_op.destination.exists() and move_op.destination != move_op.source:
                raise FileExistsError(f"Destination already exists: {move_op.destination}")
            move_op.source.rename(move_op.destination)

    def rollback(self, root: Path) -> None:
        """Rollback the last applied plan (placeholder)."""

        raise NotImplementedError("OperationExecutor.rollback will be implemented in Phase 4.")

    def _validate(self, plan: OperationPlan, root: Path) -> None:
        for rename_op in plan.renames:
            self._validate_path(rename_op.source, root)
        for move_op in plan.moves:
            self._validate_path(move_op.source, root)

    def _validate_path(self, source: Path, root: Path) -> None:
        if not source.exists():
            raise FileNotFoundError(f"Source path is missing: {source}")
        if root not in source.parents and source != root:
            raise ValueError(f"Source path {source} is outside collection root {root}")
