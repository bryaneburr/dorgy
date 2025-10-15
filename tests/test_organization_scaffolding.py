"""Tests for organization scaffolding."""

from pathlib import Path

import pytest

from dorgy.organization.models import MetadataOperation, MoveOperation, OperationPlan, RenameOperation
from dorgy.organization.planner import OrganizerPlanner


def test_operation_plan_defaults() -> None:
    plan = OperationPlan()
    assert plan.renames == []
    assert plan.moves == []
    assert plan.metadata_updates == []
    assert plan.notes == []


def test_planner_not_implemented() -> None:
    planner = OrganizerPlanner()
    with pytest.raises(NotImplementedError):
        planner.build_plan([], [])
