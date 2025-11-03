"""Tests for state helpers used by CLI commands."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from dorgy.classification import ClassificationDecision
from dorgy.cli.helpers.state import (
    _plan_state_changes,
    build_original_snapshot,
    descriptor_to_record,
)
from dorgy.ingestion import FileDescriptor
from dorgy.state import CollectionState, FileRecord


def test_build_original_snapshot_records_directories(tmp_path: Path) -> None:
    root = tmp_path
    desc_a = FileDescriptor(
        path=root / "a" / "file1.txt",
        display_name="file1.txt",
        mime_type="text/plain",
        metadata={"size_bytes": "128"},
        tags=["alpha"],
    )
    desc_b = FileDescriptor(
        path=root / "b" / "c" / "file2.txt",
        display_name="file2.txt",
        mime_type="text/plain",
        metadata={},
    )

    snapshot = build_original_snapshot([desc_a, desc_b], root)

    assert snapshot["entries"][0]["path"] == "a/file1.txt"
    assert set(snapshot["directories"]) == {"a", "b", "b/c"}


def test_plan_state_changes_for_directory(tmp_path: Path) -> None:
    root = tmp_path
    (root / "docs").mkdir()
    state = CollectionState(root=str(root))
    state.files = {
        "docs/report.txt": FileRecord(path="docs/report.txt"),
        "docs/notes/info.txt": FileRecord(path="docs/notes/info.txt"),
        "other.txt": FileRecord(path="other.txt"),
    }

    mappings = _plan_state_changes(
        state,
        root,
        root / "docs",
        root / "archive" / "docs",
    )

    assert set(mappings) == {
        ("docs/report.txt", "archive/docs/report.txt"),
        ("docs/notes/info.txt", "archive/docs/notes/info.txt"),
    }


def test_descriptor_to_record_merges_decision_and_metadata(tmp_path: Path) -> None:
    root = tmp_path
    modified = datetime(2024, 3, 7, 12, 30, tzinfo=timezone.utc)
    (root / "docs").mkdir(exist_ok=True)
    descriptor = FileDescriptor(
        path=root / "docs" / "summary.txt",
        display_name="summary.txt",
        mime_type="text/plain",
        metadata={
            "modified_at": modified.isoformat().replace("+00:00", "Z"),
            "vision_caption": "  Caption here  ",
            "vision_labels": "one, two",
            "vision_confidence": "0.75",
        },
    )
    decision = ClassificationDecision(
        primary_category="Reports",
        secondary_categories=["Monthly"],
        tags=["reports", "monthly"],
        confidence=0.88,
        rename_suggestion="summary-2024",
        reasoning="LLM reasoning",
        needs_review=True,
    )

    record = descriptor_to_record(descriptor, decision, root)

    assert record.path == "docs/summary.txt"
    assert record.categories == ["Reports", "Monthly"]
    assert record.tags == ["reports", "monthly"]
    assert record.confidence == pytest.approx(0.88)
    assert record.rename_suggestion == "summary-2024"
    assert record.needs_review is True
    assert record.last_modified == modified
    assert record.vision_caption == "Caption here"
    assert record.vision_labels == ["one", "two"]
    assert record.vision_confidence == pytest.approx(0.75)
