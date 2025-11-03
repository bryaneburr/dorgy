"""Tests for classification helper utilities used by CLI workflows."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import pytest

from dorgy.classification import ClassificationBatch, ClassificationDecision
from dorgy.cli.helpers.classification import decision_cache_key, run_classification
from dorgy.config import DorgyConfig
from dorgy.ingestion import FileDescriptor


def test_decision_cache_key_prefers_hash(tmp_path: Path) -> None:
    """Hash takes precedence over relative paths when generating cache keys."""

    root = tmp_path
    descriptor_with_hash = FileDescriptor(
        path=root / "hashed.txt",
        display_name="hashed.txt",
        mime_type="text/plain",
        hash="abc123",
    )
    descriptor_without_hash = FileDescriptor(
        path=root / "nested" / "plain.txt",
        display_name="plain.txt",
        mime_type="text/plain",
    )

    assert decision_cache_key(descriptor_with_hash, root) == "abc123"
    assert decision_cache_key(descriptor_without_hash, root) == Path("nested/plain.txt").as_posix()


def test_run_classification_uses_cache_and_engine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`run_classification` should reuse cached decisions and persist new ones."""

    root = tmp_path
    cached_descriptor = FileDescriptor(
        path=root / "cached.txt",
        display_name="cached.txt",
        mime_type="text/plain",
        hash="cached-hash",
    )
    fresh_descriptor = FileDescriptor(
        path=root / "fresh.txt",
        display_name="fresh.txt",
        mime_type="text/plain",
    )

    cached_decision = ClassificationDecision(primary_category="Cached")
    fresh_decision = ClassificationDecision(primary_category="Fresh", confidence=0.9)

    class StubCache:
        def __init__(self) -> None:
            self.loaded = False
            self.saved = False
            self.store: dict[str, ClassificationDecision] = {
                decision_cache_key(cached_descriptor, root): cached_decision
            }

        def load(self) -> None:
            self.loaded = True

        def get(self, key: Optional[str]) -> Optional[ClassificationDecision]:
            return self.store.get(key) if key is not None else None

        def set(self, key: Optional[str], value: ClassificationDecision) -> None:
            if key is not None:
                self.store[key] = value

        def save(self) -> None:
            self.saved = True

    cache = StubCache()
    engine_calls: list[int] = []

    class StubEngine:
        def __init__(self, _config: object) -> None:
            engine_calls.append(1)

        def classify(self, requests, *, max_workers: int, progress_callback=None):
            assert len(requests) == 1
            assert max_workers == 1
            if progress_callback is not None:
                progress_callback(0, requests[0], 0, "start", None, None)
                progress_callback(0, requests[0], 0, "complete", 0.01, None)
            return ClassificationBatch(decisions=[fresh_decision], errors=[])

    monkeypatch.setattr(
        "dorgy.cli.helpers.classification.ClassificationEngine",
        StubEngine,
    )

    progress_events: list[tuple[str, int, int]] = []

    def _on_progress(event: str, processed: int, total: int, *_) -> None:
        progress_events.append((event, processed, total))

    batch = run_classification(
        [cached_descriptor, fresh_descriptor],
        classification_prompt=None,
        root=root,
        dry_run=False,
        config=DorgyConfig(),
        cache=cache,
        on_progress=_on_progress,
    )

    assert cache.loaded is True
    assert cache.saved is True
    assert engine_calls == [1]
    assert progress_events[0] == ("start", 0, 2)
    assert progress_events[1][0] == "complete"
    assert progress_events[-2][0] == "start"
    assert progress_events[-1][0] == "complete"
    assert batch.decisions[0] == cached_decision
    assert batch.decisions[1] == fresh_decision
    assert cache.store[decision_cache_key(fresh_descriptor, root)] == fresh_decision
