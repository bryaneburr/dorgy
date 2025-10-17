"""Planner for organization operations."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Iterable, Optional

from dorgy.classification.models import ClassificationDecision
from dorgy.ingestion.models import FileDescriptor

from .models import MetadataOperation, MoveOperation, OperationPlan, RenameOperation


@dataclass
class _ConflictResolutionResult:
    """Container describing the outcome of a conflict resolution attempt."""

    destination: Path | None
    skipped: bool = False
    conflict_applied: bool = False
    note: Optional[str] = None


class OrganizerPlanner:
    """Derive operation plans from descriptors and classification decisions."""

    def build_plan(
        self,
        descriptors: Iterable[FileDescriptor],
        decisions: Iterable[ClassificationDecision | None],
        *,
        rename_enabled: bool = True,
        root: Optional[Path] = None,
        conflict_strategy: str = "append_number",
        timestamp_provider: Optional[Callable[[], datetime]] = None,
        destination_map: Optional[Dict[Path, Path]] = None,
    ) -> OperationPlan:
        """Produce an operation plan based on descriptors and decisions.

        Args:
            descriptors: Ingestion descriptors from the pipeline.
            decisions: Classification decisions aligned with descriptors.
            rename_enabled: Indicates whether rename operations should be proposed.
            root: Optional collection root to confine destination paths.
            conflict_strategy: Strategy used to resolve naming collisions.
            timestamp_provider: Callable returning the current timestamp for
                timestamp-based conflict resolution. Defaults to UTC `datetime.now`.
            destination_map: Optional mapping of descriptor paths to desired destinations
                (relative to ``root``). When provided, the planner prefers these targets
                over category-based placement.

        Returns:
            OperationPlan: Plan containing rename and metadata updates.
        """

        plan = OperationPlan()
        normalized_strategy = (conflict_strategy or "append_number").lower()
        if normalized_strategy not in {"append_number", "timestamp", "skip"}:
            normalized_strategy = "append_number"
        rename_targets: dict[Path, RenameOperation] = {}
        occupied_destinations: set[Path] = set()
        rename_map: dict[Path, Path] = {}
        effective_timestamp_provider = timestamp_provider or (lambda: datetime.now(timezone.utc))

        descriptor_list = list(descriptors)
        decision_list = list(decisions)

        if destination_map and root is not None:
            normalized_map: dict[Path, Path] = {}
            for descriptor in descriptor_list:
                dest = destination_map.get(descriptor.path)
                if dest is None:
                    continue
                if dest.is_absolute():
                    try:
                        dest = dest.relative_to(root)
                    except ValueError:
                        dest = dest.relative_to(dest.anchor)
                normalized_map[descriptor.path] = (root / dest).resolve()

            # Metadata updates referencing final destinations.
            for index, descriptor in enumerate(descriptor_list):
                decision = decision_list[index] if index < len(decision_list) else None
                if decision is None:
                    continue
                metadata_path = normalized_map.get(descriptor.path, descriptor.path)
                metadata = self._build_metadata_operation(metadata_path, decision)
                if metadata is not None:
                    plan.metadata_updates.append(metadata)

            for descriptor in descriptor_list:
                target = normalized_map.get(descriptor.path)
                if target is None:
                    continue
                resolution = self._resolve_conflict(
                    descriptor.path,
                    target,
                    root,
                    occupied_destinations,
                    normalized_strategy,
                    effective_timestamp_provider,
                )
                destination = resolution.destination
                if destination is None or destination == descriptor.path:
                    continue
                plan.moves.append(
                    MoveOperation(
                        source=descriptor.path,
                        destination=destination,
                        reasoning="Structure planner proposal",
                        conflict_strategy=normalized_strategy,
                        conflict_applied=resolution.conflict_applied,
                    )
                )
                occupied_destinations.add(destination)
                if resolution.note:
                    plan.notes.append(resolution.note)
            return plan

        for descriptor, decision in zip(descriptor_list, decision_list, strict=False):
            if decision is None:
                continue

            rename, note = self._build_rename(
                descriptor.path,
                decision.rename_suggestion,
                rename_enabled,
                root,
                occupied_destinations,
                normalized_strategy,
                effective_timestamp_provider,
            )
            if rename is not None:
                plan.renames.append(rename)
                rename_targets[descriptor.path] = rename
                rename_map[descriptor.path] = rename.destination
                occupied_destinations.add(rename.destination)
            if note is not None:
                plan.notes.append(note)

        for descriptor, decision in zip(descriptors, decisions, strict=False):
            if decision is None:
                continue

            metadata_path = rename_map.get(descriptor.path, descriptor.path)
            metadata = self._build_metadata_operation(metadata_path, decision)
            if metadata is not None:
                plan.metadata_updates.append(metadata)

            move_op, note = self._build_move(
                descriptor.path,
                decision,
                rename_map,
                root,
                occupied_destinations,
                normalized_strategy,
                effective_timestamp_provider,
            )
            if move_op is not None:
                plan.moves.append(move_op)
                occupied_destinations.add(move_op.destination)
            if note is not None:
                plan.notes.append(note)

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
        strategy: str,
        timestamp_provider: Callable[[], datetime],
    ) -> tuple[Optional[RenameOperation], Optional[str]]:
        """Construct a rename operation when a suggestion is available.

        Args:
            path: Original path for the descriptor.
            suggestion: Suggested filename produced by classification.
            rename_enabled: Whether renames are permitted.
            root: Optional collection root.
            existing: Destinations already claimed by planned operations.
            strategy: Conflict resolution strategy to employ.
            timestamp_provider: Callable returning the current timestamp.

        Returns:
            Tuple containing a potential rename operation and an optional note.
        """

        if not rename_enabled or not suggestion:
            return None, None

        suffix = path.suffix
        suggestion = suggestion.strip()
        if suffix and suggestion.lower().endswith(suffix.lower()):
            suggestion = suggestion[: -len(suffix)]

        sanitized = self._sanitize_filename(suggestion)
        if not sanitized:
            return None, None

        candidate = path.with_name(f"{sanitized}{path.suffix}")
        resolution = self._resolve_conflict(
            path,
            candidate,
            root,
            existing,
            strategy,
            timestamp_provider,
        )
        if resolution.destination is None or resolution.destination == path:
            return None, resolution.note

        reasoning = "Classification suggestion"
        if resolution.conflict_applied:
            reasoning = f"{reasoning} (resolved via {strategy})"

        return RenameOperation(
            source=path,
            destination=resolution.destination,
            reasoning=reasoning,
            conflict_strategy=strategy,
            conflict_applied=resolution.conflict_applied,
        ), resolution.note

    def _build_metadata_operation(
        self,
        path: Path,
        decision: ClassificationDecision,
    ) -> Optional[MetadataOperation]:
        """Create metadata updates derived from the classification decision.

        Args:
            path: Path the metadata should be associated with.
            decision: Classification decision supplying tag/category information.

        Returns:
            MetadataOperation or ``None`` if no additions are needed.
        """

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
        strategy: str,
        timestamp_provider: Callable[[], datetime],
    ) -> tuple[Optional[MoveOperation], Optional[str]]:
        """Construct a move operation into the category folder when applicable.

        Args:
            source: Original descriptor path before renames/moves.
            decision: Classification decision for the descriptor.
            rename_map: Mapping of original paths to rename destinations.
            root: Collection root path.
            occupied: Destinations already claimed by operations.
            strategy: Conflict resolution strategy to employ.
            timestamp_provider: Callable returning the current timestamp.

        Returns:
            Tuple containing a move operation and an optional note.
        """

        if root is None:
            return None, None

        category = decision.primary_category or "General"
        folder_name = self._sanitize_filename(category) or "general"
        target_dir = root / folder_name

        current_path = rename_map.get(source, source)
        if target_dir in current_path.parents:
            return None, None

        candidate = target_dir / current_path.name
        resolution = self._resolve_conflict(
            current_path,
            candidate,
            root,
            occupied,
            strategy,
            timestamp_provider,
        )
        if resolution.destination is None or resolution.destination == current_path:
            return None, resolution.note

        reasoning = f"Move to category folder '{folder_name}'"
        if resolution.conflict_applied:
            reasoning = f"{reasoning} (resolved via {strategy})"

        return MoveOperation(
            source=current_path,
            destination=resolution.destination,
            reasoning=reasoning,
            conflict_strategy=strategy,
            conflict_applied=resolution.conflict_applied,
        ), resolution.note

    def _sanitize_filename(self, value: str) -> str:
        """Sanitize classification suggestions for filesystem usage."""

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
        strategy: str,
        timestamp_provider: Callable[[], datetime],
    ) -> _ConflictResolutionResult:
        """Resolve potential naming conflicts for a proposed destination path.

        Args:
            source: Original source path for the operation.
            candidate: Desired destination path.
            root: Optional collection root used to confine outputs.
            occupied: Destinations already reserved by the plan.
            strategy: Conflict resolution policy to apply.
            timestamp_provider: Callable returning the current timestamp.

        Returns:
            `_ConflictResolutionResult` capturing the chosen destination, whether an
            operation was skipped, and optional notes describing the resolution.
        """

        if candidate == source:
            return _ConflictResolutionResult(destination=None)

        conflict_applied = False
        base_candidate = candidate
        final_candidate = candidate
        counter = 1
        timestamp_applied = False

        while True:
            filesystem_conflict = final_candidate.exists()
            planned_conflict = final_candidate in occupied

            if not filesystem_conflict and not planned_conflict:
                break

            conflict_applied = True

            if strategy == "skip":
                note = f"Skipped operation for {source} due to conflict policy 'skip'."
                return _ConflictResolutionResult(destination=None, skipped=True, note=note)

            if strategy == "timestamp" and not timestamp_applied:
                timestamp_applied = True
                timestamp_value = timestamp_provider()
                if timestamp_value.tzinfo is None:
                    timestamp_value = timestamp_value.replace(tzinfo=timezone.utc)
                else:
                    timestamp_value = timestamp_value.astimezone(timezone.utc)
                suffix = timestamp_value.strftime("%Y%m%d-%H%M%S")
                base_candidate = candidate.with_name(f"{candidate.stem}-{suffix}{candidate.suffix}")
                final_candidate = base_candidate
                continue

            final_candidate = base_candidate.with_name(
                f"{base_candidate.stem}-{counter}{base_candidate.suffix}"
            )
            counter += 1

        if root is not None and root not in final_candidate.parents:
            final_candidate = root / final_candidate.name

        note_text: str | None = None
        if conflict_applied:
            note_text = f"Resolved conflict for {source} -> {final_candidate} using '{strategy}'."

        return _ConflictResolutionResult(
            destination=final_candidate,
            conflict_applied=conflict_applied,
            note=note_text,
        )
