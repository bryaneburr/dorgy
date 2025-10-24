"""Command line interface for the Dorgy project."""

from __future__ import annotations

import difflib
import fnmatch
import importlib
import json
import logging
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Mapping, cast

import click
import yaml
from click.core import ParameterSource
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)
from rich.syntax import Syntax
from rich.table import Table

from dorgy.cli_options import (
    ModeResolution,
    classify_prompt_file_option,
    classify_prompt_option,
    dry_run_option,
    json_option,
    output_option,
    quiet_option,
    recursive_option,
    resolve_mode_settings,
    structure_prompt_file_option,
    structure_prompt_option,
    summary_option,
)
from dorgy.config import ConfigError, ConfigManager, DorgyConfig, resolve_with_precedence
from dorgy.shutdown import ShutdownRequested, shutdown_manager

if TYPE_CHECKING:
    from dorgy.classification import VisionCache, VisionCaptioner
    from dorgy.ingestion import FileDescriptor
    from dorgy.state import (
        CollectionState,
        FileRecord,
        OperationEvent,
    )
    from dorgy.watch import WatchBatchResult

_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "ClassificationCache": ("dorgy.classification", "ClassificationCache"),
    "VisionCache": ("dorgy.classification", "VisionCache"),
    "VisionCaptioner": ("dorgy.classification", "VisionCaptioner"),
    "LLMUnavailableError": ("dorgy.classification.exceptions", "LLMUnavailableError"),
    "LLMResponseError": ("dorgy.classification.exceptions", "LLMResponseError"),
    "StructurePlanner": ("dorgy.classification.structure", "StructurePlanner"),
    "FileDescriptor": ("dorgy.ingestion", "FileDescriptor"),
    "IngestionPipeline": ("dorgy.ingestion", "IngestionPipeline"),
    "HashComputer": ("dorgy.ingestion.detectors", "HashComputer"),
    "TypeDetector": ("dorgy.ingestion.detectors", "TypeDetector"),
    "DirectoryScanner": ("dorgy.ingestion.discovery", "DirectoryScanner"),
    "MetadataExtractor": ("dorgy.ingestion.extractors", "MetadataExtractor"),
    "OperationExecutor": ("dorgy.organization.executor", "OperationExecutor"),
    "MoveOperation": ("dorgy.organization.models", "MoveOperation"),
    "OperationPlan": ("dorgy.organization.models", "OperationPlan"),
    "OrganizerPlanner": ("dorgy.organization.planner", "OrganizerPlanner"),
    "CollectionState": ("dorgy.state", "CollectionState"),
    "FileRecord": ("dorgy.state", "FileRecord"),
    "MissingStateError": ("dorgy.state", "MissingStateError"),
    "OperationEvent": ("dorgy.state", "OperationEvent"),
    "StateError": ("dorgy.state", "StateError"),
    "StateRepository": ("dorgy.state", "StateRepository"),
    "WatchBatchResult": ("dorgy.watch", "WatchBatchResult"),
    "WatchService": ("dorgy.watch", "WatchService"),
}


def __getattr__(name: str) -> Any:
    """Lazily expose heavy dependencies while keeping CLI import fast."""

    if name in _LAZY_ATTRS:
        module_name, attr_name = _LAZY_ATTRS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _load_dependency(name: str, module: str, attr: str) -> Any:
    """Return a dependency, respecting any monkeypatch overrides."""

    if name in globals():
        return globals()[name]
    module_obj = importlib.import_module(module)
    value = getattr(module_obj, attr)
    globals()[name] = value
    return value


console = Console()
LOGGER = logging.getLogger(__name__)


def _collect_llm_metadata(settings: Any) -> dict[str, Any]:
    """Return sanitized LLM metadata including fallback state and summary text."""

    metadata = settings.runtime_metadata()
    fallbacks_enabled = os.getenv("DORGY_USE_FALLBACKS") == "1"
    metadata["fallbacks_enabled"] = fallbacks_enabled
    fallback_text = "enabled" if fallbacks_enabled else "disabled"
    metadata["summary"] = f"{settings.runtime_summary()}, fallbacks={fallback_text}"
    return metadata


def _llm_summary(metadata: Mapping[str, Any]) -> str:
    """Render a human-readable LLM summary from serialized metadata."""

    summary = metadata.get("summary")
    if isinstance(summary, str):
        return summary

    parts: list[str] = []
    model = metadata.get("model")
    if model:
        parts.append(f"model={model}")
    temperature = metadata.get("temperature")
    if temperature is not None:
        parts.append(f"temperature={float(temperature):.2f}")
    max_tokens = metadata.get("max_tokens")
    if max_tokens is not None:
        parts.append(f"max_tokens={max_tokens}")
    api_base_url = metadata.get("api_base_url")
    if api_base_url:
        parts.append(f"api_base_url={api_base_url}")
    if metadata.get("api_key_configured"):
        parts.append("api_key=provided")
    else:
        parts.append("api_key=not-set")
    fallback = metadata.get("fallbacks_enabled")
    if fallback is not None:
        parts.append(f"fallbacks={'enabled' if fallback else 'disabled'}")
    return ", ".join(parts)


class _ProgressTask:
    """Manage lifecycle updates for an individual progress task."""

    def __init__(
        self,
        progress: Progress | None,
        task_id: TaskID | None,
        *,
        enabled: bool,
        has_total: bool,
    ) -> None:
        """Initialize a progress task wrapper.

        Args:
            progress: Rich progress instance managing the task.
            task_id: Identifier assigned by the progress manager.
            enabled: Indicates whether progress output is active.
        """
        self._progress = progress
        self._task_id: TaskID | None = task_id
        self._enabled = enabled
        self._has_total = has_total

    def update(self, description: str) -> None:
        """Update the task description while the operation is running."""

        if not self._enabled or self._progress is None or self._task_id is None:
            return
        self._progress.update(self._task_id, description=description)

    def complete(self, message: str | None = None) -> None:
        """Mark the task as finished and optionally update the description."""

        if not self._enabled or self._progress is None or self._task_id is None:
            return
        if message:
            self._progress.update(self._task_id, description=message)
        self._progress.stop_task(self._task_id)
        self._progress.remove_task(self._task_id)
        self._task_id = None

    def advance(self, *, step: int = 1, description: str | None = None) -> None:
        """Advance the task progress and optionally update the description."""

        if not self._enabled or self._progress is None or self._task_id is None:
            return
        kwargs: dict[str, Any] = {}
        if description is not None:
            kwargs["description"] = description
        if self._has_total:
            kwargs["advance"] = step
        self._progress.update(self._task_id, **kwargs)

    def set_description(self, description: str) -> None:
        """Update the task description without advancing progress."""

        if not self._enabled or self._progress is None or self._task_id is None:
            return
        self._progress.update(self._task_id, description=description)


class _ProgressScope:
    """Context manager that coordinates Rich progress rendering."""

    def __init__(self, enabled: bool) -> None:
        """Initialize the scope.

        Args:
            enabled: Indicates whether progress output should be rendered.
        """
        self._enabled = enabled
        self._progress: Progress | None = None

    def __enter__(self) -> "_ProgressScope":
        if self._enabled:
            self._progress = Progress(
                SpinnerColumn(style="cyan"),
                TextColumn("{task.description}"),
                BarColumn(bar_width=None),
                TimeElapsedColumn(),
                transient=True,
                console=console,
            )
            self._progress.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._progress is not None:
            self._progress.__exit__(exc_type, exc, tb)
        self._progress = None

    def start(self, description: str, *, total: int | None = None) -> _ProgressTask:
        """Begin a new indeterminate progress task."""

        if not self._enabled or self._progress is None:
            return _ProgressTask(None, None, enabled=False, has_total=False)
        task_id = self._progress.add_task(description, total=total)
        return _ProgressTask(
            self._progress,
            task_id,
            enabled=True,
            has_total=total is not None,
        )


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


def _handle_cli_error(
    message: str,
    *,
    code: str,
    json_output: bool,
    details: Any | None = None,
    original: Exception | None = None,
) -> None:
    """Emit a standardized error and terminate the command appropriately.

    Args:
        message: Human-readable error message.
        code: Machine-readable error identifier.
        json_output: Indicates whether JSON mode is active.
        details: Optional structured details to include in the payload.
        original: Original exception for chaining when not using JSON.

    Raises:
        SystemExit: When emitting JSON output to terminate the command.
        click.ClickException: For non-JSON flows to surface the error.
    """

    if json_output:
        payload: dict[str, Any] = {"error": {"code": code, "message": message}}
        if details is not None:
            payload["error"]["details"] = details
        console.print_json(data=payload)
        raise SystemExit(1)

    if isinstance(original, click.ClickException):
        raise original

    raise click.ClickException(message) from original


def _emit_message(message: Any, *, mode: str, quiet: bool, summary_only: bool) -> None:
    """Conditionally print CLI output according to quiet/summary settings.

    Args:
        message: Renderable or string to emit.
        mode: Output mode identifier (`detail`, `summary`, `warning`, or `error`).
        quiet: Whether quiet mode is active.
        summary_only: Whether only summary lines should be emitted.
    """

    if quiet and mode != "error":
        return

    important_modes = {"summary", "warning", "error"}
    if summary_only and mode not in important_modes:
        return

    console.print(message)


def _format_summary_line(command: str, root: Path | str, metrics: dict[str, Any]) -> str:
    """Return a consistent summary line for CLI commands.

    Args:
        command: Command name to include in the summary.
        root: Target root path relevant to the command.
        metrics: Ordered mapping of metric names to values.

    Returns:
        str: Rich-formatted summary string.
    """

    formatted_root = str(root)
    parts = ", ".join(f"{key}={value}" for key, value in metrics.items())
    return f"[green]{command} summary for {formatted_root}: {parts}.[/green]"


def _emit_errors(
    errors: dict[str, list[str]],
    *,
    quiet: bool,
    summary_only: bool,
) -> None:
    """Emit structured error output honoring quiet/summary preferences.

    Args:
        errors: Mapping of error categories to lists of messages.
        quiet: Whether quiet mode is active.
        summary_only: Whether summary-only mode is active.
    """

    combined = [*errors.get("ingestion", []), *errors.get("classification", [])]
    if not combined:
        return

    _emit_message(
        "[red]Errors encountered:[/red]",
        mode="error",
        quiet=quiet,
        summary_only=summary_only,
    )
    for entry in combined:
        _emit_message(f"  - {entry}", mode="error", quiet=quiet, summary_only=summary_only)


