"""Planner for organization operations."""

from __future__ import annotations

from typing import Iterable

from dorgy.classification.models import ClassificationDecision
from dorgy.ingestion.models import FileDescriptor

from .models import OperationPlan


class OrganizerPlanner:
    """Derive operation plans from descriptors and classification decisions."""

    def build_plan(
        self,
        descriptors: Iterable[FileDescriptor],
        decisions: Iterable[ClassificationDecision | None],
    ) -> OperationPlan:
        """Produce an operation plan (placeholder)."""

        raise NotImplementedError("OrganizerPlanner.build_plan will be implemented in Phase 4.")
