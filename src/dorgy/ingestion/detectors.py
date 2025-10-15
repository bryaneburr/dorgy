"""File type detection and hashing utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Tuple


class TypeDetector:
    """Identify MIME type and file category using python-magic and heuristics."""

    def detect(self, path: Path) -> Tuple[str, str]:
        """Return MIME type and normalized category."""
        raise NotImplementedError("TypeDetector.detect will be implemented during ingestion feature work.")


class HashComputer:
    """Compute fast content hashes for deduplication."""

    def compute(self, path: Path) -> str:
        """Return a hex digest representing the file contents."""
        raise NotImplementedError("HashComputer.compute will be implemented during ingestion feature work.")
