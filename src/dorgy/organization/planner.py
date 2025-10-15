"""Planner for organization operations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from dorgy.classification.models import ClassificationDecision
from dorgy.ingestion.models import FileDescriptor

from .models import MetadataOperation, OperationPlan, RenameOperation


class OrganizerPlanner:
    """Derive operation plans from descriptors and classification decisions."""

    def build_plan(
        self,
        descriptors: Iterable[FileDescriptor],
        decisions: Iterable[ClassificationDecision | None],
        *,
        rename_enabled: bool = True,
    ) -> OperationPlan:
        """Produce an operation plan based on descriptors and decisions.

        Args:
            descriptors: Ingestion descriptors from the pipeline.
            decisions: Classification decisions aligned with descriptors.
            rename_enabled: Indicates whether rename operations should be proposed.

        Returns:
            OperationPlan: Plan containing rename and metadata updates.
        """

        plan = OperationPlan()

        for descriptor, decision in zip(descriptors, decisions, strict=False):
            if decision is None:
                continue

            rename = self._build_rename(descriptor.path, decision.rename_suggestion, rename_enabled)
            if rename is not None:
                plan.renames.append(rename)

            metadata = self._build_metadata_operation(descriptor.path, decision)
            if metadata is not None:
                plan.metadata_updates.append(metadata)

        return plan

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _build_rename(
        self,
        path: Path,
        suggestion: Optional[str],
        rename_enabled: bool,
    ) -> Optional[RenameOperation]:
        if not rename_enabled or not suggestion:
            return None

        sanitized = self._sanitize_filename(suggestion)
        if not sanitized:
            return None

        candidate = path.with_name(f"{sanitized}{path.suffix}")
        if candidate == path:
            return None

        return RenameOperation(
            source=path, destination=candidate, reasoning="Classification suggestion"
        )

    def _build_metadata_operation(
        self,
        path: Path,
        decision: ClassificationDecision,
    ) -> Optional[MetadataOperation]:
        additions = [decision.primary_category]
        additions.extend(decision.secondary_categories)
        additions.extend(decision.tags)

        additions = [value for value in dict.fromkeys(additions) if value]
        if not additions:
            return None

        return MetadataOperation(path=path, add=additions)

    def _sanitize_filename(self, value: str) -> str:
        normalized = value.strip().lower()
        normalized = re.sub(r"[^a-z0-9\-_. ]+", "", normalized)
        normalized = re.sub(r"[\s]+", "-", normalized)
        return normalized
