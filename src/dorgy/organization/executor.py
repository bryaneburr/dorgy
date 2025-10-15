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

        self._persist_plan(plan, root)

    def rollback(self, root: Path) -> None:
        """Rollback the last applied plan."""

        plan = self._last_plan or self._load_plan(root)
        if plan is None:
            raise RuntimeError("No organization plan available for rollback.")

        for move_op in reversed(plan.moves):
            if move_op.destination.exists():
                move_op.destination.rename(move_op.source)

        for rename_op in reversed(plan.renames):
            if rename_op.destination.exists():
                rename_op.destination.rename(rename_op.source)

        self._persist_plan(None, root)
        self._last_plan = None

    def _validate(self, plan: OperationPlan, root: Path) -> None:
        predicted_sources = {rename_op.destination for rename_op in plan.renames}

        for rename_op in plan.renames:
            self._validate_path(rename_op.source, root)
        for move_op in plan.moves:
            if not move_op.source.exists() and move_op.source in predicted_sources:
                continue
            self._validate_path(move_op.source, root)

    def _validate_path(self, source: Path, root: Path) -> None:
        if not source.exists():
            raise FileNotFoundError(f"Source path is missing: {source}")
        if root not in source.parents and source != root:
            raise ValueError(f"Source path {source} is outside collection root {root}")

    def _persist_plan(self, plan: OperationPlan | None, root: Path) -> None:
        plan_path = self._plan_path(root)
        if plan is None:
            if plan_path.exists():
                plan_path.unlink()
            return
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    def _load_plan(self, root: Path) -> OperationPlan | None:
        plan_path = self._plan_path(root)
        if not plan_path.exists():
            return None
        return OperationPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))

    def _plan_path(self, root: Path) -> Path:
        return root / ".dorgy" / "last_plan.json"
