"""Progress reporting utilities for Dorgy CLI commands."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass

from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

from dorgy.cli.context import console


@dataclass(slots=True)
class _ProgressTask:
    """Manage lifecycle updates for an individual progress task.

    Attributes:
        _progress: Rich progress instance tracking the task.
        _task_id: Identifier assigned by the progress manager.
        _enabled: Indicates whether progress output is active.
        _has_total: Indicates whether the task tracks completion counts.
    """

    _progress: Progress | None
    _task_id: TaskID | None
    _enabled: bool
    _has_total: bool

    def update(self, description: str) -> None:
        """Update the task description while the operation is running.

        Args:
            description: New description to display for the task.
        """

        if not self._enabled or self._progress is None or self._task_id is None:
            return
        self._progress.update(self._task_id, description=description)

    def advance(self, value: float = 1.0) -> None:
        """Increment the task progress when a total is known.

        Args:
            value: Increment to apply to the progress counter.
        """

        if (
            not self._enabled
            or self._progress is None
            or self._task_id is None
            or not self._has_total
        ):
            return
        self._progress.advance(self._task_id, value)

    def complete(self, message: str | None = None) -> None:
        """Mark the task as finished and optionally update the description.

        Args:
            message: Optional final description to show before removal.
        """

        if not self._enabled or self._progress is None or self._task_id is None:
            return
        if message:
            self._progress.update(self._task_id, description=message)
        self._progress.stop_task(self._task_id)
        self._progress.remove_task(self._task_id)
        self._task_id = None


class _ProgressScope(AbstractContextManager["_ProgressScope"]):
    """Context manager that configures progress display for CLI operations."""

    def __init__(self, enabled: bool) -> None:
        """Initialize the scope with an enabled flag.

        Args:
            enabled: Indicates whether progress output should be shown.
        """

        self._enabled = enabled
        self._progress: Progress | None = None

    def __enter__(self) -> "_ProgressScope":
        if not self._enabled:
            return self
        self._progress = Progress(
            SpinnerColumn(spinner_name="dots"),
            TextColumn("{task.description}"),
            BarColumn(bar_width=None),
            TimeElapsedColumn(),
            transient=True,
            expand=True,
            console=console,
        )
        self._progress.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[override]
        if self._progress is not None:
            self._progress.__exit__(exc_type, exc, tb)
        self._progress = None

    def start(self, description: str, *, total: int | None = None) -> _ProgressTask:
        """Begin a new progress task.

        Args:
            description: Task description to display.
            total: Optional total count for determinate progress.

        Returns:
            _ProgressTask: Wrapper managing the created task.
        """

        if not self._enabled or self._progress is None:
            return _ProgressTask(None, None, False, False)
        task_id = self._progress.add_task(description, total=total)
        return _ProgressTask(self._progress, task_id, True, total is not None)


INGESTION_STAGE_LABELS: dict[str, str] = {
    "scan": "Scanning",
    "locked": "Resolving lock",
    "detect": "Detecting type",
    "hash": "Computing hash",
    "metadata": "Extracting metadata",
    "preview": "Generating preview",
    "complete": "Completed",
    "skipped": "Skipped",
    "error": "Error",
    "quarantine": "Quarantined",
}
"""Human-readable labels for ingestion pipeline stages."""


__all__ = ["_ProgressScope", "_ProgressTask", "INGESTION_STAGE_LABELS"]