def _emit_watch_batch(
    batch: WatchBatchResult,
    *,
    json_output: bool,
    quiet: bool,
    summary_only: bool,
) -> None:
    """Render output for a processed watch batch."""

    if json_output:
        console.print_json(data=batch.json_payload)
        return

    trigger_count = len(batch.triggered_paths)
    llm_context = batch.json_payload.get("context", {}).get("llm")  # type: ignore[arg-type]
    if llm_context and not summary_only:
        _emit_message(
            f"[cyan]LLM configuration: {_llm_summary(llm_context)}[/cyan]",
            mode="detail",
            quiet=quiet,
            summary_only=summary_only,
        )

    if trigger_count and not summary_only:
        _emit_message(
            f"[cyan]Watch batch {batch.json_payload['context']['batch_id']} "
            f"processed {trigger_count} triggered path(s).[/cyan]",
            mode="detail",
            quiet=quiet,
            summary_only=summary_only,
        )

    _emit_errors(batch.errors, quiet=quiet, summary_only=summary_only)

    if batch.notes:
        _emit_message(
            "[yellow]Plan notes:[/yellow]",
            mode="warning",
            quiet=quiet,
            summary_only=summary_only,
        )
        for note in batch.notes:
            _emit_message(
                f"  - {note}",
                mode="warning",
                quiet=quiet,
                summary_only=summary_only,
            )

    if batch.ingestion.needs_review:
        _emit_message(
            f"[yellow]{len(batch.ingestion.needs_review)} files require review based on the "
            "current confidence threshold.[/yellow]",
            mode="warning",
            quiet=quiet,
            summary_only=summary_only,
        )

    if batch.quarantine_paths:
        _emit_message(
            f"[yellow]{len(batch.quarantine_paths)} files moved to quarantine.[/yellow]",
            mode="warning",
            quiet=quiet,
            summary_only=summary_only,
        )

    executed_removals = [
        entry for entry in batch.json_payload.get("removals", []) if entry.get("executed")
    ]
    if executed_removals and not summary_only:
        removal_counts: dict[str, int] = {}
        for entry in executed_removals:
            kind = entry.get("kind") or "deleted"
            removal_counts[kind] = removal_counts.get(kind, 0) + 1
        if removal_counts.get("deleted"):
            deleted_msg = (
                "[red]"
                f"{removal_counts['deleted']} tracked file(s) deleted during watch batch."
                "[/red]"
            )
            _emit_message(
                deleted_msg,
                mode="warning",
                quiet=quiet,
                summary_only=summary_only,
            )
        if removal_counts.get("moved_out"):
            _emit_message(
                f"[yellow]{removal_counts['moved_out']} file(s) moved outside watched roots; "
                "state entries removed.[/yellow]",
                mode="warning",
                quiet=quiet,
                summary_only=summary_only,
            )

    summary_metrics: dict[str, Any] = {
        "processed": batch.counts["processed"],
        "needs_review": batch.counts["needs_review"],
        "quarantined": batch.counts["quarantined"],
        "renames": batch.counts["renames"],
        "moves": batch.counts["moves"],
        "deleted": batch.counts["deletes"],
        "conflicts": batch.counts["conflicts"],
        "errors": batch.counts["errors"],
    }
    if batch.suppressed_deletions:
        summary_metrics["suppressed"] = len(batch.suppressed_deletions)
    if batch.dry_run:
        summary_metrics["dry_run"] = True

    _emit_message(
        _format_summary_line("Watch", batch.target_root, summary_metrics),
        mode="summary",
        quiet=quiet,
        summary_only=summary_only,
    )


def _not_implemented(command: str) -> None:
    """Emit a placeholder message for incomplete CLI commands.

    Args:
        command: Name of the command to mention in the status message.
    """
    console.print(
        f"[yellow]`{command}` is not implemented yet. "
        "Track progress in SPEC.md and notes/STATUS.md.[/yellow]"
    )


def _assign_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    """Assign a nested value within a dictionary for a dotted path.

    Args:
        target: Mapping to mutate in-place.
        path: Sequence of keys representing the nested location.
        value: Value to assign at the nested location.

    Raises:
        ConfigError: If a non-mapping value is encountered along the path.
    """

    node = target
    for segment in path[:-1]:
        existing = node.get(segment)
        if existing is None:
            existing = {}
            node[segment] = existing
        elif not isinstance(existing, dict):
            raise ConfigError(
                f"Cannot assign into '{segment}' because it is not a mapping in the config file."
            )
        node = existing
    node[path[-1]] = value


def _format_history_event(event: OperationEvent) -> str:
    notes = ", ".join(event.notes) if event.notes else ""
    note_suffix = f" — {notes}" if notes else ""
    return (
        f"[{event.timestamp.isoformat()}] {event.operation.upper()} "
        f"{event.source} -> {event.destination}{note_suffix}"
    )


def _format_size(size_bytes: int | None) -> str:
    """Return a human-readable representation of a byte count."""

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
    """Return the descriptor's size in bytes when present."""

    raw = descriptor.metadata.get("size_bytes") if descriptor.metadata else None
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _render_tree(paths: Iterable[Path], root: Path) -> str:
    """Render a tree representation of proposed file destinations."""

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
        for index, (name, child) in enumerate(items):
            is_last = index == len(items) - 1
            connector = "└──" if is_last else "├──"
            lines.append(f"{prefix}{connector} {name}")
            if child:
                extension = "    " if is_last else "│   "
                walk(child, prefix + extension)

    walk(tree)
    return "\n".join(lines)


def _normalise_state_key(value: str) -> str:
    """Return a normalized representation for state paths using forward slashes.

    Args:
        value: Path string to normalize.

    Returns:
        str: Normalized path string with forward slashes.
    """

    return value.replace("\\", "/")


def _parse_csv_option(raw: str | None) -> list[str]:
    """Parse a comma-separated CLI option into a list of values.

    Args:
        raw: Raw comma-separated string supplied by the user.

    Returns:
        list[str]: List of trimmed values (empty when no input provided).
    """

    if not raw:
        return []
    return [segment.strip() for segment in raw.split(",") if segment.strip()]


def _parse_datetime_option(option_name: str, raw: str | None) -> datetime | None:
    """Parse an ISO 8601 datetime option into a timezone-aware value.

    Args:
        option_name: CLI flag name used for error reporting.
        raw: Raw string value supplied by the user.

    Returns:
        datetime | None: Parsed datetime in UTC or ``None`` when not provided.

    Raises:
        click.ClickException: If the value cannot be parsed.
    """

    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        message = (
            f"Invalid value for {option_name}: {raw}. Use ISO 8601 format "
            "(YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)."
        )
        raise click.ClickException(message) from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _detect_collection_root(path: Path) -> Path:
    """Return the collection root that owns the given path.

    Args:
        path: Absolute file or directory path located within a collection.

    Returns:
        Path: Collection root containing `.dorgy/state.json`.

    Raises:
        MissingStateError: If the path does not belong to a managed collection.
    """

    from dorgy.state import MissingStateError

    candidate = path if path.is_dir() else path.parent
    for current in [candidate, *candidate.parents]:
        state_path = current / ".dorgy" / "state.json"
        if state_path.exists():
            return current
    raise MissingStateError(f"No collection state found for {path}.")


def _resolve_move_destination(
    source: Path,
    candidate: Path,
    strategy: str,
) -> tuple[Path | None, bool, str | None, bool]:
    """Resolve naming conflicts for a move/rename destination.

    Args:
        source: Source path that will be moved.
        candidate: Desired destination path.
        strategy: Conflict resolution strategy (`append_number`, `timestamp`, `skip`).

    Returns:
        Tuple containing the resolved destination (or ``None`` when skipped), a flag
        indicating whether a conflict occurred, an optional explanatory note, and a
        boolean indicating whether the operation should be skipped entirely.
    """

    normalized = (strategy or "append_number").lower()
    if normalized not in {"append_number", "timestamp", "skip"}:
        normalized = "append_number"

    if candidate.resolve() == source.resolve():
        return candidate, False, None, False

    conflict_applied = False
    base_candidate = candidate
    final_candidate = candidate
    counter = 1
    timestamp_applied = False

    while final_candidate.exists():
        conflict_applied = True
        if normalized == "skip":
            note = (
                f"Skipped move for {source} because {final_candidate} already exists "
                "and the conflict strategy is 'skip'."
            )
            return None, True, note, True
        if normalized == "timestamp" and not timestamp_applied:
            timestamp_applied = True
            timestamp_value = datetime.now(timezone.utc)
            suffix = timestamp_value.strftime("%Y%m%d-%H%M%S")
            base_candidate = candidate.with_name(f"{candidate.stem}-{suffix}{candidate.suffix}")
            final_candidate = base_candidate
            continue
        final_candidate = base_candidate.with_name(
            f"{base_candidate.stem}-{counter}{base_candidate.suffix}"
        )
        counter += 1

    note_text: str | None = None
    if conflict_applied:
        note_text = f"Resolved conflict for {source} -> {final_candidate} using '{normalized}'."
    return final_candidate, conflict_applied, note_text, False


def _plan_state_changes(
    state: CollectionState,
    root: Path,
    source: Path,
    destination: Path,
) -> list[tuple[str, str]]:
    """Compute state path updates required for a move/rename operation.

    Args:
        state: Loaded collection state.
        root: Collection root path.
        source: Original filesystem path.
        destination: Destination filesystem path after the move.

    Returns:
        list[tuple[str, str]]: Sequence of (old_path, new_path) mappings.

    Raises:
        click.ClickException: If the source is not tracked in the collection.
    """

    from dorgy.cli_support import relative_to_collection

    source_rel = _normalise_state_key(relative_to_collection(source, root))
    dest_rel = _normalise_state_key(relative_to_collection(destination, root))
    mappings: list[tuple[str, str]] = []

    if source.is_dir():
        prefix = source_rel.rstrip("/")
        for key in list(state.files.keys()):
            normalised_key = _normalise_state_key(key)
            if normalised_key == prefix or normalised_key.startswith(f"{prefix}/"):
                suffix = normalised_key[len(prefix) :].lstrip("/")
                new_key = dest_rel if not suffix else f"{dest_rel}/{suffix}"
                mappings.append((key, new_key))
        if not mappings:
            raise click.ClickException(
                f"No tracked files found under {source_rel}. Run `dorgy org` to refresh state."
            )
        return mappings

    matched_key: str | None = None
    for key in state.files.keys():
        if _normalise_state_key(key) == source_rel:
            matched_key = key
            break
    if matched_key is None:
        raise click.ClickException(
            f"{source_rel} is not tracked in the collection state. "
            "Run `dorgy org` to refresh metadata before moving files."
        )

    mappings.append((matched_key, dest_rel))
    return mappings


def _apply_state_changes(state: CollectionState, changes: Iterable[tuple[str, str]]) -> None:
    """Apply planned state path updates to the in-memory state model.

    Args:
        state: State model to mutate.
        changes: Iterable of (old_path, new_path) tuples describing updates.
    """

    staged: list[tuple[str, FileRecord]] = []
    for old_key, new_key in changes:
        record = state.files.pop(old_key, None)
        if record is None:
            continue
        staged.append((new_key, record))
    for new_key, record in staged:
        record.path = new_key
        state.files[new_key] = record


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="dorgy")
def cli() -> None:
    """Dorgy automatically organizes your files using AI-assisted workflows."""


