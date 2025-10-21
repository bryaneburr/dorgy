"""Tests for the classification engine heuristics."""

from pathlib import Path

import pytest

from dorgy.classification.engine import ClassificationEngine
from dorgy.classification.exceptions import LLMUnavailableError
from dorgy.classification.models import ClassificationRequest
from dorgy.ingestion.models import FileDescriptor


def _make_request(name: str, mime: str, prompt: str | None = None) -> ClassificationRequest:
    descriptor = FileDescriptor(
        path=Path(f"/tmp/{name}"),
        display_name=name,
        mime_type=mime,
        hash="abc",
    )
    return ClassificationRequest(
        descriptor=descriptor,
        prompt=prompt,
        collection_root=Path("/tmp"),
    )


def test_fallback_classifies_text_file() -> None:
    engine = ClassificationEngine()
    result = engine.classify([_make_request("report.txt", "text/plain")])

    assert len(result.decisions) == 1
    decision = result.decisions[0]
    assert decision.primary_category == "Documents"
    assert decision.rename_suggestion == "report"
    assert not result.errors


def test_fallback_uses_prompt_for_secondary_categories() -> None:
    engine = ClassificationEngine()
    request = _make_request("invoice.pdf", "application/pdf", prompt="Finance department")
    result = engine.classify([request])

    assert result.decisions[0].secondary_categories == ["Finance"]


def test_fallback_handles_unknown_types() -> None:
    engine = ClassificationEngine()
    request = _make_request("binary.bin", "application/octet-stream")
    result = engine.classify([request])

    assert result.decisions[0].primary_category == "General"
    assert result.decisions[0].needs_review is True


def test_engine_raises_without_fallback_when_llm_missing(monkeypatch) -> None:
    monkeypatch.setenv("DORGY_USE_FALLBACKS", "0")
    monkeypatch.setattr("dorgy.classification.engine.dspy", None)

    with pytest.raises(LLMUnavailableError):
        ClassificationEngine()
