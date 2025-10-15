"""Tests for organization scaffolding."""

from pathlib import Path

from dorgy.classification.models import ClassificationDecision
from dorgy.ingestion.models import FileDescriptor
from dorgy.organization.executor import OperationExecutor
from dorgy.organization.models import OperationPlan, RenameOperation
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

    executor.apply(plan, root=tmp_path)

    assert not source.exists()
    assert destination.exists()


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
