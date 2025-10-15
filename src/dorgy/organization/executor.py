"""Executor for organization plans."""

from __future__ import annotations

from pathlib import Path

from .models import OperationPlan


class OperationExecutor:
    """Apply operation plans with rollback support."""

    def apply(self, plan: OperationPlan, root: Path, dry_run: bool = False) -> None:
        """Apply the given plan (placeholder)."""

        raise NotImplementedError("OperationExecutor.apply will be implemented in Phase 4.")

    def rollback(self, root: Path) -> None:
        """Rollback the last applied plan (placeholder)."""

        raise NotImplementedError("OperationExecutor.rollback will be implemented in Phase 4.")
