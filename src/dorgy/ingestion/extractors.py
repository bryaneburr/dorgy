"""Content and metadata extraction helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional


class MetadataExtractor:
    """Extract structured metadata and previews for a file."""

    def extract(self, path: Path, mime_type: str) -> Dict[str, str]:
        """Return metadata key/value pairs for the file."""
        raise NotImplementedError("MetadataExtractor.extract will be implemented in a later phase.")

    def preview(self, path: Path, mime_type: str) -> Optional[str]:
        """Return a short textual preview of the file content."""
        raise NotImplementedError("MetadataExtractor.preview will be implemented in a later phase.")
