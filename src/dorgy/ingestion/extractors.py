"""Content and metadata extraction helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

try:  # pragma: no cover - optional dependency
    from PIL import ExifTags, Image
except ImportError:  # pragma: no cover - executed when Pillow missing
    Image = None
    ExifTags = None


class MetadataExtractor:
    """Extract structured metadata and previews for a file."""

    def extract(
        self, path: Path, mime_type: str, sample_limit: int | None = None
    ) -> Dict[str, str]:
        """Return metadata key/value pairs for the file.

        Args:
            path: Path to the file being processed.
            mime_type: MIME type detected for the file.
            sample_limit: Optional limit on the number of bytes to sample.

        Returns:
            Dict[str, str]: Mapping of metadata field names to values.
        """
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

        if mime_type.startswith("text") or mime_type in {"application/json", "application/xml"}:
            limit = sample_limit or 2048
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    sample = fh.read(limit)
            except OSError:
                sample = ""
            if sample:
                metadata["sampled_characters"] = str(len(sample))
                metadata["sampled_lines"] = str(sample.count("\n") + 1)
        if mime_type == "application/json":
            try:
                with path.open("r", encoding="utf-8") as fh:
                    obj = json.load(fh)
                if isinstance(obj, dict):
                    metadata["json_keys"] = str(len(obj))
            except Exception:  # pragma: no cover - best effort
                pass
        if mime_type.startswith("image/") and Image is not None:
            try:
                with Image.open(path) as img:
                    width, height = img.size
                    metadata["image_width"] = str(width)
                    metadata["image_height"] = str(height)
                    metadata["image_mode"] = img.mode
                    if ExifTags and img.getexif():
                        exif_data = img.getexif()
                        orientation_key = next(
                            (k for k, v in ExifTags.TAGS.items() if v == "Orientation"),
                            None,
                        )
                        if orientation_key and orientation_key in exif_data:
                            metadata["image_orientation"] = str(exif_data[orientation_key])
            except Exception:  # pragma: no cover - corrupt images
                pass

        return metadata

    def preview(self, path: Path, mime_type: str, sample_limit: int | None = None) -> Optional[str]:
        """Return a short textual preview of the file content.

        Args:
            path: Path to the file being processed.
            mime_type: MIME type detected for the file.
            sample_limit: Optional limit on the number of bytes to sample.

        Returns:
            Optional[str]: Preview text when available, otherwise None.
        """
        if mime_type.startswith("text") or mime_type in {"application/json", "application/xml"}:
            limit = min(sample_limit, 512) if sample_limit else 512
            try:
                with path.open("r", encoding="utf-8", errors="replace") as fh:
                    snippet = fh.read(limit).strip()
            except OSError:
                return None
            return snippet or None
        return None
