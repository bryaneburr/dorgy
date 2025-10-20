"""Executor for organization plans with staging safeguards."""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal

from dorgy.state import OperationEvent

from .models import MoveOperation, OperationPlan, RenameOperation


@dataclass
class _StagedFile:
    """Track staging metadata for an individual file mutation."""

    original: Path
    stage: Path
    current_location: Path


class OperationExecutor:
    """Apply operation plans with staging and rollback support."""

    def __init__(
        self,
        staging_root: Path | None = None,
        *,
        copy_mode: bool = False,
        source_root: Path | None = None,
    ) -> None:
        self._last_plan: OperationPlan | None = None
        self._staging_root = staging_root
        self._copy_mode = copy_mode
        self._source_root = source_root.resolve() if source_root is not None else None

    def apply(
        self,
        plan: OperationPlan,
        root: Path,
        dry_run: bool = False,
    ) -> list[OperationEvent]:
        """Apply the given plan by executing rename/move operations.

        Args:
            plan: Operation plan computed by the planner.
            root: Collection root path.
            dry_run: When true, only validate operations without executing them.

        Returns:
            list[OperationEvent]: History events describing applied operations.
        """

        self._last_plan = plan
        self._validate(plan, root)

        if dry_run or (not plan.renames and not plan.moves):
            return []

        session_dir = self._prepare_session(root)
        staged_files: dict[Path, _StagedFile] = {}
        original_for_path: dict[Path, Path] = {}
        for rename_op in plan.renames:
            original_for_path[rename_op.destination] = rename_op.source

        move_originals: dict[Path, MoveOperation] = {}
        for move_op in plan.moves:
            original_source = original_for_path.get(move_op.source, move_op.source)
            move_originals[original_source] = move_op

        sources = {op.source for op in plan.renames}
        sources.update(move_originals.keys())

        try:
            for original in sources:
                stage_path = self._stage_file(original, root, session_dir)
                staged_files[original] = _StagedFile(
                    original=original,
                    stage=stage_path,
                    current_location=stage_path,
                )

            events: list[OperationEvent] = []

            # Apply rename operations from staged files to their destinations.
            for rename_op in plan.renames:
                entry = staged_files.get(rename_op.source)
                if entry is None:
                    continue
                self._move_file(entry.current_location, rename_op.destination)
                entry.current_location = rename_op.destination
                events.append(
                    self._create_event(
                        operation="rename",
                        source=rename_op.source,
                        destination=rename_op.destination,
                        root=root,
                        conflict_strategy=rename_op.conflict_strategy,
                        conflict_applied=rename_op.conflict_applied,
                        notes=self._notes_from_operation(rename_op),
                    )
                )

            # Apply move operations from their current location to final destinations.
            for original, move_op in move_originals.items():
                entry = staged_files[original]
                self._move_file(entry.current_location, move_op.destination)
                entry.current_location = move_op.destination
                events.append(
                    self._create_event(
                        operation="move",
                        source=move_op.source,
                        destination=move_op.destination,
                        root=root,
                        conflict_strategy=move_op.conflict_strategy,
                        conflict_applied=move_op.conflict_applied,
                        notes=self._notes_from_operation(move_op),
                    )
                )

            self._persist_plan(plan, root)
            return events
        except Exception:
            self._restore_staged_files(staged_files)
            raise
        finally:
            self._cleanup_session(session_dir)

    def rollback(
        self,
        root: Path,
        *,
        preserved_directories: Iterable[str] | None = None,
    ) -> None:
        """Rollback the last applied plan."""

        plan = self._last_plan or self._load_plan(root)
        if plan is None:
            raise RuntimeError("No organization plan available for rollback.")

        preserved: set[Path] = set()
        if preserved_directories:
            root_resolved = root.resolve()
            for entry in preserved_directories:
                if not entry:
                    continue
                relative = Path(entry)
                if relative.is_absolute():
                    continue
                candidate = (root_resolved / relative).resolve()
                try:
                    candidate.relative_to(root_resolved)
                except ValueError:
                    continue
                preserved.add(candidate)

        candidate_dirs: set[Path] = set()
        for move_op in plan.moves:
            candidate_dirs.update(self._directories_to_prune(move_op.destination, root))
        for rename_op in plan.renames:
            candidate_dirs.update(self._directories_to_prune(rename_op.destination, root))

        for move_op in reversed(plan.moves):
            if move_op.destination.exists():
                move_op.destination.rename(move_op.source)

        for rename_op in reversed(plan.renames):
            if rename_op.destination.exists():
                rename_op.destination.rename(rename_op.source)

        self._remove_empty_directories(candidate_dirs, root, preserved)
        self._persist_plan(None, root)
        self._last_plan = None

    def _prepare_session(self, root: Path) -> Path:
        base = self._staging_root or (root / ".dorgy" / "staging")
        base.mkdir(parents=True, exist_ok=True)
        session_dir = base / uuid.uuid4().hex
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def _stage_file(self, source: Path, root: Path, session_dir: Path) -> Path:
        try:
            relative_path = source.resolve().relative_to(root.resolve())
        except ValueError:
            relative_path = Path(source.name)
        stage_path = session_dir / relative_path
        stage_path.parent.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            raise FileNotFoundError(f"Source path is missing: {source}")
        counter = 1
        candidate = stage_path
        while candidate.exists():
            candidate = stage_path.with_name(f"{stage_path.stem}-{counter}{stage_path.suffix}")
            counter += 1
        stage_path = candidate
        if self._copy_mode:
            shutil.copy2(source, stage_path)
        else:
            source.rename(stage_path)
        return stage_path

    def _move_file(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination != source:
            raise FileExistsError(f"Destination already exists: {destination}")
        source.rename(destination)

    def _restore_staged_files(self, staged_files: dict[Path, _StagedFile]) -> None:
        for entry in staged_files.values():
            if self._copy_mode:
                for candidate in [entry.current_location, entry.stage]:
                    if candidate.exists():
                        candidate.unlink()
            else:
                for candidate in [entry.current_location, entry.stage]:
                    if candidate.exists():
                        candidate.rename(entry.original)
                        break

    def _cleanup_session(self, session_dir: Path) -> None:
        if session_dir.exists():
            shutil.rmtree(session_dir, ignore_errors=True)

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
        roots = [root.resolve()]
        if self._source_root is not None:
            roots.append(self._source_root)
        if not any(r in source.resolve().parents or source.resolve() == r for r in roots):
            raise ValueError(
                f"Source path {source} is outside managed roots: {', '.join(str(r) for r in roots)}"
            )

    def _create_event(
        self,
        *,
        operation: Literal["rename", "move"],
        source: Path,
        destination: Path,
        root: Path,
        conflict_strategy: str | None,
        conflict_applied: bool,
        notes: Iterable[str] | None,
    ) -> OperationEvent:
        timestamp = datetime.now(timezone.utc)
        note_list = list(notes or [])
        return OperationEvent(
            timestamp=timestamp,
            operation=operation,
            source=self._relative_path(source, root),
            destination=self._relative_path(destination, root),
            conflict_strategy=conflict_strategy,
            conflict_applied=conflict_applied,
            notes=note_list,
        )

    def _notes_from_operation(self, operation: RenameOperation | MoveOperation) -> list[str]:
        if operation.reasoning:
            return [operation.reasoning]
        return []

    def _relative_path(self, path: Path, root: Path) -> str:
        try:
            return str(path.resolve().relative_to(root.resolve()))
        except ValueError:
            return str(path.resolve())

    def _directories_to_prune(self, path: Path, root: Path) -> set[Path]:
        directories: set[Path] = set()
        root_resolved = root.resolve()
        current = path.resolve().parent
        while True:
            try:
                current.relative_to(root_resolved)
            except ValueError:
                break
            if current == root_resolved:
                break
            directories.add(current)
            current = current.parent
        return directories

    def _remove_empty_directories(
        self,
        candidates: set[Path],
        root: Path,
        preserved: set[Path],
    ) -> None:
        if not candidates:
            return

        root_resolved = root.resolve()
        ordered = sorted(
            {candidate.resolve() for candidate in candidates},
            key=lambda path: len(path.parts),
            reverse=True,
        )
        for directory in ordered:
            if directory in preserved:
                continue
            try:
                directory.relative_to(root_resolved)
            except ValueError:
                continue
            if directory == root_resolved:
                continue
            try:
                directory.rmdir()
            except OSError:
                continue

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
