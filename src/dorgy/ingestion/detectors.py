"""File type detection and hashing utilities."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Tuple

try:
    import magic  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover - optional dependency
    magic = None  # type: ignore[assignment]


class TypeDetector:
    """Identify MIME type and file category using python-magic and heuristics."""

    def detect(self, path: Path) -> Tuple[str, str]:
        """Return MIME type and normalized category for a file.

        Args:
            path: Path to the file to inspect.

        Returns:
            Tuple[str, str]: MIME type and derived high-level category.
        """
        mime = "application/octet-stream"
        category = "unknown"

        if magic is not None:
            try:
                mime = magic.from_file(str(path), mime=True)  # type: ignore[arg-type]
            except Exception:  # pragma: no cover - magic failure
                pass

        if not mime or mime == "application/octet-stream":
            guessed, _ = mimetypes.guess_type(str(path))
            if guessed:
                mime = guessed

        if "/" in mime:
            category = mime.split("/", 1)[0]

        return mime, category


class HashComputer:
    """Compute fast content hashes for deduplication."""

    def compute(self, path: Path) -> str:
        """Return a SHA-256 hex digest representing the file contents.

        Args:
            path: Path to the file whose contents should be hashed.

        Returns:
            str: Hexadecimal digest of the file contents.
        """
        import hashlib

        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()
