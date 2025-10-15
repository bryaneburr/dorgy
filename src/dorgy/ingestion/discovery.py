"""File discovery utilities."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from .models import PendingFile


def _is_hidden(path: Path) -> bool:
    return any(part.startswith(".") for part in path.parts if part not in (".", ".."))


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
        """Yield files discovered under root respecting configured filters."""
        root = root.expanduser().resolve()
        if not root.exists():
            return

        for path in self._iter_paths(root):
            if not path.exists():
                continue
            if not path.is_file() and not (self.follow_symlinks and path.is_symlink()):
                continue
            try:
                relative = path.relative_to(root)
            except ValueError:
                relative = Path(path.name)
            if not self.include_hidden and _is_hidden(relative):
                continue
            try:
                stat = path.stat(follow_symlinks=self.follow_symlinks)
            except OSError:
                continue
            oversized = False
            if self.max_size_bytes is not None and stat.st_size > self.max_size_bytes:
                oversized = True

            locked = False
            try:
                with path.open("rb"):
                    pass
            except PermissionError:
                locked = True
            except OSError:
                locked = False

            modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            yield PendingFile(
                path=path,
                size_bytes=stat.st_size,
                modified_at=modified,
                locked=locked,
                oversized=oversized,
            )

    def _iter_paths(self, root: Path) -> Iterable[Path]:
        """Internal helper to iterate candidate paths."""
        if root.is_file():
            yield root
            return

        if self.recursive:
            yield from root.rglob("*")
        else:
            yield from root.iterdir()
