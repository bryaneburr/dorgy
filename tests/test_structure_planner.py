"""Tests for the structure planner JSON decoding helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dorgy.classification.exceptions import LLMResponseError, LLMUnavailableError
from dorgy.classification.models import ClassificationDecision
from dorgy.classification.structure import StructurePlanner
from dorgy.config.models import LLMSettings
from dorgy.ingestion.models import FileDescriptor


def test_decode_tree_payload_parses_plain_json() -> None:
    """Ensure raw JSON strings decode into dictionaries."""

    payload = {"files": [{"source": "a.txt", "destination": "inbox/a.txt"}]}
    raw = json.dumps(payload)

    result = StructurePlanner._decode_tree_payload(raw)

    assert result == payload


def test_decode_tree_payload_parses_code_fence() -> None:
    """Decode JSON embedded within a fenced code block."""

    raw = """```json
    {"files": [{"source": "b.txt", "destination": "letters/b.txt"}]}
    ```"""

    result = StructurePlanner._decode_tree_payload(raw)

    assert result == {"files": [{"source": "b.txt", "destination": "letters/b.txt"}]}


def test_decode_tree_payload_parses_prefixed_text() -> None:
    """Handle conversational wrappers surrounding valid JSON."""

    raw = (
        "Sure, here is a proposal:\n"
        '{"files": [{"source": "c.txt", "destination": "archive/c.txt"}]}\n'
        "Let me know if you need adjustments."
    )

    result = StructurePlanner._decode_tree_payload(raw)

    assert result == {"files": [{"source": "c.txt", "destination": "archive/c.txt"}]}


def test_decode_tree_payload_accepts_list_payload() -> None:
    """Accept bare lists as shorthand for the files array."""

    raw = json.dumps([{"source": "d.txt", "destination": "reports/d.txt"}])

    result = StructurePlanner._decode_tree_payload(raw)

    assert result == {"files": [{"source": "d.txt", "destination": "reports/d.txt"}]}


def test_decode_tree_payload_returns_none_for_invalid_data() -> None:
    """Return ``None`` when JSON cannot be recovered."""

    result = StructurePlanner._decode_tree_payload("not json at all")

    assert result is None


def test_structure_planner_raises_without_llm_when_fallback_disabled(monkeypatch) -> None:
    monkeypatch.setenv("DORGY_USE_FALLBACKS", "0")
    monkeypatch.setattr("dorgy.classification.structure.dspy", None)

    with pytest.raises(LLMUnavailableError):
        StructurePlanner()


def test_structure_planner_propose_raises_on_empty_response(monkeypatch) -> None:
    descriptor = FileDescriptor(
        path=Path("/tmp/sample.pdf"),
        display_name="sample.pdf",
        mime_type="application/pdf",
    )

    planner = object.__new__(StructurePlanner)
    planner._settings = LLMSettings()
    planner._use_fallback = False
    planner._enabled = True
    planner._allow_reprompt = True

    class _Stub:
        def __call__(self, **_: object) -> object:
            return type("Resp", (), {"tree_json": ""})()

    planner._program = _Stub()  # type: ignore[attr-defined]

    with pytest.raises(LLMResponseError):
        planner.propose([descriptor], [None], source_root=Path("/tmp"))


def test_structure_planner_appends_prompt_to_goal() -> None:
    descriptor = FileDescriptor(
        path=Path("/tmp/sample.pdf"),
        display_name="sample.pdf",
        mime_type="application/pdf",
    )

    summary = StructurePlanner._build_descriptor_summary([descriptor], [None], Path("/tmp"))
    expected_goal = StructurePlanner._compose_goal_prompt(summary, "Group items by project")
    captured: dict[str, object] = {}

    class _CaptureProgram:
        def __call__(self, **kwargs: object) -> object:
            captured["goal"] = kwargs.get("goal")
            return type(
                "Resp",
                (),
                {
                    "tree_json": json.dumps(
                        {"files": [{"source": "sample.pdf", "destination": "docs/sample.pdf"}]}
                    )
                },
            )()

    planner = object.__new__(StructurePlanner)
    planner._settings = LLMSettings()
    planner._use_fallback = False
    planner._enabled = True
    planner._allow_reprompt = True
    planner._program = _CaptureProgram()  # type: ignore[attr-defined]

    result = planner.propose(
        [descriptor],
        [None],
        source_root=Path("/tmp"),
        prompt="Group items by project",
    )

    assert captured["goal"] == expected_goal
    assert result[descriptor.path] == Path("docs/sample.pdf")


def test_build_descriptor_summary_highlights_context(tmp_path: Path) -> None:
    descriptor_one = FileDescriptor(
        path=tmp_path / "finance" / "invoice-2023.pdf",
        display_name="invoice-2023.pdf",
        mime_type="application/pdf",
    )
    descriptor_two = FileDescriptor(
        path=tmp_path / "finance" / "archive" / "invoice-2023.pdf",
        display_name="invoice-2023.pdf",
        mime_type="application/pdf",
    )

    decision = ClassificationDecision(primary_category="Taxes")

    summary = StructurePlanner._build_descriptor_summary(
        [descriptor_one, descriptor_two],
        [decision, None],
        tmp_path,
    )

    assert "Total files: 2" in summary
    assert "Primary categories: Taxes (1)" in summary
    assert "Existing folders to reuse" in summary
    assert "Duplicate file stems detected: invoice-2023" in summary


def test_propose_normalizes_single_segment_destination(tmp_path: Path) -> None:
    descriptor = FileDescriptor(
        path=tmp_path / "sample.pdf",
        display_name="sample.pdf",
        mime_type="application/pdf",
    )

    response_payload = {
        "files": [
            {
                "source": "sample.pdf",
                "destination": "Receipts",
            }
        ]
    }

    class _Stub:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, **_: object) -> object:
            self.calls += 1
            return type("Resp", (), {"tree_json": json.dumps(response_payload)})()

    planner = object.__new__(StructurePlanner)
    planner._settings = LLMSettings()
    planner._use_fallback = False
    planner._enabled = True
    planner._program = _Stub()  # type: ignore[attr-defined]
    planner._allow_reprompt = True

    result = planner.propose([descriptor], [None], source_root=tmp_path)

    assert result[descriptor.path] == Path("Receipts") / descriptor.path.name


def test_propose_assigns_fallback_for_missing_files(tmp_path: Path) -> None:
    descriptor_a = FileDescriptor(
        path=tmp_path / "a.pdf",
        display_name="a.pdf",
        mime_type="application/pdf",
    )
    descriptor_b = FileDescriptor(
        path=tmp_path / "b.pdf",
        display_name="b.pdf",
        mime_type="application/pdf",
    )

    response_payload = {
        "files": [
            {
                "source": "a.pdf",
                "destination": "Projects/Taxes/a.pdf",
            }
        ]
    }

    class _PartialStub:
        def __call__(self, **_: object) -> object:
            return type("Resp", (), {"tree_json": json.dumps(response_payload)})()

    planner = object.__new__(StructurePlanner)
    planner._settings = LLMSettings()
    planner._use_fallback = False
    planner._enabled = True
    planner._program = _PartialStub()  # type: ignore[attr-defined]
    planner._allow_reprompt = True

    result = planner.propose([descriptor_a, descriptor_b], [None, None], source_root=tmp_path)

    assert result[descriptor_a.path] == Path("Projects/Taxes/a.pdf")
    assert result[descriptor_b.path] == Path("misc/b.pdf")


def test_propose_skips_reprompt_when_disabled(tmp_path: Path) -> None:
    descriptor_a = FileDescriptor(
        path=tmp_path / "a.pdf",
        display_name="a.pdf",
        mime_type="application/pdf",
    )
    descriptor_b = FileDescriptor(
        path=tmp_path / "b.pdf",
        display_name="b.pdf",
        mime_type="application/pdf",
    )

    response_payload = {
        "files": [
            {
                "source": "a.pdf",
                "destination": "Projects/Taxes/a.pdf",
            }
        ]
    }

    class _CountingStub:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, **_: object) -> object:
            self.calls += 1
            return type("Resp", (), {"tree_json": json.dumps(response_payload)})()

    stub = _CountingStub()
    planner = object.__new__(StructurePlanner)
    planner._settings = LLMSettings()
    planner._use_fallback = False
    planner._enabled = True
    planner._allow_reprompt = False
    planner._program = stub  # type: ignore[attr-defined]

    result = planner.propose([descriptor_a, descriptor_b], [None, None], source_root=tmp_path)

    assert stub.calls == 1
    assert result[descriptor_b.path] == Path("misc/b.pdf")


def test_propose_reprompts_when_enabled(tmp_path: Path) -> None:
    descriptor_a = FileDescriptor(
        path=tmp_path / "a.pdf",
        display_name="a.pdf",
        mime_type="application/pdf",
    )
    descriptor_b = FileDescriptor(
        path=tmp_path / "b.pdf",
        display_name="b.pdf",
        mime_type="application/pdf",
    )

    response_payload = {
        "files": [
            {
                "source": "a.pdf",
                "destination": "Projects/Taxes/a.pdf",
            }
        ]
    }

    class _CountingStub:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self, **_: object) -> object:
            self.calls += 1
            return type("Resp", (), {"tree_json": json.dumps(response_payload)})()

    stub = _CountingStub()
    planner = object.__new__(StructurePlanner)
    planner._settings = LLMSettings()
    planner._use_fallback = False
    planner._enabled = True
    planner._allow_reprompt = True
    planner._program = stub  # type: ignore[attr-defined]

    planner.propose([descriptor_a, descriptor_b], [None, None], source_root=tmp_path)

    assert stub.calls == 2
