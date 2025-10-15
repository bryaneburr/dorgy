"""High-level ingestion pipeline orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

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
    ) -> None:
        self.scanner = scanner
        self.detector = detector
        self.hasher = hasher
        self.extractor = extractor

    def run(self, roots: Iterable[Path]) -> IngestionResult:
        """Process one or more roots and return aggregated results."""
        raise NotImplementedError("IngestionPipeline.run will be implemented during Phase 2 development.")
