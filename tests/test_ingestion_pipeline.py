"""Tests covering the ingestion implementation."""

from pathlib import Path

from PIL import Image

from dorgy.config.models import CorruptedFilePolicy, LockedFilePolicy, ProcessingOptions
from dorgy.ingestion import IngestionPipeline
from dorgy.ingestion.detectors import HashComputer, TypeDetector
from dorgy.ingestion.discovery import DirectoryScanner
from dorgy.ingestion.extractors import MetadataExtractor
from dorgy.ingestion.models import PendingFile


def test_directory_scanner_filters(tmp_path: Path) -> None:
    visible = tmp_path / "visible.txt"
    visible.write_text("hello", encoding="utf-8")

    hidden = tmp_path / ".hidden.txt"
    hidden.write_text("secret", encoding="utf-8")

    oversized = tmp_path / "oversized.bin"
    oversized.write_bytes(b"x" * 2048)

    scanner = DirectoryScanner(
        recursive=False,
        include_hidden=False,
        follow_symlinks=False,
        max_size_bytes=1024,
    )

    found = list(scanner.scan(tmp_path))
    names = sorted(item.path.name for item in found)

    assert names == ["oversized.bin", "visible.txt"]
    oversized_entry = next(item for item in found if item.path.name == "oversized.bin")
    assert oversized_entry.oversized is True
    assert next(item for item in found if item.path.name == "visible.txt").size_bytes == 5


def test_ingestion_pipeline_generates_descriptors(tmp_path: Path) -> None:
    file_path = tmp_path / "note.txt"
    file_path.write_text("first line\nsecond", encoding="utf-8")

    image_path = tmp_path / "image.png"
    Image.new("RGB", (32, 16), color="red").save(image_path)

    processing = ProcessingOptions()
    pipeline = IngestionPipeline(
        scanner=DirectoryScanner(
            recursive=True,
            include_hidden=True,
            follow_symlinks=False,
            max_size_bytes=None,
        ),
        detector=TypeDetector(),
        hasher=HashComputer(),
        extractor=MetadataExtractor(),
        processing=processing,
    )

    result = pipeline.run([tmp_path])

    assert len(result.processed) == 2
    descriptors = {descriptor.display_name: descriptor for descriptor in result.processed}

    text_desc = descriptors["note.txt"]
    assert text_desc.mime_type.startswith("text/")
    assert text_desc.hash
    assert text_desc.preview is not None and "first line" in text_desc.preview
    assert text_desc.metadata["size_bytes"] == str(file_path.stat().st_size)
    assert text_desc.metadata.get("sampled_lines") == "2"

    image_desc = descriptors["image.png"]
    assert image_desc.mime_type.startswith("image/")
    assert image_desc.metadata["image_width"] == "32"
    assert image_desc.metadata["image_height"] == "16"

    assert not result.needs_review
    assert not result.errors


def test_ingestion_pipeline_sampling(tmp_path: Path) -> None:
    large_file = tmp_path / "large.txt"
    large_file.write_text("A" * 4096, encoding="utf-8")

    processing = ProcessingOptions(max_file_size_mb=0, sample_size_mb=1)

    pipeline = IngestionPipeline(
        scanner=DirectoryScanner(
            recursive=False,
            include_hidden=True,
            follow_symlinks=False,
            max_size_bytes=512,
        ),
        detector=TypeDetector(),
        hasher=HashComputer(),
        extractor=MetadataExtractor(),
        processing=processing,
    )

    result = pipeline.run([tmp_path])

    descriptor = result.processed[0]
    assert descriptor.metadata.get("oversized") == "true"
    assert descriptor.metadata.get("sample_limit") == str(processing.sample_size_mb * 1024 * 1024)


def test_ingestion_pipeline_quarantines_on_error(tmp_path: Path) -> None:
    class FailingExtractor(MetadataExtractor):
        def extract(  # type: ignore[override]
            self, path: Path, mime_type: str, sample_limit: int | None = None
        ) -> dict[str, str]:
            raise ValueError("boom")

        def preview(  # type: ignore[override]
            self, path: Path, mime_type: str, sample_limit: int | None = None
        ) -> str | None:
            return None

    file_path = tmp_path / "bad.txt"
    file_path.write_text("broken", encoding="utf-8")

    processing = ProcessingOptions(
        corrupted_files=CorruptedFilePolicy(action="quarantine"),
    )

    pipeline = IngestionPipeline(
        scanner=DirectoryScanner(
            recursive=False,
            include_hidden=True,
            follow_symlinks=False,
            max_size_bytes=None,
        ),
        detector=TypeDetector(),
        hasher=HashComputer(),
        extractor=FailingExtractor(),
        processing=processing,
    )

    result = pipeline.run([tmp_path])

    assert not result.processed
    assert file_path in result.quarantined
    assert any("boom" in msg for msg in result.errors)


def test_ingestion_pipeline_skips_locked_files(tmp_path: Path) -> None:
    locked_file = tmp_path / "locked.txt"
    locked_file.write_text("content", encoding="utf-8")

    pending = PendingFile(
        path=locked_file,
        size_bytes=locked_file.stat().st_size,
        locked=True,
    )

    class LockedScanner:
        def scan(self, root: Path):  # type: ignore[override]
            yield pending

    processing = ProcessingOptions(
        locked_files=LockedFilePolicy(action="skip"),
    )

    pipeline = IngestionPipeline(
        scanner=LockedScanner(),
        detector=TypeDetector(),
        hasher=HashComputer(),
        extractor=MetadataExtractor(),
        processing=processing,
    )

    result = pipeline.run([tmp_path])

    assert not result.processed
    assert locked_file in result.needs_review
    assert any("locked" in msg for msg in result.errors)


def test_ingestion_pipeline_copies_locked_files(tmp_path: Path) -> None:
    locked_file = tmp_path / "locked.txt"
    locked_file.write_text("content", encoding="utf-8")

    pending = PendingFile(
        path=locked_file,
        size_bytes=locked_file.stat().st_size,
        locked=True,
    )

    class LockedScanner:
        def scan(self, root: Path):  # type: ignore[override]
            yield pending

    staging_dir = tmp_path / "staging"
    processing = ProcessingOptions(locked_files=LockedFilePolicy(action="copy"))

    pipeline = IngestionPipeline(
        scanner=LockedScanner(),
        detector=TypeDetector(),
        hasher=HashComputer(),
        extractor=MetadataExtractor(),
        processing=processing,
        staging_dir=staging_dir,
    )

    result = pipeline.run([tmp_path])

    assert len(result.processed) == 1
    descriptor = result.processed[0]
    assert descriptor.metadata.get("processed_from_copy")
    assert not list(staging_dir.glob("*"))
    assert locked_file not in result.needs_review
