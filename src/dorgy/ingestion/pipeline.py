"""High-level ingestion pipeline orchestration."""

from __future__ import annotations

import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, Tuple

if TYPE_CHECKING:  # pragma: no cover - imported for type checking only
    from dorgy.classification.vision import VisionCaptioner

from dorgy.config.models import ProcessingOptions
from dorgy.shutdown import ShutdownRequested, check_for_shutdown

from .detectors import HashComputer, TypeDetector
from .discovery import DirectoryScanner
from .extractors import MetadataExtractor
from .models import FileDescriptor, IngestionResult, PendingFile


class IngestionPipeline:
    """Coordinate discovery, detection, and extraction to produce file descriptors."""

    def __init__(
        self,
        scanner: DirectoryScanner,
        detector: TypeDetector,
        hasher: HashComputer,
        extractor: MetadataExtractor,
        processing: ProcessingOptions,
        staging_dir: Path | None = None,
        allow_writes: bool = True,
        vision_captioner: "VisionCaptioner" | None = None,
    ) -> None:
        """Initialize the ingestion pipeline with collaborator instances.

        Args:
            scanner: Directory scanner that yields candidate files.
            detector: MIME-type detector for discovered files.
            hasher: Hash computer for deduplication support.
            extractor: Metadata extractor for file content.
            processing: Processing configuration options.
            staging_dir: Optional directory for temporary copies.
            allow_writes: Whether the pipeline is permitted to write to disk.
        """
        self.scanner = scanner
        self.detector = detector
        self.hasher = hasher
        self.extractor = extractor
        self.processing = processing
        self.staging_dir = staging_dir
        self.allow_writes = allow_writes
        self.vision_captioner = vision_captioner

    def run(
        self,
        roots: Iterable[Path],
        on_stage: Callable[[str, Path, Dict[str, Any] | None], None] | None = None,
        *,
        prompt: str | None = None,
    ) -> IngestionResult:
        """Process one or more roots and return aggregated results.

        Args:
            roots: Iterable of directory roots to ingest.
            on_stage: Optional callback invoked as files progress through the pipeline.
                The callback receives a stage identifier and the associated file path.
            prompt: Optional user-provided instruction that should influence captioning.

        Returns:
            IngestionResult: Aggregate of processed descriptors and status.
        """
        check_for_shutdown()
        result = IngestionResult()

        emit_lock = threading.Lock()

        def emit(stage: str, path: Path, info: Dict[str, Any] | None = None) -> None:
            if on_stage is not None:
                try:
                    with emit_lock:
                        on_stage(stage, path, info)
                except Exception:
                    pass

        for root in roots:
            check_for_shutdown()
            root_path = root.expanduser()
            pending_items = list(self.scanner.scan(root_path))
            if not pending_items:
                continue

            worker_count = max(1, getattr(self.processing, "parallel_workers", 1))

            worker_lock = threading.Lock()
            worker_ids: dict[int, int] = {}
            worker_counter = 0

            def get_worker_id(
                lock: threading.Lock = worker_lock,
                ids: dict[int, int] = worker_ids,
            ) -> int:
                nonlocal worker_counter
                thread_id = threading.get_ident()
                with lock:
                    worker = ids.get(thread_id)
                    if worker is None:
                        worker = worker_counter
                        ids[thread_id] = worker
                        worker_counter += 1
                return worker

            def process_pending(pending: PendingFile) -> IngestionResult:
                check_for_shutdown()
                local_result = IngestionResult()
                process_path = pending.path
                metadata_extra: dict[str, str] = {}
                needs_review = pending.locked
                worker_id = get_worker_id()

                emit(
                    "scan",
                    pending.path,
                    {
                        "size_bytes": pending.size_bytes,
                        "oversized": pending.oversized,
                        "worker_id": worker_id,
                    },
                )
                if pending.locked:
                    emit(
                        "locked",
                        pending.path,
                        {"size_bytes": pending.size_bytes, "worker_id": worker_id},
                    )
                    resolved = self._handle_locked(pending, local_result)
                    if resolved is None:
                        emit(
                            "skipped",
                            pending.path,
                            {"size_bytes": pending.size_bytes, "worker_id": worker_id},
                        )
                        local_result.needs_review.append(pending.path)
                        return local_result
                    process_path, metadata_extra, needs_review = resolved

                sample_limit = None
                if pending.oversized and self.processing.sample_size_mb > 0:
                    sample_limit = self.processing.sample_size_mb * 1024 * 1024
                try:
                    check_for_shutdown()
                    emit(
                        "detect",
                        pending.path,
                        {"size_bytes": pending.size_bytes, "worker_id": worker_id},
                    )
                    mime, category = self.detector.detect(process_path)
                    check_for_shutdown()
                    emit(
                        "hash",
                        pending.path,
                        {"size_bytes": pending.size_bytes, "worker_id": worker_id},
                    )
                    file_hash = self.hasher.compute(process_path)
                    check_for_shutdown()
                    emit(
                        "metadata",
                        pending.path,
                        {"size_bytes": pending.size_bytes, "worker_id": worker_id},
                    )
                    metadata = self.extractor.extract(process_path, mime, sample_limit)
                    metadata.update(metadata_extra)
                    if pending.oversized:
                        metadata.setdefault("oversized", "true")
                        if sample_limit:
                            metadata.setdefault("sample_limit", str(sample_limit))
                    check_for_shutdown()
                    emit(
                        "preview",
                        pending.path,
                        {"size_bytes": pending.size_bytes, "worker_id": worker_id},
                    )
                    preview = self.extractor.preview(process_path, mime, sample_limit)

                    tags: list[str] = [category] if category and category != "unknown" else []

                    vision_result = None
                    if (
                        self.processing.process_images
                        and self.vision_captioner is not None
                        and mime.startswith("image/")
                    ):
                        try:
                            check_for_shutdown()
                            vision_result = self.vision_captioner.caption(
                                process_path,
                                cache_key=file_hash,
                                prompt=prompt,
                            )
                        except RuntimeError as vision_error:
                            metadata.setdefault("vision_error", str(vision_error))
                            local_result.errors.append(f"{pending.path}: {vision_error}")
                        else:
                            if vision_result is not None:
                                if not preview:
                                    preview = vision_result.caption
                                metadata["vision_caption"] = vision_result.caption
                                if vision_result.labels:
                                    metadata["vision_labels"] = ", ".join(vision_result.labels)
                                    for label in vision_result.labels:
                                        if label not in tags:
                                            tags.append(label)
                                if vision_result.confidence is not None:
                                    metadata["vision_confidence"] = (
                                        f"{vision_result.confidence:.3f}"
                                    )
                                if vision_result.reasoning:
                                    metadata["vision_reasoning"] = vision_result.reasoning

                    if not tags and category and category != "unknown":
                        tags = [category]

                    descriptor = FileDescriptor(
                        path=pending.path,
                        display_name=pending.path.name,
                        mime_type=mime,
                        hash=file_hash,
                        preview=preview,
                        metadata=metadata,
                        tags=tags,
                        needs_review=needs_review,
                    )
                    local_result.processed.append(descriptor)

                    if descriptor.needs_review:
                        local_result.needs_review.append(pending.path)

                    processed_copy = metadata.get("processed_from_copy")
                    if processed_copy and self.allow_writes:
                        try:
                            Path(processed_copy).unlink()
                        except OSError:
                            local_result.errors.append(
                                f"{pending.path}: could not clean staging copy {processed_copy}"
                            )
                    emit(
                        "complete",
                        pending.path,
                        {
                            "size_bytes": pending.size_bytes,
                            "descriptor": descriptor,
                            "worker_id": worker_id,
                        },
                    )
                except Exception as exc:  # pragma: no cover - defensive logging
                    emit(
                        "error",
                        pending.path,
                        {"size_bytes": pending.size_bytes, "worker_id": worker_id},
                    )
                    local_result.errors.append(f"{pending.path}: {exc}")
                    corrupted_action = self.processing.corrupted_files.action
                    if corrupted_action == "quarantine":
                        local_result.quarantined.append(pending.path)
                        emit(
                            "quarantine",
                            pending.path,
                            {"size_bytes": pending.size_bytes, "worker_id": worker_id},
                        )
                    else:
                        local_result.needs_review.append(pending.path)
                return local_result

            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = [executor.submit(process_pending, pending) for pending in pending_items]
                try:
                    for future in as_completed(futures):
                        check_for_shutdown()
                        local = future.result()
                        if local.processed:
                            result.processed.extend(local.processed)
                        if local.needs_review:
                            result.needs_review.extend(local.needs_review)
                        if local.quarantined:
                            result.quarantined.extend(local.quarantined)
                        if local.errors:
                            result.errors.extend(local.errors)
                except ShutdownRequested:
                    for future in futures:
                        future.cancel()
                    raise

        return result

    def _handle_locked(
        self,
        pending: PendingFile,
        result: IngestionResult,
    ) -> Tuple[Path, dict[str, str], bool] | None:
        """Resolve a locked file according to the configured policy.

        Args:
            pending: File awaiting processing that is locked.
            result: Result object collecting pipeline metadata.

        Returns:
            Tuple[Path, dict[str, str], bool] | None: Path to process, additional metadata,
            and whether the descriptor still needs review. Returns None if the file
            should be skipped.
        """
        action = self.processing.locked_files.action

        if action == "skip":
            result.errors.append(f"{pending.path}: file locked; skipped.")
            return None

        if action == "wait":
            attempts = max(1, self.processing.locked_files.retry_attempts)
            delay = max(0, self.processing.locked_files.retry_delay_seconds)
            for attempt in range(attempts):
                try:
                    with pending.path.open("rb"):
                        break
                except PermissionError:
                    if attempt == attempts - 1:
                        result.errors.append(
                            f"{pending.path}: file locked after {attempts} attempts; skipped."
                        )
                        return None
                    time.sleep(delay)
            return pending.path, {}, False

        if action == "copy":
            if not self.allow_writes:
                result.errors.append(f"{pending.path}: locked file copy skipped during dry run.")
                return None
            staging_root = self.staging_dir or pending.path.parent / "._dorgy_staging"
            staging_root.mkdir(parents=True, exist_ok=True)
            target = staging_root / pending.path.name
            counter = 1
            while target.exists():
                target = staging_root / f"{pending.path.stem}-{counter}{pending.path.suffix}"
                counter += 1
            shutil.copy2(pending.path, target)
            metadata = {
                "processed_from_copy": str(target),
                "original_locked": "true",
            }
            return target, metadata, False

        result.errors.append(f"{pending.path}: unsupported locked file action '{action}'.")
        return None
