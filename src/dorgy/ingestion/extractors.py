"""Content and metadata extraction helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


class MetadataExtractor:
    """Extract structured metadata and previews for a file."""

    def extract(self, path: Path, mime_type: str) -> Dict[str, str]:
        """Return metadata key/value pairs for the file."""
        try:
            stat = path.stat()
        except OSError as exc:  # pragma: no cover - file disappeared
            return {"error": str(exc)}

        modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        metadata: Dict[str, str] = {
            "size_bytes": str(stat.st_size),
            "modified_at": modified.isoformat(),
            "mime_type": mime_type,
        }
        return metadata

    def preview(self, path: Path, mime_type: str) -> Optional[str]:
        """Return a short textual preview of the file content."""
        if mime_type.startswith("text") or mime_type in {"application/json", "application/xml"}:
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    snippet = fh.read(512).strip()
            except OSError:
                return None
            return snippet or None
        return None
