"""High-level ingestion pipeline orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from dorgy.config.models import ProcessingOptions

from .detectors import HashComputer, TypeDetector
from .discovery import DirectoryScanner
from .extractors import MetadataExtractor
from .models import FileDescriptor, IngestionResult


class IngestionPipeline:
    """Coordinate discovery, detection, and extraction to produce file descriptors."""

    def __init__(
        self,
        scanner: DirectoryScanner,
        detector: TypeDetector,
        hasher: HashComputer,
        extractor: MetadataExtractor,
        processing: ProcessingOptions,
    ) -> None:
        self.scanner = scanner
        self.detector = detector
        self.hasher = hasher
        self.extractor = extractor
        self.processing = processing

    def run(self, roots: Iterable[Path]) -> IngestionResult:
        """Process one or more roots and return aggregated results."""
        result = IngestionResult()

        for root in roots:
            root_path = root.expanduser()
            for pending in self.scanner.scan(root_path):
                if pending.locked:
                    result.needs_review.append(pending.path)
                    locked_action = self.processing.locked_files.action
                    if locked_action == "skip":
                        result.errors.append(f"{pending.path}: file locked; skipped.")
                        continue
                try:
                    mime, category = self.detector.detect(pending.path)
                    file_hash = self.hasher.compute(pending.path)
                    metadata = self.extractor.extract(pending.path, mime)
                    preview = self.extractor.preview(pending.path, mime)

                    descriptor = FileDescriptor(
                        path=pending.path,
                        display_name=pending.path.name,
                        mime_type=mime,
                        hash=file_hash,
                        preview=preview,
                        metadata=metadata,
                        tags=[category] if category and category != "unknown" else [],
                        needs_review=pending.locked,
                    )
                    result.processed.append(descriptor)

                    if descriptor.needs_review:
                        result.needs_review.append(pending.path)
                except Exception as exc:  # pragma: no cover - defensive logging
                    result.errors.append(f"{pending.path}: {exc}")
                    corrupted_action = self.processing.corrupted_files.action
                    if corrupted_action == "quarantine":
                        result.quarantined.append(pending.path)
                    else:
                        result.needs_review.append(pending.path)

        return result
