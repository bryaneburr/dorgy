"""High-level ingestion pipeline orchestration."""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Iterable, Tuple

from dorgy.config.models import ProcessingOptions

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
    ) -> None:
        self.scanner = scanner
        self.detector = detector
        self.hasher = hasher
        self.extractor = extractor
        self.processing = processing
        self.staging_dir = staging_dir
        self.allow_writes = allow_writes

    def run(self, roots: Iterable[Path]) -> IngestionResult:
        """Process one or more roots and return aggregated results."""
        result = IngestionResult()

        for root in roots:
            root_path = root.expanduser()
            for pending in self.scanner.scan(root_path):
                process_path = pending.path
                metadata_extra: dict[str, str] = {}
                needs_review = pending.locked

                if pending.locked:
                    resolved = self._handle_locked(pending, result)
                    if resolved is None:
                        result.needs_review.append(pending.path)
                        continue
                    process_path, metadata_extra, needs_review = resolved

                sample_limit = None
                if pending.oversized and self.processing.sample_size_mb > 0:
                    sample_limit = self.processing.sample_size_mb * 1024 * 1024
                try:
                    mime, category = self.detector.detect(process_path)
                    file_hash = self.hasher.compute(process_path)
                    metadata = self.extractor.extract(process_path, mime, sample_limit)
                    metadata.update(metadata_extra)
                    if pending.oversized:
                        metadata.setdefault("oversized", "true")
                        if sample_limit:
                            metadata.setdefault("sample_limit", str(sample_limit))
                    preview = self.extractor.preview(process_path, mime, sample_limit)

                    descriptor = FileDescriptor(
                        path=pending.path,
                        display_name=pending.path.name,
                        mime_type=mime,
                        hash=file_hash,
                        preview=preview,
                        metadata=metadata,
                        tags=[category] if category and category != "unknown" else [],
                        needs_review=needs_review,
                    )
                    result.processed.append(descriptor)

                    if descriptor.needs_review:
                        result.needs_review.append(pending.path)

                    processed_copy = metadata.get("processed_from_copy")
                    if processed_copy and self.allow_writes:
                        try:
                            Path(processed_copy).unlink()
                        except OSError:
                            result.errors.append(
                                f"{pending.path}: could not clean staging copy {processed_copy}"
                            )
                except Exception as exc:  # pragma: no cover - defensive logging
                    result.errors.append(f"{pending.path}: {exc}")
                    corrupted_action = self.processing.corrupted_files.action
                    if corrupted_action == "quarantine":
                        result.quarantined.append(pending.path)
                    else:
                        result.needs_review.append(pending.path)

        return result

    def _handle_locked(
        self,
        pending: PendingFile,
        result: IngestionResult,
    ) -> Tuple[Path, dict[str, str], bool] | None:
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