@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=str))
@recursive_option("Include all subdirectories.")
@classify_prompt_file_option("Read classification guidance from a text file.")
@classify_prompt_option("Provide extra classification guidance.")
@structure_prompt_file_option("Read extra structure instructions from a file.")
@structure_prompt_option("Provide extra structure instructions.")
@output_option("Directory for organized files.")
@dry_run_option("Preview changes without modifying files.")
@json_option("Emit JSON describing proposed changes.")
@summary_option()
@quiet_option()
@click.pass_context
def org(
    ctx: click.Context,
    path: str,
    recursive: bool,
    classify_prompt: str | None,
    classify_prompt_file: str | None,
    structure_prompt: str | None,
    structure_prompt_file: str | None,
    output: str | None,
    dry_run: bool,
    json_output: bool,
    summary_mode: bool,
    quiet: bool,
) -> None:
    """Organize files rooted at PATH using the configured ingestion pipeline."""

    from dorgy.cli_support import (
        build_original_snapshot,
        collect_error_payload,
        compute_org_counts,
        descriptor_to_record,
        relative_to_collection,
        resolve_prompt_text,
        run_classification,
        zip_decisions,
    )

    ClassificationCacheCls = _load_dependency(
        "ClassificationCache", "dorgy.classification", "ClassificationCache"
    )
    VisionCacheCls = _load_dependency("VisionCache", "dorgy.classification", "VisionCache")
    VisionCaptionerCls = _load_dependency(
        "VisionCaptioner", "dorgy.classification", "VisionCaptioner"
    )
    StructurePlannerCls = _load_dependency(
        "StructurePlanner", "dorgy.classification.structure", "StructurePlanner"
    )
    LLMUnavailableError = _load_dependency(
        "LLMUnavailableError", "dorgy.classification.exceptions", "LLMUnavailableError"
    )
    LLMResponseError = _load_dependency(
        "LLMResponseError", "dorgy.classification.exceptions", "LLMResponseError"
    )
    IngestionPipelineCls = _load_dependency(
        "IngestionPipeline", "dorgy.ingestion", "IngestionPipeline"
    )
    HashComputerCls = _load_dependency("HashComputer", "dorgy.ingestion.detectors", "HashComputer")
    TypeDetectorCls = _load_dependency("TypeDetector", "dorgy.ingestion.detectors", "TypeDetector")
    DirectoryScannerCls = _load_dependency(
        "DirectoryScanner", "dorgy.ingestion.discovery", "DirectoryScanner"
    )
    MetadataExtractorCls = _load_dependency(
        "MetadataExtractor", "dorgy.ingestion.extractors", "MetadataExtractor"
    )
    OperationExecutorCls = _load_dependency(
        "OperationExecutor", "dorgy.organization.executor", "OperationExecutor"
    )
    OrganizerPlannerCls = _load_dependency(
        "OrganizerPlanner", "dorgy.organization.planner", "OrganizerPlanner"
    )
    CollectionStateCls = _load_dependency("CollectionState", "dorgy.state", "CollectionState")
    StateRepositoryCls = _load_dependency("StateRepository", "dorgy.state", "StateRepository")
    MissingStateError = _load_dependency("MissingStateError", "dorgy.state", "MissingStateError")

    json_enabled = json_output
    mode: ModeResolution | None = None
    try:
        classification_prompt = resolve_prompt_text(classify_prompt, classify_prompt_file)
    except (OSError, UnicodeDecodeError) as exc:
        raise click.ClickException(
            f"Failed to read classification prompt file {classify_prompt_file}: {exc}"
        ) from exc
    try:
        structure_prompt_value = resolve_prompt_text(structure_prompt, structure_prompt_file)
    except (OSError, UnicodeDecodeError) as exc:
        raise click.ClickException(
            f"Failed to read structure prompt file {structure_prompt_file}: {exc}"
        ) from exc
    if structure_prompt_value is None:
        structure_prompt_value = classification_prompt
    try:
        manager = ConfigManager()
        manager.ensure_exists()
        config = manager.load()

        mode = resolve_mode_settings(
            ctx,
            config.cli,
            quiet_flag=quiet,
            summary_flag=summary_mode,
            json_flag=json_output,
        )
        if mode is None:  # pragma: no cover - defensive guard
            raise RuntimeError("Failed to resolve mode settings")
        quiet_enabled = mode.quiet
        summary_only = mode.summary
        json_enabled = mode.json_output
        progress_enabled = (
            config.cli.progress_enabled
            and console.is_terminal
            and not json_enabled
            and not quiet_enabled
            and not summary_only
        )

        source_root = Path(path).expanduser().resolve()
        target_root = source_root
        copy_mode = False
        if output:
            target_root = Path(output).expanduser().resolve()
            if not dry_run:
                target_root.mkdir(parents=True, exist_ok=True)
            copy_mode = target_root != source_root

        recursive = recursive or config.processing.recurse_directories
        include_hidden = config.processing.process_hidden_files
        follow_symlinks = config.processing.follow_symlinks
        max_size_bytes = None
        if config.processing.max_file_size_mb > 0:
            max_size_bytes = config.processing.max_file_size_mb * 1024 * 1024

        scanner = DirectoryScannerCls(
            recursive=recursive,
            include_hidden=include_hidden,
            follow_symlinks=follow_symlinks,
            max_size_bytes=max_size_bytes,
        )
        state_dir = target_root / ".dorgy"
        staging_dir = None if dry_run else state_dir / "staging"
        classification_cache = ClassificationCacheCls(state_dir / "classifications.json")
        vision_captioner: "VisionCaptioner | None" = None
        vision_warning: str | None = None
        if config.processing.process_images:
            cache_instance = cast("VisionCache", VisionCacheCls(state_dir / "vision.json"))
            cache_instance.load()
            try:
                vision_captioner = cast(
                    "VisionCaptioner",
                    VisionCaptionerCls(config.llm, cache=cache_instance),
                )
            except RuntimeError as exc:
                vision_warning = f"Vision captioning disabled: {exc}"
                LOGGER.warning("%s", vision_warning)
                vision_captioner = None

        pipeline = IngestionPipelineCls(
            scanner=scanner,
            detector=TypeDetectorCls(),
            hasher=HashComputerCls(),
            extractor=MetadataExtractorCls(preview_char_limit=config.processing.preview_char_limit),
            processing=config.processing,
            staging_dir=staging_dir,
            allow_writes=not dry_run,
            vision_captioner=vision_captioner,
        )

        planner = OrganizerPlannerCls()
        parallel_workers = max(1, config.processing.parallel_workers)

        with _ProgressScope(progress_enabled) as progress:
            ingestion_task = progress.start("Preparing files")
            ingestion_state = {"completed": 0}
            ingestion_worker_tasks: dict[int, _ProgressTask] = {}

            def _ingestion_stage(
                stage: str,
                stage_path: Path,
                info: dict[str, Any] | None,
            ) -> None:
                label = INGESTION_STAGE_LABELS.get(stage, stage.replace("_", " ").title())
                completed = ingestion_state["completed"]
                path_name = stage_path.name
                size_value = None
                if info is not None and "size_bytes" in info:
                    try:
                        size_value = int(info["size_bytes"])
                    except (TypeError, ValueError):
                        size_value = None
                size_suffix = f" ({_format_size(size_value)})" if size_value is not None else ""
                worker_id: int | None = None
                if info is not None and "worker_id" in info:
                    try:
                        worker_id = int(info["worker_id"])
                    except (TypeError, ValueError):
                        worker_id = None

                def _ensure_worker_task(identifier: int) -> _ProgressTask:
                    task = ingestion_worker_tasks.get(identifier)
                    if task is None:
                        task = progress.start("", total=None)
                        ingestion_worker_tasks[identifier] = task
                    return task

                if worker_id is not None and progress_enabled:
                    task = _ensure_worker_task(worker_id)
                    if stage in {"complete", "error", "skipped", "quarantine"}:
                        task.complete("")
                        ingestion_worker_tasks.pop(worker_id, None)
                    else:
                        task.set_description(f"{path_name}{size_suffix} – {label.lower()}")
                    return

                if stage == "complete":
                    ingestion_state["completed"] += 1
                    updated = ingestion_state["completed"]
                    ingestion_task.set_description(
                        f"Completed ({updated}) {path_name}{size_suffix}"
                    )
                elif stage == "error":
                    ingestion_task.set_description(f"Error: {path_name}{size_suffix}")
                elif stage == "skipped":
                    ingestion_task.set_description(
                        f"Skipped {path_name}{size_suffix} ({completed} done)"
                    )
                elif stage == "quarantine":
                    ingestion_task.set_description(
                        f"Quarantined {path_name}{size_suffix} ({completed} done)"
                    )
                else:
                    ingestion_task.set_description(
                        f"{label}: {path_name}{size_suffix} ({completed} done)"
                    )

            result = pipeline.run(
                [source_root],
                on_stage=_ingestion_stage if progress_enabled else None,
                prompt=classification_prompt,
            )
            if not dry_run and vision_captioner is not None:
                vision_captioner.save_cache()
            files_total = len(result.processed)
            ingestion_task.complete(f"Ingestion complete ({files_total} file(s))")

            overall_task: _ProgressTask | None = None
            worker_tasks: dict[int, _ProgressTask] = {}

            if files_total > 0:
                overall_task = progress.start(
                    "Classifying files",
                    total=files_total,
                )

            def _classification_progress(
                event: str,
                processed: int,
                total: int,
                descriptor: FileDescriptor,
                worker_id: int | None,
                duration: float | None,
            ) -> None:
                if overall_task is None:
                    return

                name = descriptor.path.name
                size_text = _format_size(_descriptor_size(descriptor))
                display = f"{name} ({size_text})" if size_text != "?" else name

                if event == "start":
                    if worker_id is None:
                        overall_task.set_description(
                            f"Classifying cached ({processed}/{total}) {display}"
                        )
                        return
                    task = worker_tasks.get(worker_id)
                    if task is None:
                        task = progress.start("", total=None)
                        worker_tasks[worker_id] = task
                    task.set_description(display)
                    return

                if event == "complete":
                    overall_task.advance(description=f"Classified {processed}/{total}")
                    if worker_id is not None:
                        task = worker_tasks.get(worker_id)
                        if task is not None:
                            task.complete("")
                            worker_tasks.pop(worker_id, None)
                    return

            classification_batch = run_classification(
                result.processed,
                classification_prompt=classification_prompt,
                root=source_root,
                dry_run=dry_run,
                config=config,
                cache=classification_cache,
                on_progress=(
                    _classification_progress if progress_enabled and files_total else None
                ),
                max_workers=parallel_workers,
            )
            if overall_task is not None:
                overall_task.complete("Classification complete")

            paired = list(zip_decisions(classification_batch, result.processed))
            descriptor_list = [descriptor for _, descriptor in paired]
            decision_list = [decision for decision, _ in paired]
            confidence_threshold = config.ambiguity.confidence_threshold
            for decision, descriptor in paired:
                if decision is not None and decision.confidence < confidence_threshold:
                    decision.needs_review = True
                    if descriptor.path not in result.needs_review:
                        result.needs_review.append(descriptor.path)

            structure_map: dict[Path, Path] = {}
            structure_task: _ProgressTask | None = None
            if descriptor_list and progress_enabled:
                structure_task = progress.start(
                    f"Planning structure ({len(descriptor_list)} files)",
                    total=None,
                )
            if descriptor_list:
                try:
                    structure_planner = StructurePlannerCls(config.llm)
                    structure_map = structure_planner.propose(
                        descriptor_list,
                        decision_list,
                        source_root=source_root,
                        prompt=structure_prompt_value,
                    )
                    if structure_task is not None:
                        structure_task.complete("Structure plan ready")
                except LLMUnavailableError:
                    if structure_task is not None:
                        structure_task.complete("Structure plan skipped")
                    raise
                except LLMResponseError:
                    if structure_task is not None:
                        structure_task.complete("Structure plan failed")
                    raise
                except Exception as exc:  # pragma: no cover - best-effort hint
                    if structure_task is not None:
                        structure_task.complete("Structure plan skipped")
                    LOGGER.debug("Structure planner unavailable: %s", exc)
            elif structure_task is not None:
                structure_task.complete("Structure plan skipped")

            plan_task = progress.start("Building operation plan")
            plan = planner.build_plan(
                descriptors=descriptor_list,
                decisions=decision_list,
                rename_enabled=config.organization.rename_files,
                root=target_root,
                conflict_strategy=config.organization.conflict_resolution,
                destination_map=structure_map,
            )
            plan_task.complete("Operation plan ready")
            if vision_warning:
                plan.notes.append(vision_warning)
        rename_map = {operation.source: operation.destination for operation in plan.renames}
        move_map = {operation.source: operation.destination for operation in plan.moves}

        final_path_map: dict[Path, Path] = {}
        file_entries: list[dict[str, Any]] = []
        table_rows: list[tuple[str, str, str, str, str, str]] = []

        for decision, descriptor in paired:
            original_path = descriptor.path
            rename_target = rename_map.get(original_path)
            move_key = rename_target if rename_target is not None else original_path
            move_target = move_map.get(move_key)
            final_path = move_target or rename_target or original_path
            final_path_map[original_path] = final_path

            vision_metadata: dict[str, Any] | None = None
            if config.processing.process_images and descriptor.metadata.get("vision_caption"):
                vision_metadata = {
                    "caption": descriptor.metadata.get("vision_caption"),
                    "labels": descriptor.metadata.get("vision_labels"),
                    "confidence": descriptor.metadata.get("vision_confidence"),
                    "reasoning": descriptor.metadata.get("vision_reasoning"),
                }

            file_entries.append(
                {
                    "original_path": original_path.as_posix(),
                    "final_path": final_path.as_posix(),
                    "descriptor": descriptor.model_dump(mode="json"),
                    "classification": decision.model_dump(mode="json")
                    if decision is not None
                    else None,
                    "vision": vision_metadata,
                    "operations": {
                        "rename": rename_target.as_posix() if rename_target is not None else None,
                        "move": move_target.as_posix() if move_target is not None else None,
                    },
                }
            )

            metadata = descriptor.metadata
            relative_path = original_path
            try:
                relative_path = original_path.relative_to(source_root)
            except ValueError:
                pass
            category = decision.primary_category if decision else "-"
            confidence_value = "-"
            status_label = "-"
            if decision is not None:
                if decision.confidence is not None:
                    confidence_value = f"{decision.confidence:.2f}"
                status_label = "Review" if decision.needs_review else "Ok"
            table_rows.append(
                (
                    str(relative_path),
                    descriptor.mime_type,
                    str(metadata.get("size_bytes", "?")),
                    category,
                    confidence_value,
                    status_label,
                )
            )

        llm_metadata = _collect_llm_metadata(config.llm)
        counts = compute_org_counts(result, classification_batch, plan)
        json_payload: dict[str, Any] = {
            "context": {
                "source_root": source_root.as_posix(),
                "destination_root": target_root.as_posix(),
                "copy_mode": copy_mode,
                "dry_run": dry_run,
                "classification_prompt": classification_prompt,
                "structure_prompt": structure_prompt_value,
                # Backwards compatibility: retain legacy key.
                "prompt": classification_prompt,
            },
            "counts": counts,
            "plan": plan.model_dump(mode="json"),
            "files": file_entries,
            "notes": list(plan.notes),
        }
        json_payload["context"]["llm"] = llm_metadata
        json_payload["errors"] = collect_error_payload(result, classification_batch)

        if json_output and dry_run:
            console.print_json(data=json_payload)
            return

        if not json_output:
            table_title = (
                f"Organization preview for {source_root}"
                if not copy_mode
                else f"Organization preview for {source_root} → {target_root}"
            )
            table = Table(title=table_title)
            table.add_column("File", overflow="fold")
            table.add_column("Type")
            table.add_column("Size", justify="right")
            threshold = config.ambiguity.confidence_threshold
            table.add_column("Category")
            table.add_column(f"Confidence ≥ {threshold:.2f}", justify="right")
            table.add_column("Status", justify="center")
            for row in table_rows:
                table.add_row(*row)
            _emit_message(table, mode="detail", quiet=quiet_enabled, summary_only=summary_only)

            llm_summary_text = _llm_summary(llm_metadata)
            _emit_message(
                f"[cyan]LLM configuration: {llm_summary_text}[/cyan]",
                mode="detail",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )

            tree_output = _render_tree(final_path_map.values(), target_root)
            if tree_output:
                tree_mode = "summary" if summary_only else "detail"
                _emit_message(
                    f"[cyan]Proposed file tree for {target_root}:[/cyan]",
                    mode=tree_mode,
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
                for line in tree_output.splitlines():
                    _emit_message(
                        f"  {line}",
                        mode=tree_mode,
                        quiet=quiet_enabled,
                        summary_only=summary_only,
                    )

            classification_total = sum(
                1 for decision in classification_batch.decisions if decision is not None
            )
            review_count = sum(
                1
                for decision in classification_batch.decisions
                if decision is not None and decision.needs_review
            )
            if classification_total:
                _emit_message(
                    f"[cyan]Classification evaluated {classification_total} file(s); "
                    f"{review_count} marked for review.[/cyan]",
                    mode="detail",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

            if result.needs_review:
                _emit_message(
                    f"[yellow]{len(result.needs_review)} files require review based on the current "
                    "confidence threshold.[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

            if result.quarantined:
                _emit_message(
                    f"[yellow]{len(result.quarantined)} files would be quarantined during "
                    "execution.[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

            if plan.metadata_updates:
                _emit_message(
                    f"[cyan]{len(plan.metadata_updates)} metadata update(s) planned.[/cyan]",
                    mode="detail",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

            if plan.notes:
                _emit_message(
                    "[yellow]Plan notes:[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
                for note in plan.notes:
                    _emit_message(
                        f"  - {note}",
                        mode="warning",
                        quiet=quiet_enabled,
                        summary_only=summary_only,
                    )

        if dry_run:
            if not json_output:
                _emit_errors(
                    json_payload["errors"],
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
                summary_metrics = {
                    "dry_run": True,
                    "processed": counts["processed"],
                    "needs_review": counts["needs_review"],
                    "quarantined": counts["quarantined"],
                    "renames": counts["renames"],
                    "moves": counts["moves"],
                    "conflicts": counts["conflicts"],
                    "errors": counts["errors"],
                }
                _emit_message(
                    _format_summary_line("Organization", target_root, summary_metrics),
                    mode="summary",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
                _emit_message(
                    "[yellow]Dry run selected; skipping state persistence.[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
            return

        repository = StateRepositoryCls()
        state_dir = repository.initialize(target_root)
        quarantine_dir = state_dir / "quarantine"
        if result.quarantined and config.processing.corrupted_files.action == "quarantine":
            moved_paths: list[Path] = []
            for original in result.quarantined:
                target = quarantine_dir / original.name
                counter = 1
                while target.exists():
                    target = target.with_name(f"{original.stem}-{counter}{original.suffix}")
                    counter += 1
                try:
                    shutil.move(str(original), str(target))
                except Exception as exc:  # pragma: no cover - filesystem issues
                    _emit_message(
                        f"[red]Failed to quarantine {original}: {exc}[/red]",
                        mode="error",
                        quiet=quiet_enabled,
                        summary_only=summary_only,
                    )
                    result.errors.append(f"{original}: quarantine failed ({exc})")
                else:
                    moved_paths.append(target)
            result.quarantined = moved_paths
            if moved_paths:
                _emit_message(
                    f"[yellow]Moved {len(moved_paths)} files to quarantine.[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
        try:
            state = repository.load(target_root)
        except MissingStateError:
            state = CollectionStateCls(root=str(target_root))

        snapshot: dict[str, Any] | None = None
        if not dry_run:
            snapshot = build_original_snapshot(
                [descriptor for _, descriptor in paired], source_root
            )

        executor = OperationExecutorCls(
            staging_root=state_dir / "staging",
            copy_mode=copy_mode,
            source_root=source_root,
        )
        events: list[OperationEvent] = []
        try:
            if snapshot is not None:
                repository.write_original_structure(target_root, snapshot)
            with _ProgressScope(progress_enabled) as progress:
                apply_task = progress.start("Applying operation plan")
                events = executor.apply(plan, target_root)
                apply_task.complete("Operation plan applied")
        except Exception as exc:
            raise click.ClickException(
                f"Failed to apply organization plan: {exc}. "
                "Verify file permissions and available disk space."
            ) from exc

        for decision, descriptor in paired:
            original_path = descriptor.path
            final_path = final_path_map.get(original_path, original_path)
            old_relative = relative_to_collection(original_path, target_root)

            descriptor.path = final_path
            descriptor.display_name = descriptor.path.name

            record = descriptor_to_record(descriptor, decision, target_root)

            state.files.pop(old_relative, None)
            state.files[record.path] = record

        repository.save(target_root, state)
        if events:
            repository.append_history(target_root, events)

        if not json_output:
            _emit_message(
                f"[green]Persisted state for {len(result.processed)} files.[/green]",
                mode="detail",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
            if copy_mode:
                _emit_message(
                    f"[cyan]Copy mode enabled; organized files written to {target_root} while "
                    f"preserving originals at {source_root}.[/cyan]",
                    mode="summary",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

        log_path = state_dir / "dorgy.log"
        try:
            with log_path.open("a", encoding="utf-8") as log_file:
                timestamp = datetime.now(timezone.utc).isoformat()
                log_file.write(
                    f"[{timestamp}] processed={len(result.processed)} "
                    f"needs_review={len(result.needs_review)} "
                    f"quarantined={len(result.quarantined)} "
                    f"classification={len(classification_batch.decisions)} "
                    f"classification_errors={len(classification_batch.errors)} "
                    f"renames={len(plan.renames)} moves={len(plan.moves)} "
                    f"errors={len(result.errors)}\n"
                )
                for error in result.errors:
                    log_file.write(f"  error: {error}\n")
                for error in classification_batch.errors:
                    log_file.write(f"  classification_error: {error}\n")
                for q_path in result.quarantined:
                    log_file.write(f"  quarantined: {q_path}\n")
                for rename_op in plan.renames:
                    log_file.write(f"  rename: {rename_op.source} -> {rename_op.destination}\n")
                for move_op in plan.moves:
                    log_file.write(f"  move: {move_op.source} -> {move_op.destination}\n")
        except OSError as exc:  # pragma: no cover - logging best effort
            _emit_message(
                f"[yellow]Unable to update log file: {exc}[/yellow]",
                mode="warning",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )

        counts = compute_org_counts(result, classification_batch, plan)
        errors_payload = collect_error_payload(result, classification_batch)
        json_payload["counts"] = counts
        json_payload["errors"] = errors_payload
        json_payload["history"] = [event.model_dump(mode="json") for event in events]
        json_payload["state"] = {
            "path": str(state_dir / "state.json"),
            "files_tracked": len(state.files),
        }
        json_payload["log_path"] = str(log_path)
        json_payload["quarantine"] = [path.as_posix() for path in result.quarantined]
        json_payload["context"]["state_dir"] = state_dir.as_posix()

        if not json_output:
            _emit_errors(errors_payload, quiet=quiet_enabled, summary_only=summary_only)
            summary_metrics = {
                "processed": counts["processed"],
                "needs_review": counts["needs_review"],
                "quarantined": counts["quarantined"],
                "renames": counts["renames"],
                "moves": counts["moves"],
                "conflicts": counts["conflicts"],
                "errors": counts["errors"],
            }
            _emit_message(
                _format_summary_line("Organization", target_root, summary_metrics),
                mode="summary",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
        else:
            console.print_json(data=json_payload)
    except ShutdownRequested:
        quiet_flag = mode.quiet if mode is not None else quiet
        summary_flag = mode.summary if mode is not None else summary_mode
        if not json_enabled:
            _emit_message(
                "[yellow]Organization cancelled by user request.[/yellow]",
                mode="summary",
                quiet=quiet_flag,
                summary_only=summary_flag,
            )
    except ConfigError as exc:
        _handle_cli_error(str(exc), code="config_error", json_output=json_enabled, original=exc)
    except LLMUnavailableError as exc:
        _handle_cli_error(
            str(exc),
            code="llm_unavailable",
            json_output=json_enabled,
            original=exc,
        )
    except LLMResponseError as exc:
        _handle_cli_error(
            str(exc),
            code="llm_response_error",
            json_output=json_enabled,
            original=exc,
        )
    except click.ClickException as exc:
        _handle_cli_error(str(exc), code="cli_error", json_output=json_enabled, original=exc)
    except Exception as exc:
        _handle_cli_error(
            f"Unexpected error while organizing files: {exc}",
            code="internal_error",
            json_output=json_enabled,
            details={"exception": type(exc).__name__},
            original=exc,
        )


@cli.command()
@click.argument("paths", nargs=-1, type=click.Path(exists=True, file_okay=False, path_type=str))
@recursive_option("Include subdirectories for monitoring.")
@classify_prompt_file_option("Read classification guidance from a text file.")
@classify_prompt_option("Provide extra classification guidance.")
@structure_prompt_file_option("Read extra structure instructions from a file.")
@structure_prompt_option("Provide extra structure instructions.")
@output_option("Destination root when copying organized files.")
@dry_run_option("Preview actions without mutating files.")
@click.option("--debounce", type=float, help="Override debounce interval in seconds.")
@json_option("Emit JSON describing watch batches.")
@summary_option()
@quiet_option()
@click.option(
    "--allow-deletions",
    is_flag=True,
    help="Allow watch runs to drop state entries when files are deleted or leave the collection.",
)
@click.option("--once", is_flag=True, help="Process current contents once and exit.")
@click.pass_context
def watch(
    ctx: click.Context,
    paths: tuple[str, ...],
    recursive: bool,
    classify_prompt: str | None,
    classify_prompt_file: str | None,
    structure_prompt: str | None,
    structure_prompt_file: str | None,
    output: str | None,
    dry_run: bool,
    debounce: float | None,
    json_output: bool,
    summary_mode: bool,
    quiet: bool,
    allow_deletions: bool,
    once: bool,
) -> None:
    """Continuously monitor PATHS and organize changes as they arrive."""

    from dorgy.cli_support import resolve_prompt_text

    WatchService = _load_dependency("WatchService", "dorgy.watch", "WatchService")
    LLMUnavailableError = _load_dependency(
        "LLMUnavailableError", "dorgy.classification.exceptions", "LLMUnavailableError"
    )
    LLMResponseError = _load_dependency(
        "LLMResponseError", "dorgy.classification.exceptions", "LLMResponseError"
    )

    if not paths:
        raise click.ClickException("Provide at least one PATH to monitor.")

    try:
        classification_prompt = resolve_prompt_text(classify_prompt, classify_prompt_file)
    except (OSError, UnicodeDecodeError) as exc:
        raise click.ClickException(
            f"Failed to read classification prompt file {classify_prompt_file}: {exc}"
        ) from exc
    try:
        structure_prompt_value = resolve_prompt_text(structure_prompt, structure_prompt_file)
    except (OSError, UnicodeDecodeError) as exc:
        raise click.ClickException(
            f"Failed to read structure prompt file {structure_prompt_file}: {exc}"
        ) from exc
    if structure_prompt_value is None:
        structure_prompt_value = classification_prompt

    try:
        manager = ConfigManager()
        manager.ensure_exists()
        config = manager.load()
    except ConfigError as exc:
        _handle_cli_error(str(exc), code="config_error", json_output=json_output)
        return

    mode: ModeResolution = resolve_mode_settings(
        ctx,
        config.cli,
        quiet_flag=quiet,
        summary_flag=summary_mode,
        json_flag=json_output,
    )
    quiet_enabled = mode.quiet
    summary_only = mode.summary
    json_output = mode.json_output
    progress_enabled = (
        config.cli.progress_enabled
        and console.is_terminal
        and not json_output
        and not quiet_enabled
        and not summary_only
    )

    allow_source = ctx.get_parameter_source("allow_deletions")
    if allow_source == ParameterSource.COMMANDLINE:
        allow_deletions_enabled = allow_deletions
    else:
        allow_deletions_enabled = config.processing.watch.allow_deletions

    if debounce is not None and debounce <= 0:
        raise click.ClickException("--debounce must be greater than zero.")

    root_paths = [Path(path).expanduser().resolve() for path in paths]
    output_path = Path(output).expanduser().resolve() if output else None
    if output_path is not None and len(root_paths) != 1:
        raise click.ClickException("--output currently supports a single PATH.")

    recursive_enabled = recursive or config.processing.recurse_directories

    try:
        service = WatchService(
            config,
            roots=root_paths,
            classification_prompt=classification_prompt,
            structure_prompt=structure_prompt_value,
            output=output_path,
            dry_run=dry_run,
            recursive=recursive_enabled,
            debounce_override=debounce,
            allow_deletions=allow_deletions_enabled,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    except LLMUnavailableError as exc:
        _handle_cli_error(str(exc), code="llm_unavailable", json_output=json_output, original=exc)
        return
    except LLMResponseError as exc:
        _handle_cli_error(
            str(exc), code="llm_response_error", json_output=json_output, original=exc
        )
        return

    if once:
        with _ProgressScope(progress_enabled) as progress:
            task = progress.start("Processing watch batch")
            try:
                batches = service.process_once()
            except LLMUnavailableError as exc:
                task.complete("Watch run aborted")
                _handle_cli_error(
                    str(exc), code="llm_unavailable", json_output=json_output, original=exc
                )
                return
            except LLMResponseError as exc:
                task.complete("Watch run aborted")
                _handle_cli_error(
                    str(exc),
                    code="llm_response_error",
                    json_output=json_output,
                    original=exc,
                )
                return
            except ShutdownRequested:
                task.complete("Watch run aborted")
                if not json_output:
                    _emit_message(
                        "[yellow]Watch stopped by user request.[/yellow]",
                        mode="summary",
                        quiet=quiet_enabled,
                        summary_only=summary_only,
                    )
                return
            task.complete("Watch run complete")
        if json_output:
            console.print_json(data={"batches": [batch.json_payload for batch in batches]})
            return
        if not batches:
            _emit_message(
                "[yellow]No files matched the watch criteria during the one-shot run.[/yellow]",
                mode="warning",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
            return
        for batch in batches:
            _emit_watch_batch(
                batch,
                json_output=False,
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
        return

    if not json_output:
        monitored = ", ".join(str(path) for path in root_paths)
        _emit_message(
            f"[cyan]Watching {monitored}. Press Ctrl+C to stop.[/cyan]",
            mode="detail",
            quiet=quiet_enabled,
            summary_only=summary_only,
        )

    try:
        service.watch(
            lambda batch: _emit_watch_batch(
                batch,
                json_output=json_output,
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
        )
    except (KeyboardInterrupt, ShutdownRequested):
        service.stop()
        if not json_output:
            _emit_message(
                "[yellow]Watch stopped by user request.[/yellow]",
                mode="summary",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
    except LLMUnavailableError as exc:
        _handle_cli_error(str(exc), code="llm_unavailable", json_output=json_output, original=exc)
    except LLMResponseError as exc:
        _handle_cli_error(
            str(exc), code="llm_response_error", json_output=json_output, original=exc
        )
    except RuntimeError as exc:
        _handle_cli_error(
            str(exc), code="watch_runtime_error", json_output=json_output, original=exc
        )


@cli.group()
def config() -> None:
    """Manage Dorgy configuration files and overrides."""


@config.command("view")
@click.option("--no-env", is_flag=True, help="Ignore environment overrides when displaying output.")
def config_view(no_env: bool) -> None:
    """Display the effective configuration after applying precedence rules."""
    manager = ConfigManager()
    try:
        manager.ensure_exists()
        config = manager.load(include_env=not no_env)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    yaml_text = yaml.safe_dump(config.model_dump(mode="python"), sort_keys=False)
    console.print(Syntax(yaml_text, "yaml", word_wrap=True))


@config.command("set")
@click.argument("key")
@click.option("--value", required=True, help="Value to assign to KEY.")
def config_set(key: str, value: str) -> None:
    """Persist a configuration value expressed as a dotted KEY."""
    manager = ConfigManager()
    manager.ensure_exists()

    before = manager.read_text().splitlines()
    segments = [segment.strip() for segment in key.split(".") if segment.strip()]
    if not segments:
        raise click.ClickException("KEY must specify a dotted path such as 'llm.temperature'.")

    try:
        parsed_value = yaml.safe_load(value)
    except yaml.YAMLError as exc:
        raise click.ClickException(f"Unable to parse value: {exc}") from exc

    file_data = manager.load_file_overrides()

    try:
        _assign_nested(file_data, segments, parsed_value)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    try:
        resolve_with_precedence(defaults=DorgyConfig(), file_overrides=file_data)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    manager.save(file_data)
    after = manager.read_text().splitlines()

    diff = list(
        difflib.unified_diff(
            before,
            after,
            fromfile="config.yaml (before)",
            tofile="config.yaml (after)",
            lineterm="",
        )
    )

    if diff:
        console.print(Syntax("\n".join(diff), "diff", word_wrap=False))
    else:
        console.print("[yellow]No changes applied; value already up to date.[/yellow]")
        return

    console.print(f"[green]Updated {'.'.join(segments)}.[/green]")


@config.command("edit")
def config_edit() -> None:
    """Open the configuration file in an interactive editor session."""
    manager = ConfigManager()
    manager.ensure_exists()

    original = manager.read_text()
    edited = click.edit(original, extension=".yaml")

    if edited is None:
        console.print("[yellow]Edit cancelled; no changes applied.[/yellow]")
        return

    if edited == original:
        console.print("[yellow]No changes detected.[/yellow]")
        return

    try:
        parsed = yaml.safe_load(edited) or {}
    except yaml.YAMLError as exc:
        raise click.ClickException(f"Invalid YAML: {exc}") from exc

    if not isinstance(parsed, dict):
        raise click.ClickException("Configuration file must contain a top-level mapping.")

    try:
        resolve_with_precedence(defaults=DorgyConfig(), file_overrides=parsed)
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    manager.save(parsed)
    console.print("[green]Configuration updated successfully.[/green]")


@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=str))
@click.option(
    "--search",
    "query",
    type=str,
    help="Free-text search across paths, tags, and categories.",
)
@click.option("--name", type=str, help="Filename glob filter (e.g., '*.pdf').")
@click.option(
    "--tags",
    type=str,
    help="Comma-separated tag filters (matches all provided tags).",
)
@click.option(
    "--categories",
    type=str,
    help="Comma-separated category filters (matches all provided categories).",
)
@click.option(
    "--before",
    type=str,
    help="Return results with modified time before this ISO 8601 timestamp.",
)
@click.option(
    "--after",
    type=str,
    help="Return results with modified time on or after this ISO 8601 timestamp.",
)
@click.option(
    "--needs-review/--any-review",
    "needs_review",
    default=None,
    help="Filter results by needs-review flag (default is to include all).",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    show_default=False,
    help="Maximum number of results to return (defaults to configuration).",
)
@json_option("Emit search results as JSON.")
@summary_option()
@quiet_option()
@click.pass_context
def search(
    ctx: click.Context,
    path: str,
    query: str | None,
    name: str | None,
    tags: str | None,
    categories: str | None,
    before: str | None,
    after: str | None,
    needs_review: bool | None,
    limit: int | None,
    json_output: bool,
    summary_mode: bool,
    quiet: bool,
) -> None:
    """Search within an organized collection's state metadata."""

    StateRepository = _load_dependency("StateRepository", "dorgy.state", "StateRepository")
    MissingStateError = _load_dependency("MissingStateError", "dorgy.state", "MissingStateError")

    json_enabled = json_output
    try:
        manager = ConfigManager()
        manager.ensure_exists()
        config = manager.load()

        mode: ModeResolution = resolve_mode_settings(
            ctx,
            config.cli,
            quiet_flag=quiet,
            summary_flag=summary_mode,
            json_flag=json_output,
        )
        quiet_enabled = mode.quiet
        summary_only = mode.summary
        json_enabled = mode.json_output

        effective_limit = limit if limit is not None else config.cli.search_default_limit
        if effective_limit is not None and effective_limit <= 0:
            raise click.ClickException("--limit must be greater than zero.")

        before_dt = _parse_datetime_option("--before", before)
        after_dt = _parse_datetime_option("--after", after)
        if before_dt and after_dt and after_dt > before_dt:
            raise click.ClickException("--after must be earlier than or equal to --before.")

        tag_terms = _parse_csv_option(tags)
        category_terms = _parse_csv_option(categories)
        tag_filters = {value.lower() for value in tag_terms}
        category_filters = {value.lower() for value in category_terms}
        query_text = query.lower().strip() if query else None
        name_pattern = name.strip() if name else None

        root = Path(path).expanduser().resolve()
        repository = StateRepository()
        state = repository.load(root)

        matches: list[tuple[str, FileRecord, datetime | None, Path]] = []
        fallback_timestamp = datetime.min.replace(tzinfo=timezone.utc)

        for rel_path, record in state.files.items():
            normalized_rel = _normalise_state_key(rel_path)
            if name_pattern and not fnmatch.fnmatch(Path(normalized_rel).name, name_pattern):
                continue

            record_tags = [tag for tag in record.tags if tag]
            record_categories = [category for category in record.categories if category]
            record_tags_lower = {tag.lower() for tag in record_tags}
            record_categories_lower = {category.lower() for category in record_categories}

            if tag_filters and not tag_filters.issubset(record_tags_lower):
                continue
            if category_filters and not category_filters.issubset(record_categories_lower):
                continue

            if needs_review is not None and record.needs_review != needs_review:
                continue

            last_modified = record.last_modified
            if last_modified is not None:
                last_modified_utc = (
                    last_modified.astimezone(timezone.utc)
                    if last_modified.tzinfo is not None
                    else last_modified.replace(tzinfo=timezone.utc)
                )
            else:
                last_modified_utc = None

            if before_dt and (last_modified_utc is None or last_modified_utc >= before_dt):
                continue
            if after_dt and (last_modified_utc is None or last_modified_utc < after_dt):
                continue

            if query_text:
                haystack = [
                    normalized_rel.lower(),
                    " ".join(record_tags_lower),
                    " ".join(record_categories_lower),
                    (record.rename_suggestion or "").lower(),
                    (record.reasoning or "").lower(),
                ]
                if not any(query_text in field for field in haystack if field):
                    continue

            absolute_path = (root / Path(normalized_rel)).resolve()
            matches.append((normalized_rel, record, last_modified_utc, absolute_path))

        total_matches = len(matches)
        matches.sort(
            key=lambda entry: entry[2] if entry[2] is not None else fallback_timestamp,
            reverse=True,
        )

        displayed_matches = matches[:effective_limit] if effective_limit is not None else matches
        truncated = total_matches - len(displayed_matches)
        displayed_needs_review = sum(
            1 for _, record, _, _ in displayed_matches if record.needs_review
        )

        json_results = [
            {
                "relative_path": rel_path,
                "absolute_path": str(abs_path),
                "tags": list(record.tags),
                "categories": list(record.categories),
                "needs_review": record.needs_review,
                "confidence": record.confidence,
                "last_modified": last_modified.isoformat() if last_modified else None,
                "hash": record.hash,
                "rename_suggestion": record.rename_suggestion,
            }
            for rel_path, record, last_modified, abs_path in displayed_matches
        ]

        counts: dict[str, Any] = {
            "matches": len(displayed_matches),
            "total": total_matches,
            "needs_review": displayed_needs_review,
        }
        if effective_limit is not None:
            counts["limit"] = effective_limit
        if truncated > 0:
            counts["truncated"] = truncated

        context_payload = {
            "root": str(root),
            "query": query,
            "name": name_pattern,
            "tags": tag_terms,
            "categories": category_terms,
            "before": before_dt.isoformat() if before_dt else None,
            "after": after_dt.isoformat() if after_dt else None,
            "needs_review": needs_review,
            "limit": effective_limit,
        }

        json_payload = {
            "context": context_payload,
            "counts": counts,
            "results": json_results,
        }

        if json_enabled:
            console.print_json(data=json_payload)
            return

        if not summary_only:
            if displayed_matches:
                table = Table(title=f"Search results for {root}")
                table.add_column("Path", overflow="fold")
                table.add_column("Tags", overflow="fold")
                table.add_column("Categories", overflow="fold")
                table.add_column("Confidence", justify="right")
                table.add_column("Needs Review", justify="center")
                table.add_column("Modified")
                for rel_path, record, last_modified, _ in displayed_matches:
                    table.add_row(
                        rel_path,
                        ", ".join(record.tags) or "-",
                        ", ".join(record.categories) or "-",
                        f"{record.confidence:.2f}" if record.confidence is not None else "-",
                        "Yes" if record.needs_review else "No",
                        last_modified.isoformat() if last_modified else "-",
                    )
                _emit_message(table, mode="detail", quiet=quiet_enabled, summary_only=summary_only)
            else:
                _emit_message(
                    "[yellow]No matching records found.[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

        if truncated > 0:
            truncated_msg = (
                f"[yellow]{truncated} additional result(s) omitted due to limit "
                f"{effective_limit}.[/yellow]"
            )
            _emit_message(
                truncated_msg,
                mode="warning",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )

        summary_metrics: dict[str, Any] = {
            "matches": len(displayed_matches),
            "total": total_matches,
            "needs_review": displayed_needs_review,
        }
        if effective_limit is not None:
            summary_metrics["limit"] = effective_limit
        if truncated > 0:
            summary_metrics["truncated"] = truncated

        _emit_message(
            _format_summary_line("Search", root, summary_metrics),
            mode="summary",
            quiet=quiet_enabled,
            summary_only=summary_only,
        )
    except ConfigError as exc:
        _handle_cli_error(str(exc), code="config_error", json_output=json_enabled, original=exc)
    except MissingStateError as exc:
        _handle_cli_error(
            f"No organization state found for {path}. Run `dorgy org {path}` before searching.",
            code="missing_state",
            json_output=json_enabled,
            original=exc,
        )
    except click.ClickException as exc:
        _handle_cli_error(str(exc), code="cli_error", json_output=json_enabled, original=exc)
    except Exception as exc:
        _handle_cli_error(
            f"Unexpected error while searching: {exc}",
            code="internal_error",
            json_output=json_enabled,
            details={"exception": type(exc).__name__},
            original=exc,
        )


@cli.command()
@click.argument("source", type=click.Path(exists=True, path_type=str))
@click.argument("destination", type=click.Path(path_type=str))
@click.option(
    "--conflict-strategy",
    type=click.Choice(["append_number", "timestamp", "skip"], case_sensitive=False),
    help="Conflict resolution strategy when the destination already exists.",
)
@dry_run_option("Preview move/rename without applying changes.")
@json_option("Emit JSON describing the move operation.")
@summary_option()
@quiet_option()
@click.pass_context
def mv(
    ctx: click.Context,
    source: str,
    destination: str,
    conflict_strategy: str | None,
    dry_run: bool,
    json_output: bool,
    summary_mode: bool,
    quiet: bool,
) -> None:
    """Move or rename tracked files within an organized collection."""

    from dorgy.cli_support import relative_to_collection

    OperationExecutor = _load_dependency(
        "OperationExecutor", "dorgy.organization.executor", "OperationExecutor"
    )
    OperationPlan = _load_dependency("OperationPlan", "dorgy.organization.models", "OperationPlan")
    MoveOperation = _load_dependency("MoveOperation", "dorgy.organization.models", "MoveOperation")
    StateRepository = _load_dependency("StateRepository", "dorgy.state", "StateRepository")
    MissingStateError = _load_dependency("MissingStateError", "dorgy.state", "MissingStateError")

    json_enabled = json_output
    try:
        manager = ConfigManager()
        manager.ensure_exists()
        config = manager.load()

        mode: ModeResolution = resolve_mode_settings(
            ctx,
            config.cli,
            quiet_flag=quiet,
            summary_flag=summary_mode,
            json_flag=json_output,
        )
        quiet_enabled = mode.quiet
        summary_only = mode.summary
        json_enabled = mode.json_output

        default_strategy = (
            config.cli.move_conflict_strategy or config.organization.conflict_resolution
        )
        strategy = (conflict_strategy or default_strategy or "append_number").lower()
        if strategy not in {"append_number", "timestamp", "skip"}:
            strategy = "append_number"

        source_path = Path(source).expanduser().resolve()
        if ".dorgy" in source_path.parts:
            raise click.ClickException("Cannot move files within the .dorgy metadata directory.")

        root = _detect_collection_root(source_path)
        repository = StateRepository()
        try:
            state = repository.load(root)
        except MissingStateError as exc:
            missing_state_msg = (
                f"No organization state found for {root}. "
                f"Run `dorgy org {root}` before moving files."
            )
            raise click.ClickException(missing_state_msg) from exc

        dest_candidate_input = Path(destination).expanduser()
        if dest_candidate_input.is_absolute():
            dest_candidate = dest_candidate_input
        else:
            dest_candidate = root / dest_candidate_input
        dest_candidate = dest_candidate.resolve()

        if dest_candidate.exists() and dest_candidate.is_dir():
            destination_path = (dest_candidate / source_path.name).resolve()
        else:
            destination_path = dest_candidate

        if ".dorgy" in destination_path.parts:
            raise click.ClickException(
                "Destination cannot be inside the .dorgy metadata directory."
            )

        try:
            destination_path.relative_to(root)
        except ValueError:
            raise click.ClickException(
                "Destination must reside within the same collection root as the source."
            ) from None

        resolved_path, conflict_applied, note, skipped_operation = _resolve_move_destination(
            source_path, destination_path, strategy
        )

        if resolved_path is not None and resolved_path.resolve() == source_path.resolve():
            skipped_operation = True

        if resolved_path is not None and ".dorgy" in resolved_path.parts:
            raise click.ClickException(
                "Destination cannot be inside the .dorgy metadata directory."
            )

        if resolved_path is not None:
            try:
                resolved_path.relative_to(root)
            except ValueError:
                raise click.ClickException(
                    "Resolved destination would leave the collection root; adjust the target path."
                ) from None

        plan = OperationPlan()
        if note:
            plan.notes.append(note)

        counts: dict[str, Any] = {
            "moved": 0,
            "skipped": 0,
            "conflicts": 1 if conflict_applied else 0,
            "changes": 0,
        }
        changes: list[tuple[str, str]] = []
        events: list[OperationEvent] = []

        if skipped_operation or resolved_path is None:
            counts["skipped"] = 1
        else:
            counts["moved"] = 1
            changes = _plan_state_changes(state, root, source_path, resolved_path)
            counts["changes"] = len(changes)
            plan.moves.append(
                MoveOperation(
                    source=source_path,
                    destination=resolved_path,
                    conflict_strategy=strategy,
                    conflict_applied=conflict_applied,
                )
            )

        source_rel = _normalise_state_key(relative_to_collection(source_path, root))
        resolved_rel = (
            _normalise_state_key(relative_to_collection(resolved_path, root))
            if resolved_path is not None
            else None
        )

        if not skipped_operation and resolved_path is not None:
            executor = OperationExecutor(staging_root=root / ".dorgy" / "staging")
            if dry_run:
                executor.apply(plan, root, dry_run=True)
            else:
                try:
                    events = executor.apply(plan, root)
                except Exception as exc:
                    failure_msg = (
                        "Failed to apply move operation: "
                        f"{exc}. Check file permissions and availability."
                    )
                    raise click.ClickException(failure_msg) from exc
                _apply_state_changes(state, changes)
                repository.save(root, state)
                if events:
                    repository.append_history(root, events)

        changes_payload = [
            {"from": _normalise_state_key(old), "to": _normalise_state_key(new)}
            for old, new in changes
        ]
        json_payload: dict[str, Any] = {
            "context": {
                "root": str(root),
                "source": source_path.as_posix(),
                "requested_destination": dest_candidate_input.as_posix(),
                "resolved_destination": resolved_path.as_posix() if resolved_path else None,
                "strategy": strategy,
                "dry_run": dry_run,
                "skipped": skipped_operation,
            },
            "counts": counts,
            "plan": plan.model_dump(mode="json"),
            "changes": changes_payload,
        }
        if plan.notes:
            json_payload["notes"] = list(plan.notes)
        if events:
            json_payload["history"] = [event.model_dump(mode="json") for event in events]
        if not dry_run and not skipped_operation:
            json_payload["state"] = {
                "path": str(root / ".dorgy" / "state.json"),
                "files_tracked": len(state.files),
            }

        if json_enabled:
            console.print_json(data=json_payload)
            return

        if not summary_only:
            if skipped_operation:
                message = (
                    "[yellow]Move skipped due to conflict strategy.[/yellow]"
                    if strategy == "skip"
                    else "[yellow]Move skipped; destination matches source.[/yellow]"
                )
                _emit_message(
                    message, mode="warning", quiet=quiet_enabled, summary_only=summary_only
                )
            elif dry_run:
                _emit_message(
                    f"[yellow]Dry run: would move {source_rel} -> {resolved_rel}.[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
            else:
                _emit_message(
                    f"[green]Moved {source_rel} -> {resolved_rel}.[/green]",
                    mode="detail",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

            if plan.notes:
                _emit_message(
                    "[yellow]Notes:[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
                for entry in plan.notes:
                    _emit_message(
                        f"  - {entry}",
                        mode="warning",
                        quiet=quiet_enabled,
                        summary_only=summary_only,
                    )

        summary_metrics: dict[str, Any] = {
            "moved": counts["moved"],
            "skipped": counts["skipped"],
            "conflicts": counts["conflicts"],
        }
        if dry_run:
            summary_metrics["dry_run"] = True
        _emit_message(
            _format_summary_line("Move", root, summary_metrics),
            mode="summary",
            quiet=quiet_enabled,
            summary_only=summary_only,
        )
    except ConfigError as exc:
        _handle_cli_error(str(exc), code="config_error", json_output=json_enabled, original=exc)
    except MissingStateError as exc:
        _handle_cli_error(
            f"No organization state found for {source}. Run `dorgy org` before moving files.",
            code="missing_state",
            json_output=json_enabled,
            original=exc,
        )
    except click.ClickException as exc:
        _handle_cli_error(str(exc), code="cli_error", json_output=json_enabled, original=exc)
    except Exception as exc:
        _handle_cli_error(
            f"Unexpected error while moving files: {exc}",
            code="internal_error",
            json_output=json_enabled,
            details={"exception": type(exc).__name__},
            original=exc,
        )


@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=str))
@json_option("Emit status information as JSON.")
@click.option(
    "--history",
    "history_limit",
    type=int,
    default=None,
    show_default=False,
    help="Number of recent history entries to include (defaults to configuration).",
)
@summary_option()
@quiet_option()
@click.pass_context
def status(
    ctx: click.Context,
    path: str,
    json_output: bool,
    history_limit: int | None,
    summary_mode: bool,
    quiet: bool,
) -> None:
    """Display a summary of the collection state for PATH."""

    StateRepository = _load_dependency("StateRepository", "dorgy.state", "StateRepository")
    MissingStateError = _load_dependency("MissingStateError", "dorgy.state", "MissingStateError")
    StateError = _load_dependency("StateError", "dorgy.state", "StateError")

    json_enabled = json_output
    try:
        manager = ConfigManager()
        manager.ensure_exists()
        config = manager.load()

        explicit_history = ctx.get_parameter_source("history_limit") == ParameterSource.COMMANDLINE

        mode: ModeResolution = resolve_mode_settings(
            ctx,
            config.cli,
            quiet_flag=quiet,
            summary_flag=summary_mode,
            json_flag=json_output,
        )
        quiet_enabled = mode.quiet
        summary_only = mode.summary
        json_enabled = mode.json_output

        effective_history = (
            history_limit
            if explicit_history and history_limit is not None
            else config.cli.status_history_limit
        )

        root = Path(path).expanduser().resolve()
        repository = StateRepository()

        try:
            state = repository.load(root)
        except MissingStateError as exc:
            raise click.ClickException(
                f"No organization state found for {root}. Run `dorgy org {root}` first."
            ) from exc

        files_total = len(state.files)
        needs_review_count = sum(1 for record in state.files.values() if record.needs_review)
        tagged_count = sum(1 for record in state.files.values() if record.tags)

        snapshot_payload: dict[str, Any] | None = None
        snapshot_error = None
        try:
            snapshot_payload = repository.load_original_structure(root)
        except StateError as exc:
            snapshot_error = str(exc)

        history_error = None
        history_limit_value = max(0, effective_history)
        history_events: list[OperationEvent] = []
        if history_limit_value > 0:
            try:
                history_events = repository.read_history(root, limit=history_limit_value)
            except StateError as exc:
                history_error = str(exc)

        plan_summary: dict[str, Any] | None = None
        plan_error = None
        plan_path = root / ".dorgy" / "last_plan.json"
        if plan_path.exists():
            try:
                plan_data = json.loads(plan_path.read_text(encoding="utf-8"))
                plan_summary = {
                    "renames": len(plan_data.get("renames", [])),
                    "moves": len(plan_data.get("moves", [])),
                    "metadata_updates": len(plan_data.get("metadata_updates", [])),
                }
            except json.JSONDecodeError as exc:
                plan_error = str(exc)

        needs_review_dir = root / ".dorgy" / "needs-review"
        review_entries = (
            sorted(path.name for path in needs_review_dir.iterdir())
            if needs_review_dir.exists()
            else []
        )

        quarantine_dir = root / ".dorgy" / "quarantine"
        quarantine_entries = (
            sorted(path.name for path in quarantine_dir.iterdir())
            if quarantine_dir.exists()
            else []
        )

        counts = {
            "files": files_total,
            "needs_review": needs_review_count,
            "tagged": tagged_count,
            "history_entries": len(history_events),
            "needs_review_dir": len(review_entries),
            "quarantine_dir": len(quarantine_entries),
        }

        state_summary = {
            "root": str(root),
            "created_at": state.created_at.isoformat(),
            "updated_at": state.updated_at.isoformat(),
            "plan": plan_summary,
            "history": [event.model_dump(mode="json") for event in history_events],
        }

        directories_preview = {
            "needs_review": review_entries[:5],
            "quarantine": quarantine_entries[:5],
        }

        error_summary: dict[str, str] = {}
        if snapshot_error:
            error_summary["snapshot"] = snapshot_error
        if history_error:
            error_summary["history"] = history_error
        if plan_error:
            error_summary["last_plan"] = plan_error

        if json_enabled:
            payload = {
                "context": {"root": str(root)},
                "counts": counts,
                **state_summary,
                "snapshot": snapshot_payload,
                "directories": directories_preview,
            }
            if error_summary:
                payload["errors"] = error_summary
            console.print_json(data=payload)
            return

        table = Table(title=f"Status for {root}")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Files tracked", str(files_total))
        table.add_row("Needs review (state)", str(needs_review_count))
        table.add_row("Tagged files", str(tagged_count))
        table.add_row("Created", state.created_at.isoformat())
        table.add_row("Last updated", state.updated_at.isoformat())
        table.add_row("Needs-review dir entries", str(len(review_entries)))
        table.add_row("Quarantine dir entries", str(len(quarantine_entries)))
        if plan_summary is not None:
            table.add_row("Last plan renames", str(plan_summary.get("renames", 0)))
            table.add_row("Last plan moves", str(plan_summary.get("moves", 0)))
            table.add_row(
                "Last plan metadata updates", str(plan_summary.get("metadata_updates", 0))
            )
        elif plan_error:
            table.add_row("Last plan", f"Error: {plan_error}")
        _emit_message(table, mode="detail", quiet=quiet_enabled, summary_only=summary_only)

        if snapshot_payload:
            generated_at = snapshot_payload.get("generated_at", "unknown")
            entry_count = len(snapshot_payload.get("entries", []))
            _emit_message(
                f"[cyan]Snapshot generated at {generated_at} with {entry_count} entries.[/cyan]",
                mode="detail",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
        elif snapshot_error:
            _emit_message(
                f"[yellow]Unable to load snapshot: {snapshot_error}[/yellow]",
                mode="warning",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )

        if review_entries:
            preview = review_entries[:5]
            _emit_message(
                "[yellow]Needs-review directory samples:[/yellow]",
                mode="warning",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
            for entry in preview:
                _emit_message(
                    f"  - {entry}",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

        if quarantine_entries:
            preview = quarantine_entries[:5]
            _emit_message(
                "[yellow]Quarantine directory samples:[/yellow]",
                mode="warning",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
            for entry in preview:
                _emit_message(
                    f"  - {entry}",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

        if history_events:
            _emit_message(
                f"[green]Recent history ({len(history_events)} entries, newest first):[/green]",
                mode="detail",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
            for event in history_events:
                _emit_message(
                    f"  - {_format_history_event(event)}",
                    mode="detail",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
        elif history_error:
            _emit_message(
                f"[yellow]Unable to read history log: {history_error}[/yellow]",
                mode="warning",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )

        summary_metrics = {
            "files": counts["files"],
            "needs_review": counts["needs_review"],
            "tagged": counts["tagged"],
            "history": counts["history_entries"],
        }
        _emit_message(
            _format_summary_line("Status", root, summary_metrics),
            mode="summary",
            quiet=quiet_enabled,
            summary_only=summary_only,
        )
    except ConfigError as exc:
        _handle_cli_error(str(exc), code="config_error", json_output=json_enabled, original=exc)
    except click.ClickException as exc:
        _handle_cli_error(str(exc), code="cli_error", json_output=json_enabled, original=exc)
    except Exception as exc:
        _handle_cli_error(
            f"Unexpected error while reading status: {exc}",
            code="internal_error",
            json_output=json_enabled,
            details={"exception": type(exc).__name__},
            original=exc,
        )


@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=str))
@dry_run_option("Preview rollback without applying it.")
@json_option("Emit JSON describing the rollback plan.")
@summary_option()
@quiet_option()
@click.pass_context
def undo(
    ctx: click.Context,
    path: str,
    dry_run: bool,
    json_output: bool,
    summary_mode: bool,
    quiet: bool,
) -> None:
    """Rollback the last organization plan applied to PATH."""

    OperationExecutor = _load_dependency(
        "OperationExecutor", "dorgy.organization.executor", "OperationExecutor"
    )
    StateRepository = _load_dependency("StateRepository", "dorgy.state", "StateRepository")
    MissingStateError = _load_dependency("MissingStateError", "dorgy.state", "MissingStateError")
    StateError = _load_dependency("StateError", "dorgy.state", "StateError")

    json_enabled = json_output
    try:
        manager = ConfigManager()
        manager.ensure_exists()
        config = manager.load()

        mode: ModeResolution = resolve_mode_settings(
            ctx,
            config.cli,
            quiet_flag=quiet,
            summary_flag=summary_mode,
            json_flag=json_output,
        )
        quiet_enabled = mode.quiet
        summary_only = mode.summary
        json_enabled = mode.json_output

        root = Path(path).expanduser().resolve()
        repository = StateRepository()
        executor = OperationExecutor(staging_root=root / ".dorgy" / "staging")

        try:
            state = repository.load(root)
        except MissingStateError as exc:
            raise click.ClickException(
                f"No organization state found for {root}. Run `dorgy org {root}` before undo."
            ) from exc

        plan = executor._load_plan(root)  # type: ignore[attr-defined]
        rename_count = len(plan.renames) if plan else 0
        move_count = len(plan.moves) if plan else 0
        plan_payload = (
            {
                "renames": [op.model_dump(mode="json") for op in plan.renames],
                "moves": [op.model_dump(mode="json") for op in plan.moves],
            }
            if plan
            else None
        )

        snapshot_payload: dict[str, Any] | None = None
        snapshot_error = None
        try:
            snapshot_payload = repository.load_original_structure(root)
        except StateError as exc:
            snapshot_error = str(exc)

        history_error = None
        try:
            history_events = repository.read_history(root, limit=5)
        except StateError as exc:
            history_events = []
            history_error = str(exc)

        counts = {
            "renames": rename_count,
            "moves": move_count,
            "history": len(history_events),
        }

        error_summary: dict[str, str] = {}
        if snapshot_error:
            error_summary["snapshot"] = snapshot_error
        if history_error:
            error_summary["history"] = history_error
        if plan is None:
            error_summary["plan"] = "No plan available to roll back."

        json_payload: dict[str, Any] = {
            "context": {"root": str(root), "dry_run": dry_run},
            "plan": plan_payload,
            "snapshot": snapshot_payload,
            "history": [event.model_dump(mode="json") for event in history_events],
            "counts": counts,
        }
        if error_summary:
            json_payload["errors"] = error_summary

        if dry_run:
            if json_enabled:
                console.print_json(data=json_payload)
                return

            _emit_message(
                "[yellow]Dry run: organization rollback simulated.[/yellow]",
                mode="warning",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
            if plan is None:
                _emit_message(
                    "[yellow]No plan available to roll back.[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
            else:
                plan_summary = (
                    "[yellow]"
                    f"Plan contains {rename_count} rename(s) and {move_count} move(s)."
                    "[/yellow]"
                )
                _emit_message(
                    plan_summary,
                    mode="detail",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

            if snapshot_payload:
                entries = snapshot_payload.get("entries", [])
                snapshot_summary = (
                    "[yellow]"
                    f"Snapshot captured {len(entries)} original entries before organization."
                    "[/yellow]"
                )
                _emit_message(
                    snapshot_summary,
                    mode="detail",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
                preview = [entry.get("path", "?") for entry in entries[:5]]
                if preview:
                    _emit_message(
                        "[yellow]Sample paths:[/yellow]",
                        mode="detail",
                        quiet=quiet_enabled,
                        summary_only=summary_only,
                    )
                    for sample in preview:
                        _emit_message(
                            f"  - {sample}",
                            mode="detail",
                            quiet=quiet_enabled,
                            summary_only=summary_only,
                        )
            elif snapshot_error:
                _emit_message(
                    f"[yellow]Unable to load original snapshot: {snapshot_error}[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

            if history_events:
                history_summary = (
                    "[yellow]"
                    f"Recent history ({len(history_events)} entries, newest first):"
                    "[/yellow]"
                )
                _emit_message(
                    history_summary,
                    mode="detail",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
                for event in history_events:
                    notes = ", ".join(event.notes) if event.notes else ""
                    note_suffix = f" — {notes}" if notes else ""
                    _emit_message(
                        "  - "
                        f"[{event.timestamp.isoformat()}] {event.operation.upper()} "
                        f"{event.source} -> {event.destination}{note_suffix}",
                        mode="detail",
                        quiet=quiet_enabled,
                        summary_only=summary_only,
                    )
            elif history_error:
                _emit_message(
                    f"[yellow]Unable to read history log: {history_error}[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )

            summary_metrics = {
                "dry_run": True,
                "renames": counts["renames"],
                "moves": counts["moves"],
                "history": counts["history"],
            }
            _emit_message(
                _format_summary_line("Undo", root, summary_metrics),
                mode="summary",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
            return

        preserved_dirs: list[str] | None = None
        if snapshot_payload:
            raw_dirs = snapshot_payload.get("directories")
            if isinstance(raw_dirs, list):
                preserved_dirs = [entry for entry in raw_dirs if isinstance(entry, str)]

        try:
            executor.rollback(root, preserved_directories=preserved_dirs)
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc

        repository.save(root, state)
        if json_enabled:
            payload = dict(json_payload)
            payload["rolled_back"] = True
            console.print_json(data=payload)
            return

        _emit_message(
            f"[green]Rolled back last plan for {root}.[/green]",
            mode="detail",
            quiet=quiet_enabled,
            summary_only=summary_only,
        )
        if history_events:
            _emit_message(
                f"[green]Recent history ({len(history_events)} entries, newest first):[/green]",
                mode="detail",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
            for event in history_events:
                _emit_message(
                    f"  - {_format_history_event(event)}",
                    mode="detail",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
        elif history_error:
            _emit_message(
                f"[yellow]Unable to read history log: {history_error}[/yellow]",
                mode="warning",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )

        summary_metrics = {
            "renames": counts["renames"],
            "moves": counts["moves"],
            "history": counts["history"],
        }
        _emit_message(
            _format_summary_line("Undo", root, summary_metrics),
            mode="summary",
            quiet=quiet_enabled,
            summary_only=summary_only,
        )
    except ConfigError as exc:
        _handle_cli_error(str(exc), code="config_error", json_output=json_enabled, original=exc)
    except click.ClickException as exc:
        _handle_cli_error(str(exc), code="cli_error", json_output=json_enabled, original=exc)
    except Exception as exc:
        _handle_cli_error(
            f"Unexpected error while rolling back changes: {exc}",
            code="internal_error",
            json_output=json_enabled,
            details={"exception": type(exc).__name__},
            original=exc,
        )


def main() -> None:
    """Invoke the Click CLI as the console script entry point.

    Returns:
        None: This function is invoked for its side effects.
    """
    with shutdown_manager:
        try:
            cli()
        except ShutdownRequested:
            console.print("[yellow]Operation cancelled by user request.[/yellow]")
            sys.exit(130)
        except KeyboardInterrupt:
            console.print("[yellow]Operation cancelled by user request.[/yellow]")
            sys.exit(130)


if __name__ == "__main__":
    main()
