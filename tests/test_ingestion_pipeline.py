"""Tests covering the ingestion implementation."""

from pathlib import Path

from PIL import Image

from dorgy.ingestion import IngestionPipeline
from dorgy.ingestion.detectors import HashComputer, TypeDetector
from dorgy.ingestion.discovery import DirectoryScanner
from dorgy.ingestion.extractors import MetadataExtractor


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

    assert [item.path.name for item in found] == ["visible.txt"]
    assert found[0].size_bytes == 5


def test_ingestion_pipeline_generates_descriptors(tmp_path: Path) -> None:
    file_path = tmp_path / "note.txt"
    file_path.write_text("first line\nsecond", encoding="utf-8")

    image_path = tmp_path / "image.png"
    Image.new("RGB", (32, 16), color="red").save(image_path)

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
