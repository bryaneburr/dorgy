"""File discovery utilities."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable, Iterator

from .models import PendingFile


class DirectoryScanner:
    """Discover files within a directory tree subject to configuration filters."""

    def __init__(
        self,
        *,
        recursive: bool,
        include_hidden: bool,
        follow_symlinks: bool,
        max_size_bytes: int | None,
    ) -> None:
        self.recursive = recursive
        self.include_hidden = include_hidden
        self.follow_symlinks = follow_symlinks
        self.max_size_bytes = max_size_bytes

    def scan(self, root: Path) -> Iterator[PendingFile]:
        """Yield files discovered under root."""
        raise NotImplementedError("DirectoryScanner.scan is implemented in a later phase.")

    def _iter_paths(self, root: Path) -> Iterable[Path]:
        """Internal helper to iterate candidate paths."""
        raise NotImplementedError("DirectoryScanner._iter_paths is implemented in a later phase.")

