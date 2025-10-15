"""Smoke tests for classification scaffolding."""

from pathlib import Path

import pytest

from dorgy.classification import ClassificationBatch, ClassificationDecision, ClassificationRequest


def test_classification_models_defaults() -> None:
    request = ClassificationRequest(
        descriptor=_build_descriptor(Path("/tmp/file.txt")),
        collection_root=Path("/tmp"),
    )
    assert request.descriptor.display_name == "file.txt"

    decision = ClassificationDecision(primary_category="General")
    assert decision.confidence == 0.0
    assert not decision.secondary_categories

    batch = ClassificationBatch()
    assert batch.decisions == []
    assert batch.errors == []


def _build_descriptor(path: Path):
    """Create a minimal `FileDescriptor` for testing.

    Args:
        path: Path to assign to the descriptor.

    Returns:
        FileDescriptor: Descriptor populated with basic metadata.
    """
    from dorgy.ingestion.models import FileDescriptor

    return FileDescriptor(
        path=path,
        display_name=path.name,
        mime_type="text/plain",
        hash="abc",
    )


@pytest.mark.skipif("dspy" not in globals(), reason="DSPy not installed")
def test_classification_engine_not_implemented():
    from dorgy.classification.engine import ClassificationEngine

    if ClassificationEngine.__module__ == "dorgy.classification.engine":
        with pytest.raises(NotImplementedError):
            engine = object.__new__(ClassificationEngine)
            ClassificationEngine.classify(engine, [])
