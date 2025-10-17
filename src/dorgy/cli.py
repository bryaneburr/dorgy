"""Command line interface for the Dorgy project."""

from __future__ import annotations

import difflib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click
import yaml
from click.core import ParameterSource
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from dorgy.classification import ClassificationCache
from dorgy.cli_support import (
    build_original_snapshot,
    collect_error_payload,
    compute_org_counts,
    descriptor_to_record,
    relative_to_collection,
    run_classification,
    zip_decisions,
)
from dorgy.config import ConfigError, ConfigManager, DorgyConfig, resolve_with_precedence
from dorgy.ingestion import IngestionPipeline
from dorgy.ingestion.detectors import HashComputer, TypeDetector
from dorgy.ingestion.discovery import DirectoryScanner
from dorgy.ingestion.extractors import MetadataExtractor
from dorgy.organization.executor import OperationExecutor
from dorgy.organization.planner import OrganizerPlanner
from dorgy.state import (
    CollectionState,
    MissingStateError,
    OperationEvent,
    StateError,
    StateRepository,
)
from dorgy.watch import WatchBatchResult, WatchService

console = Console()


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


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="dorgy")
def cli() -> None:
    """Dorgy automatically organizes your files using AI-assisted workflows.

    Returns:
        None: This function is invoked for its side effects.
    """


