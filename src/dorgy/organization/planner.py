"""Planner for organization operations."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Optional

from dorgy.classification.models import ClassificationDecision
from dorgy.ingestion.models import FileDescriptor

from .models import MetadataOperation, MoveOperation, OperationPlan, RenameOperation


class OrganizerPlanner:
    """Derive operation plans from descriptors and classification decisions."""

    def build_plan(
        self,
        descriptors: Iterable[FileDescriptor],
        decisions: Iterable[ClassificationDecision | None],
        *,
        rename_enabled: bool = True,
        root: Optional[Path] = None,
    ) -> OperationPlan:
        """Produce an operation plan based on descriptors and decisions.

        Args:
            descriptors: Ingestion descriptors from the pipeline.
            decisions: Classification decisions aligned with descriptors.
            rename_enabled: Indicates whether rename operations should be proposed.
            root: Optional collection root to confine destination paths.

        Returns:
            OperationPlan: Plan containing rename and metadata updates.
        """

        plan = OperationPlan()
        rename_targets: dict[Path, RenameOperation] = {}
        occupied_destinations: set[Path] = set()
        rename_map: dict[Path, Path] = {}

        for descriptor, decision in zip(descriptors, decisions, strict=False):
            if decision is None:
                continue

            rename = self._build_rename(
                descriptor.path,
                decision.rename_suggestion,
                rename_enabled,
                root,
                occupied_destinations,
            )
            if rename is not None:
                plan.renames.append(rename)
                rename_targets[descriptor.path] = rename
                rename_map[descriptor.path] = rename.destination
                occupied_destinations.add(rename.destination)

        for descriptor, decision in zip(descriptors, decisions, strict=False):
            if decision is None:
                continue

            metadata_path = rename_map.get(descriptor.path, descriptor.path)
            metadata = self._build_metadata_operation(metadata_path, decision)
            if metadata is not None:
                plan.metadata_updates.append(metadata)

            move_op = self._build_move(
                descriptor.path,
                decision,
                rename_map,
                root,
                occupied_destinations,
            )
            if move_op is not None:
                plan.moves.append(move_op)
                occupied_destinations.add(move_op.destination)

        return plan

    # ------------------------------------------------------------------ #
    # Helpers                                                            #
    # ------------------------------------------------------------------ #

    def _build_rename(
        self,
        path: Path,
        suggestion: Optional[str],
        rename_enabled: bool,
        root: Optional[Path],
        existing: set[Path],
    ) -> Optional[RenameOperation]:
        if not rename_enabled or not suggestion:
            return None

        sanitized = self._sanitize_filename(suggestion)
        if not sanitized:
            return None

        candidate = path.with_name(f"{sanitized}{path.suffix}")
        resolved = self._resolve_conflict(path, candidate, root, existing)
        if resolved is None or resolved == path:
            return None

        return RenameOperation(
            source=path,
            destination=resolved,
            reasoning="Classification suggestion",
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

    def _build_move(
        self,
        source: Path,
        decision: ClassificationDecision,
        rename_map: dict[Path, Path],
        root: Optional[Path],
        occupied: set[Path],
    ) -> Optional[MoveOperation]:
        if root is None:
            return None

        category = decision.primary_category or "General"
        folder_name = self._sanitize_filename(category) or "general"
        target_dir = root / folder_name

        current_path = rename_map.get(source, source)
        if target_dir in current_path.parents:
            return None

        candidate = target_dir / current_path.name
        resolved = self._resolve_conflict(current_path, candidate, root, occupied)
        if resolved is None or resolved == current_path:
            return None

        return MoveOperation(
            source=current_path,
            destination=resolved,
            reasoning=f"Move to category folder '{folder_name}'",
        )

    def _sanitize_filename(self, value: str) -> str:
        normalized = value.strip().lower()
        normalized = re.sub(r"[^a-z0-9\-_. ]+", "", normalized)
        normalized = re.sub(r"[\s]+", "-", normalized)
        return normalized

    def _resolve_conflict(
        self,
        source: Path,
        candidate: Path,
        root: Optional[Path],
        occupied: set[Path],
    ) -> Optional[Path]:
        if candidate == source:
            return None

        counter = 1
        final_candidate = candidate
        while True:
            filesystem_conflict = final_candidate.exists()
            planned_conflict = final_candidate in occupied

            if not filesystem_conflict and not planned_conflict:
                break

            final_candidate = candidate.with_name(f"{candidate.stem}-{counter}{candidate.suffix}")
            counter += 1

        if root is not None and root not in final_candidate.parents:
            final_candidate = root / final_candidate.name

        return final_candidate
