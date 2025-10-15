"""Ensure ingestion scaffolding exports exist and are unimplemented."""

from pathlib import Path

import pytest

from dorgy.ingestion import FileDescriptor, IngestionPipeline, PendingFile
from dorgy.ingestion.detectors import HashComputer, TypeDetector
from dorgy.ingestion.discovery import DirectoryScanner
from dorgy.ingestion.extractors import MetadataExtractor


def test_pending_file_defaults() -> None:
    pending = PendingFile(path=Path("/tmp/sample.txt"), size_bytes=10)

    assert pending.locked is False
    assert pending.path.name == "sample.txt"


def test_directory_scanner_not_implemented(tmp_path: Path) -> None:
    scanner = DirectoryScanner(recursive=True, include_hidden=False, follow_symlinks=False, max_size_bytes=None)

    with pytest.raises(NotImplementedError):
        next(scanner.scan(tmp_path))


def test_pipeline_run_not_implemented(tmp_path: Path) -> None:
    pipeline = IngestionPipeline(
        scanner=DirectoryScanner(recursive=True, include_hidden=False, follow_symlinks=False, max_size_bytes=None),
        detector=TypeDetector(),
        hasher=HashComputer(),
        extractor=MetadataExtractor(),
    )

    with pytest.raises(NotImplementedError):
        pipeline.run([tmp_path])
