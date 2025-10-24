"""Tests for the structure planner JSON decoding helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dorgy.classification.exceptions import LLMResponseError, LLMUnavailableError
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

    expected_goal = StructurePlanner._compose_goal_prompt("Group items by project")
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
    planner._program = _CaptureProgram()  # type: ignore[attr-defined]

    result = planner.propose(
        [descriptor],
        [None],
        source_root=Path("/tmp"),
        prompt="Group items by project",
    )

    assert captured["goal"] == expected_goal
    assert result[descriptor.path] == Path("docs/sample.pdf")
