"""Classification helpers shared by CLI commands and watch service."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Callable, Iterable, Optional

from dorgy.classification import (
    ClassificationBatch,
    ClassificationCache,
    ClassificationDecision,
    ClassificationEngine,
    ClassificationRequest,
)
from dorgy.config import DorgyConfig
from dorgy.ingestion import FileDescriptor
from dorgy.shutdown import ShutdownRequested, check_for_shutdown


def decision_cache_key(descriptor: FileDescriptor, root: Path) -> Optional[str]:
    """Return a stable classification cache key for a descriptor."""

    if descriptor.hash:
        return descriptor.hash
    path = descriptor.path
    if not isinstance(path, Path):
        path = Path(path)
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def run_classification(
    descriptors: Iterable[FileDescriptor],
    classification_prompt: Optional[str],
    root: "Path",
    dry_run: bool,
    config: DorgyConfig,
    cache: Optional[ClassificationCache],
    *,
    on_progress: Optional[
        Callable[[str, int, int, FileDescriptor, Optional[int], Optional[float]], None]
    ] = None,
    max_workers: int = 1,
) -> ClassificationBatch:
    """Execute the classification workflow with caching and fallbacks."""

    descriptors = list(descriptors)
    check_for_shutdown()
    if not descriptors:
        return ClassificationBatch()

    cache_instance = cache
    if cache_instance is not None:
        cache_instance.load()

    decisions: list[Optional[ClassificationDecision]] = [None] * len(descriptors)
    errors: list[str] = []
    pending_requests: list[ClassificationRequest] = []
    pending_indices: list[int] = []
    pending_keys: list[Optional[str]] = []

    total = len(descriptors)
    progress_lock = Lock()
    completed_count = 0

    def notify(event: str, idx: int, worker_id: Optional[int], duration: Optional[float]) -> None:
        nonlocal completed_count
        if on_progress is None or idx >= total:
            return
        descriptor = descriptors[idx]
        with progress_lock:
            if event == "complete":
                completed_count += 1
                processed = completed_count
            else:
                processed = completed_count
        on_progress(event, processed, total, descriptor, worker_id, duration)

    for index, descriptor in enumerate(descriptors):
        key = decision_cache_key(descriptor, root)
        cached = cache_instance.get(key) if cache_instance is not None and key is not None else None
        check_for_shutdown()
        if cached is not None:
            decisions[index] = cached
            notify("start", index, worker_id=None, duration=None)
            notify("complete", index, worker_id=None, duration=0.0)
            continue
        pending_indices.append(index)
        pending_keys.append(key)
        pending_requests.append(
            ClassificationRequest(
                descriptor=descriptor,
                prompt=classification_prompt,
                collection_root=root,
            )
        )

    max_workers = max(1, max_workers)

    if pending_requests:
        check_for_shutdown()
        engine = ClassificationEngine(config.llm)

        def _on_classification_progress(
            local_index: int,
            request: ClassificationRequest,
            worker_id: int,
            event: str,
            duration: float | None,
            error: Exception | None,
        ) -> None:
            original_index = pending_indices[local_index]
            notify(event, original_index, worker_id, duration)

        try:
            batch = engine.classify(
                pending_requests,
                max_workers=max_workers,
                progress_callback=_on_classification_progress if on_progress else None,
            )
        except ShutdownRequested:
            raise
        errors.extend(batch.errors)
        for idx, decision, key in zip(pending_indices, batch.decisions, pending_keys, strict=False):
            check_for_shutdown()
            if decision is not None:
                decisions[idx] = decision
                if not dry_run and cache_instance is not None and key is not None:
                    cache_instance.set(key, decision)

    if cache_instance is not None and not dry_run:
        check_for_shutdown()
        cache_instance.save()

    return ClassificationBatch(decisions=decisions, errors=errors)


def zip_decisions(
    batch: ClassificationBatch,
    descriptors: Iterable[FileDescriptor],
) -> Iterable[tuple[Optional[ClassificationDecision], FileDescriptor]]:
    """Yield pairs of classification decisions and their descriptors."""

    decisions = list(batch.decisions)
    descriptors = list(descriptors)
    for index, descriptor in enumerate(descriptors):
        decision = decisions[index] if index < len(decisions) else None
        yield decision, descriptor


__all__ = ["decision_cache_key", "run_classification", "zip_decisions"]
