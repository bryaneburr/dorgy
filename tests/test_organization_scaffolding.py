"""Tests for organization scaffolding."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from dorgy.classification.models import ClassificationDecision
from dorgy.ingestion.models import FileDescriptor
from dorgy.organization.executor import OperationExecutor
from dorgy.organization.models import MoveOperation, OperationPlan, RenameOperation
from dorgy.organization.planner import OrganizerPlanner


def test_operation_plan_defaults() -> None:
    plan = OperationPlan()
    assert plan.renames == []
    assert plan.moves == []
    assert plan.metadata_updates == []
    assert plan.notes == []


def test_planner_not_implemented() -> None:
    planner = OrganizerPlanner()
    descriptor = FileDescriptor(
        path=Path("/tmp/report.txt"),
        display_name="report.txt",
        mime_type="text/plain",
        hash="abc",
    )
    decision = ClassificationDecision(
        primary_category="Finance", tags=["Finance"], rename_suggestion="report-2024"
    )

    plan = planner.build_plan([descriptor], [decision], rename_enabled=True)

    assert plan.renames[0].destination.name == "report-2024.txt"
    assert "Finance" in plan.metadata_updates[0].add


def test_executor_applies_rename(tmp_path: Path) -> None:
    source = tmp_path / "old.txt"
    source.write_text("content", encoding="utf-8")
    destination = tmp_path / "new.txt"

    plan = OperationPlan(renames=[RenameOperation(source=source, destination=destination)])
    executor = OperationExecutor()

    events = executor.apply(plan, root=tmp_path)

    assert not source.exists()
    assert destination.exists()
    assert len(events) == 1
    event = events[0]
    assert event.operation == "rename"
    assert event.source == "old.txt"
    assert event.destination == "new.txt"
    assert event.conflict_applied is False


def test_executor_rollback_on_failure(tmp_path: Path) -> None:
    source = tmp_path / "file.txt"
    source.write_text("data", encoding="utf-8")
    conflict = tmp_path / "conflict.txt"
    conflict.write_text("existing", encoding="utf-8")

    plan = OperationPlan(
        renames=[RenameOperation(source=source, destination=conflict)],
    )

    executor = OperationExecutor()

    with pytest.raises(FileExistsError):
        executor.apply(plan, root=tmp_path)

    assert source.exists()
    assert conflict.read_text(encoding="utf-8") == "existing"
    staging_root = tmp_path / ".dorgy" / "staging"
    if staging_root.exists():
        assert not any(staging_root.iterdir())


def test_planner_resolves_conflicts(tmp_path: Path) -> None:
    original = tmp_path / "doc.txt"
    original.write_text("content", encoding="utf-8")
    other = tmp_path / "other.txt"
    other.write_text("content", encoding="utf-8")

    existing = tmp_path / "report.txt"
    existing.write_text("existing", encoding="utf-8")

    descriptors = [
        FileDescriptor(path=original, display_name="doc.txt", mime_type="text/plain", hash="1"),
        FileDescriptor(path=other, display_name="other.txt", mime_type="text/plain", hash="2"),
    ]
    decisions = [
        ClassificationDecision(primary_category="Docs", rename_suggestion="report"),
        ClassificationDecision(primary_category="Docs", rename_suggestion="report"),
    ]

    planner = OrganizerPlanner()
    plan = planner.build_plan(descriptors, decisions, rename_enabled=True, root=tmp_path)

    destinations = {rename.destination.name for rename in plan.renames}
    assert destinations == {"report-1.txt", "report-2.txt"}
    assert all(rename.conflict_applied for rename in plan.renames)
    assert {rename.conflict_strategy for rename in plan.renames} == {"append_number"}


def test_planner_skip_conflict_policy(tmp_path: Path) -> None:
    original = tmp_path / "doc.txt"
    original.write_text("content", encoding="utf-8")
    existing = tmp_path / "report.txt"
    existing.write_text("existing", encoding="utf-8")

    descriptor = FileDescriptor(
        path=original,
        display_name="doc.txt",
        mime_type="text/plain",
        hash="1",
    )
    decision = ClassificationDecision(primary_category="Docs", rename_suggestion="report")

    planner = OrganizerPlanner()
    plan = planner.build_plan(
        [descriptor],
        [decision],
        rename_enabled=True,
        root=tmp_path,
        conflict_strategy="skip",
    )

    assert plan.renames == []
    assert any("skip" in note.lower() for note in plan.notes)


def test_planner_timestamp_conflict_policy(tmp_path: Path) -> None:
    original = tmp_path / "doc.txt"
    original.write_text("content", encoding="utf-8")
    existing = tmp_path / "report.txt"
    existing.write_text("existing", encoding="utf-8")

    descriptor = FileDescriptor(
        path=original,
        display_name="doc.txt",
        mime_type="text/plain",
        hash="1",
    )
    decision = ClassificationDecision(primary_category="Docs", rename_suggestion="report")

    planner = OrganizerPlanner()
    fixed_timestamp = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    plan = planner.build_plan(
        [descriptor],
        [decision],
        rename_enabled=True,
        root=tmp_path,
        conflict_strategy="timestamp",
        timestamp_provider=lambda: fixed_timestamp,
    )

    assert plan.renames[0].destination.name == "report-20240101-120000.txt"
    assert any("timestamp" in note.lower() for note in plan.notes)
    assert plan.renames[0].conflict_applied is True
    assert plan.renames[0].conflict_strategy == "timestamp"


def test_executor_rollback(tmp_path: Path) -> None:
    source = tmp_path / "file.txt"
    source.write_text("data", encoding="utf-8")
    rename_dest = tmp_path / "file-renamed.txt"
    move_dest = tmp_path / "folder" / "file-renamed.txt"

    plan = OperationPlan(
        renames=[RenameOperation(source=source, destination=rename_dest)],
        moves=[MoveOperation(source=rename_dest, destination=move_dest)],
    )

    executor = OperationExecutor()
    executor.apply(plan, root=tmp_path)

    assert move_dest.exists()
    assert not source.exists()

    executor.rollback(tmp_path)

    assert source.exists()
    assert not move_dest.exists()
    assert not rename_dest.exists()
    assert not (tmp_path / ".dorgy" / "last_plan.json").exists()
