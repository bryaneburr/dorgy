"""Formatting helpers shared across Dorgy CLI commands."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

from dorgy.cli.lazy import FileDescriptor

if TYPE_CHECKING:
    from dorgy.state import OperationEvent


def _format_modified_timestamp(value: datetime | None) -> str:
    """Format a datetime for human-friendly CLI output.

    Args:
        value: Timestamp to format.

    Returns:
        str: Readable timestamp or ``-`` when unavailable.
    """

    if value is None:
        return "-"
    ts = value
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts = ts.astimezone()
    hour = int(ts.strftime("%I"))
    minute = ts.strftime("%M")
    period = ts.strftime("%p")
    return f"{ts.strftime('%b')} {ts.day} {ts.year}, {hour}:{minute}{period}"


def _format_history_event(event: "OperationEvent") -> str:
    """Render a human-readable string for a persisted operation event.

    Args:
        event: Event entry persisted in the collection history.

    Returns:
        str: Rendered summary string.
    """

    notes = ", ".join(event.notes) if event.notes else ""
    note_suffix = f" — {notes}" if notes else ""
    return (
        f"[{event.timestamp.isoformat()}] {event.operation.upper()} "
        f"{event.source} -> {event.destination}{note_suffix}"
    )


def _format_size(size_bytes: int | None) -> str:
    """Return a human-readable representation of a byte count.

    Args:
        size_bytes: Byte count to format.

    Returns:
        str: Readable size string such as ``1.2 MB``.
    """

    if size_bytes is None or size_bytes < 0:
        return "?"
    units = ["B", "KB", "MB", "GB", "TB", "PB"]
    value = float(size_bytes)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} PB"


def _descriptor_size(descriptor: FileDescriptor) -> int | None:
    """Return the descriptor's size in bytes when present.

    Args:
        descriptor: File descriptor produced by the ingestion pipeline.

    Returns:
        int | None: Parsed byte count or ``None`` when missing.
    """

    raw = descriptor.metadata.get("size_bytes") if descriptor.metadata else None
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _render_tree(paths: Iterable[Path], root: Path) -> str:
    """Render a tree representation of proposed file destinations.

    Args:
        paths: Iterable of destination paths under consideration.
        root: Collection root path to relativize against.

    Returns:
        str: Tree-formatted representation of the provided paths.
    """

    tree: dict[str, dict] = {}

    for path in sorted(paths):
        candidate = Path(path)
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            continue
        if not relative.parts:
            continue
        node = tree
        for part in relative.parts:
            node = node.setdefault(part, {})

    lines: list[str] = []

    def walk(node: dict[str, dict], prefix: str = "") -> None:
        items = sorted(node.items())
        for index, (part, child) in enumerate(items):
            connector = "└── " if index == len(items) - 1 else "├── "
            lines.append(f"{prefix}{connector}{part}")
            extension = "    " if index == len(items) - 1 else "│   "
            walk(child, prefix + extension)

    walk(tree)
    return "\n".join(lines)


__all__ = [
    "_descriptor_size",
    "_format_history_event",
    "_format_modified_timestamp",
    "_format_size",
    "_render_tree",
]