@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=str))
@click.option("-r", "--recursive", is_flag=True, help="Include all subdirectories.")
@click.option("--prompt", type=str, help="Provide extra instructions for organization.")
@click.option(
    "--output",
    type=click.Path(file_okay=False, path_type=str),
    help="Directory for organized files.",
)
@click.option("--dry-run", is_flag=True, help="Preview changes without modifying files.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON describing proposed changes.")
@click.option("--summary", "summary_mode", is_flag=True, help="Only emit summary lines.")
@click.option("--quiet", is_flag=True, help="Suppress non-error output.")
@click.pass_context
def org(
    ctx: click.Context,
    path: str,
    recursive: bool,
    prompt: str | None,
    output: str | None,
    dry_run: bool,
    json_output: bool,
    summary_mode: bool,
    quiet: bool,
) -> None:
    """Organize files rooted at PATH using the configured ingestion pipeline.

    Args:
        ctx: Click context used for parameter source inspection.
        path: Root directory to organize.
        recursive: Whether to include subdirectories during scanning.
        prompt: Additional natural-language guidance for the workflow.
        output: Destination directory for organized files.
        dry_run: If True, skip making filesystem mutations.
        json_output: If True, emit JSON describing planned or applied changes.
        summary_mode: When True, limit output to summary lines and warnings.
        quiet: When True, suppress non-error CLI output entirely.

    Raises:
        click.ClickException: If configuration loading or validation fails.
    """

    json_enabled = json_output
    try:
        manager = ConfigManager()
        manager.ensure_exists()
        config = manager.load()

        explicit_quiet = ctx.get_parameter_source("quiet") == ParameterSource.COMMANDLINE
        explicit_summary = ctx.get_parameter_source("summary_mode") == ParameterSource.COMMANDLINE

        quiet_enabled = quiet if explicit_quiet else config.cli.quiet_default
        summary_only = summary_mode if explicit_summary else config.cli.summary_default

        if json_output:
            if explicit_quiet and quiet_enabled:
                raise click.ClickException("--json cannot be combined with --quiet.")
            if explicit_summary and summary_only:
                raise click.ClickException("--json cannot be combined with --summary.")
            quiet_enabled = False
            summary_only = False

        if quiet_enabled and summary_only:
            raise click.ClickException(
                "Quiet and summary modes cannot both be enabled. Adjust CLI defaults or flags."
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

        scanner = DirectoryScanner(
            recursive=recursive,
            include_hidden=include_hidden,
            follow_symlinks=follow_symlinks,
            max_size_bytes=max_size_bytes,
        )
        state_dir = target_root / ".dorgy"
        staging_dir = None if dry_run else state_dir / "staging"
        classification_cache = ClassificationCache(state_dir / "classifications.json")

        pipeline = IngestionPipeline(
            scanner=scanner,
            detector=TypeDetector(),
            hasher=HashComputer(),
            extractor=MetadataExtractor(),
            processing=config.processing,
            staging_dir=staging_dir,
            allow_writes=not dry_run,
        )

        result = pipeline.run([source_root])
        classification_batch = run_classification(
            result.processed,
            prompt,
            source_root,
            dry_run,
            config,
            classification_cache,
        )

        paired = list(zip_decisions(classification_batch, result.processed))
        confidence_threshold = config.ambiguity.confidence_threshold
        for decision, descriptor in paired:
            if decision is not None and decision.confidence < confidence_threshold:
                decision.needs_review = True
                if descriptor.path not in result.needs_review:
                    result.needs_review.append(descriptor.path)

        planner = OrganizerPlanner()
        plan = planner.build_plan(
            descriptors=[descriptor for _, descriptor in paired],
            decisions=[decision for decision, _ in paired],
            rename_enabled=config.organization.rename_files,
            root=target_root,
            conflict_strategy=config.organization.conflict_resolution,
        )
        rename_map = {operation.source: operation.destination for operation in plan.renames}
        move_map = {operation.source: operation.destination for operation in plan.moves}

        final_path_map: dict[Path, Path] = {}
        file_entries: list[dict[str, Any]] = []
        table_rows: list[tuple[str, str, str, str, str]] = []

        for decision, descriptor in paired:
            original_path = descriptor.path
            rename_target = rename_map.get(original_path)
            move_key = rename_target if rename_target is not None else original_path
            move_target = move_map.get(move_key)
            final_path = move_target or rename_target or original_path
            final_path_map[original_path] = final_path

            file_entries.append(
                {
                    "original_path": original_path.as_posix(),
                    "final_path": final_path.as_posix(),
                    "descriptor": descriptor.model_dump(mode="json"),
                    "classification": decision.model_dump(mode="json")
                    if decision is not None
                    else None,
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
            table_rows.append(
                (
                    str(relative_path),
                    descriptor.mime_type,
                    str(metadata.get("size_bytes", "?")),
                    category,
                    (descriptor.preview or "")[:120],
                )
            )

        counts = compute_org_counts(result, classification_batch, plan)
        json_payload: dict[str, Any] = {
            "context": {
                "source_root": source_root.as_posix(),
                "destination_root": target_root.as_posix(),
                "copy_mode": copy_mode,
                "dry_run": dry_run,
                "prompt": prompt,
            },
            "counts": counts,
            "plan": plan.model_dump(mode="json"),
            "files": file_entries,
            "notes": list(plan.notes),
        }
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
            table.add_column("Category")
            table.add_column("Preview", overflow="fold")
            for row in table_rows:
                table.add_row(*row)
            _emit_message(table, mode="detail", quiet=quiet_enabled, summary_only=summary_only)

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

        repository = StateRepository()
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
            state = CollectionState(root=str(target_root))

        snapshot: dict[str, Any] | None = None
        if not dry_run:
            snapshot = build_original_snapshot(
                [descriptor for _, descriptor in paired], source_root
            )

        executor = OperationExecutor(
            staging_root=state_dir / "staging",
            copy_mode=copy_mode,
            source_root=source_root,
        )
        events: list[OperationEvent] = []
        try:
            if snapshot is not None:
                repository.write_original_structure(target_root, snapshot)
            events = executor.apply(plan, target_root)
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
    except ConfigError as exc:
        _handle_cli_error(str(exc), code="config_error", json_output=json_enabled, original=exc)
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
@click.option("-r", "--recursive", is_flag=True, help="Include subdirectories for monitoring.")
@click.option("--prompt", type=str, help="Provide extra classification guidance.")
@click.option(
    "--output",
    type=click.Path(file_okay=False, path_type=str),
    help="Destination root when copying organized files.",
)
@click.option("--dry-run", is_flag=True, help="Preview actions without mutating files.")
@click.option("--debounce", type=float, help="Override debounce interval in seconds.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON describing watch batches.")
@click.option("--summary", "summary_mode", is_flag=True, help="Only emit summary lines.")
@click.option("--quiet", is_flag=True, help="Suppress non-error output.")
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
    prompt: str | None,
    output: str | None,
    dry_run: bool,
    debounce: float | None,
    json_output: bool,
    summary_mode: bool,
    quiet: bool,
    allow_deletions: bool,
    once: bool,
) -> None:
    """Continuously monitor PATHS and organize changes as they arrive.

    Args:
        ctx: Click context for parameter source inspection.
        paths: One or more directory roots to monitor.
        recursive: Whether to include subdirectories while watching.
        prompt: Optional natural-language guidance for classification.
        output: Optional destination for copy-mode organization.
        dry_run: When True, skip filesystem mutations.
        debounce: Optional debounce override in seconds.
        json_output: When True, emit JSON payloads instead of text.
        summary_mode: When True, restrict output to summary/warning lines.
        quiet: When True, suppress non-error output entirely.
        allow_deletions: When True, permit removal of state entries when files are deleted
            or leave the watched roots.
        once: When True, process current contents once and exit.

    Raises:
        click.ClickException: If option combinations are invalid.
    """

    if not paths:
        raise click.ClickException("Provide at least one PATH to monitor.")

    try:
        manager = ConfigManager()
        manager.ensure_exists()
        config = manager.load()
    except ConfigError as exc:
        _handle_cli_error(str(exc), code="config_error", json_output=json_output)
        return

    explicit_quiet = ctx.get_parameter_source("quiet") == ParameterSource.COMMANDLINE
    explicit_summary = ctx.get_parameter_source("summary_mode") == ParameterSource.COMMANDLINE

    quiet_enabled = quiet if explicit_quiet else config.cli.quiet_default
    summary_only = summary_mode if explicit_summary else config.cli.summary_default

    if json_output:
        if quiet_enabled and explicit_quiet:
            raise click.ClickException("--json cannot be combined with --quiet.")
        if summary_only and explicit_summary:
            raise click.ClickException("--json cannot be combined with --summary.")

    if quiet_enabled and summary_only:
        raise click.ClickException(
            "Quiet and summary modes cannot both be enabled. Adjust CLI defaults or flags."
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
            prompt=prompt,
            output=output_path,
            dry_run=dry_run,
            recursive=recursive_enabled,
            debounce_override=debounce,
            allow_deletions=allow_deletions_enabled,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc

    if once:
        batches = service.process_once()
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
    except KeyboardInterrupt:
        service.stop()
        if not json_output:
            _emit_message(
                "[yellow]Watch stopped by user request.[/yellow]",
                mode="summary",
                quiet=quiet_enabled,
                summary_only=summary_only,
            )
    except RuntimeError as exc:
        _handle_cli_error(
            str(exc), code="watch_runtime_error", json_output=json_output, original=exc
        )


@cli.group()
def config() -> None:
    """Manage Dorgy configuration files and overrides.

    Returns:
        None: This function is invoked for its side effects.
    """


@config.command("view")
@click.option("--no-env", is_flag=True, help="Ignore environment overrides when displaying output.")
def config_view(no_env: bool) -> None:
    """Display the effective configuration after applying precedence rules.

    Args:
        no_env: If True, ignore environment-derived overrides.

    Raises:
        click.ClickException: If configuration cannot be loaded.
    """
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
    """Persist a configuration value expressed as a dotted KEY.

    Args:
        key: Dotted path describing the configuration field to update.
        value: YAML-literal value to write into the configuration file.

    Raises:
        click.ClickException: If parsing, assignment, or validation fails.
    """
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
    """Open the configuration file in an interactive editor session.

    Raises:
        click.ClickException: If edited content is invalid or cannot be saved.
    """
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
@click.option("--search", "query", type=str, help="Free-text search query.")
@click.option("--tags", type=str, help="Comma-separated tag filters.")
@click.option("--before", type=str, help="Return results created before this date.")
def search(**_: object) -> None:
    """Search within an organized collection.

    Args:
        _: Placeholder for Click-injected keyword arguments.

    Returns:
        None: This function is invoked for its side effects.
    """
    _not_implemented("dorgy search")


@cli.command()
@click.argument("source", type=click.Path(exists=True, path_type=str))
@click.argument("destination", type=click.Path(path_type=str))
def mv(**_: object) -> None:
    """Move a file or directory within an organized collection.

    Args:
        _: Placeholder for Click-injected keyword arguments.

    Returns:
        None: This function is invoked for its side effects.
    """
    _not_implemented("dorgy mv")


@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=str))
@click.option("--json", "json_output", is_flag=True, help="Emit status information as JSON.")
@click.option(
    "--history",
    "history_limit",
    type=int,
    default=None,
    show_default=False,
    help="Number of recent history entries to include (defaults to configuration).",
)
@click.option("--summary", "summary_mode", is_flag=True, help="Only emit summary lines.")
@click.option("--quiet", is_flag=True, help="Suppress non-error output.")
@click.pass_context
def status(
    ctx: click.Context,
    path: str,
    json_output: bool,
    history_limit: int | None,
    summary_mode: bool,
    quiet: bool,
) -> None:
    """Display a summary of the collection state for PATH.

    Args:
        ctx: Click context for parameter source inspection.
        path: Root directory whose state should be inspected.
        json_output: When True, emit JSON instead of textual output.
        history_limit: Optional override for how many history entries to include.
        summary_mode: When True, restrict output to summary lines and warnings.
        quiet: When True, suppress non-error output entirely.

    Raises:
        click.ClickException: If state cannot be loaded or arguments conflict.
    """

    json_enabled = json_output
    try:
        manager = ConfigManager()
        manager.ensure_exists()
        config = manager.load()

        explicit_quiet = ctx.get_parameter_source("quiet") == ParameterSource.COMMANDLINE
        explicit_summary = ctx.get_parameter_source("summary_mode") == ParameterSource.COMMANDLINE
        explicit_history = ctx.get_parameter_source("history_limit") == ParameterSource.COMMANDLINE

        quiet_enabled = quiet if explicit_quiet else config.cli.quiet_default
        summary_only = summary_mode if explicit_summary else config.cli.summary_default
        effective_history = (
            history_limit
            if explicit_history and history_limit is not None
            else config.cli.status_history_limit
        )

        if json_output:
            if explicit_quiet and quiet_enabled:
                raise click.ClickException("--json cannot be combined with --quiet.")
            if explicit_summary and summary_only:
                raise click.ClickException("--json cannot be combined with --summary.")
            quiet_enabled = False
            summary_only = False

        if quiet_enabled and summary_only:
            raise click.ClickException(
                "Quiet and summary modes cannot both be enabled. Adjust CLI defaults or flags."
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

        if json_output:
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
@click.option("--dry-run", is_flag=True, help="Preview rollback without applying it.")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON describing the rollback plan.")
@click.option("--summary", "summary_mode", is_flag=True, help="Only emit summary lines.")
@click.option("--quiet", is_flag=True, help="Suppress non-error output.")
@click.pass_context
def undo(
    ctx: click.Context,
    path: str,
    dry_run: bool,
    json_output: bool,
    summary_mode: bool,
    quiet: bool,
) -> None:
    """Rollback the last organization plan applied to PATH.

    Args:
        ctx: Click context for parameter inspection.
        path: Root directory to roll back.
        dry_run: If True, only preview the rollback operations.
        json_output: When True, emit JSON instead of textual output.
        summary_mode: When True, limit output to summary lines and warnings.
        quiet: When True, suppress non-error output entirely.

    Raises:
        click.ClickException: If state is missing or rollback fails.
    """

    json_enabled = json_output
    try:
        manager = ConfigManager()
        manager.ensure_exists()
        config = manager.load()

        explicit_quiet = ctx.get_parameter_source("quiet") == ParameterSource.COMMANDLINE
        explicit_summary = ctx.get_parameter_source("summary_mode") == ParameterSource.COMMANDLINE

        quiet_enabled = quiet if explicit_quiet else config.cli.quiet_default
        summary_only = summary_mode if explicit_summary else config.cli.summary_default

        if json_output:
            if explicit_quiet and quiet_enabled:
                raise click.ClickException("--json cannot be combined with --quiet.")
            if explicit_summary and summary_only:
                raise click.ClickException("--json cannot be combined with --summary.")
            quiet_enabled = False
            summary_only = False

        if quiet_enabled and summary_only:
            raise click.ClickException(
                "Quiet and summary modes cannot both be enabled. Adjust CLI defaults or flags."
            )

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
            if json_output:
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

        try:
            executor.rollback(root)
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc

        repository.save(root, state)
        if json_output:
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
    cli()


if __name__ == "__main__":
    main()
