"""Output helpers for Dorgy CLI commands."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

import click

from dorgy.cli.context import console

if TYPE_CHECKING:
    from dorgy.watch import WatchBatchResult


def _collect_llm_metadata(settings: Any) -> dict[str, Any]:
    """Return sanitized LLM metadata including fallback state and summary text.

    Args:
        settings: LLM runtime settings exposed by the configuration layer.

    Returns:
        dict[str, Any]: Metadata payload suitable for CLI and JSON output.
    """

    metadata = settings.runtime_metadata()
    fallbacks_enabled = os.getenv("DORGY_USE_FALLBACKS") == "1"
    metadata["fallbacks_enabled"] = fallbacks_enabled
    fallback_text = "enabled" if fallbacks_enabled else "disabled"
    metadata["summary"] = f"{settings.runtime_summary()}, fallbacks={fallback_text}"
    return metadata


def _llm_summary(metadata: Mapping[str, Any]) -> str:
    """Render a human-readable LLM summary from serialized metadata.

    Args:
        metadata: Serialized metadata emitted by :func:`_collect_llm_metadata`.

    Returns:
        str: Summary string describing the configured LLM runtime.
    """

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
        message: Human-readable error description.
        code: Machine-readable error identifier.
        json_output: Indicates whether JSON output is active.
        details: Optional structured metadata for JSON payloads.
        original: Original exception to chain when appropriate.

    Raises:
        SystemExit: When emitting JSON output so the process exits with failure.
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
        mode: Output mode identifier (`detail`, `summary`, `warning`, `error`).
        quiet: Indicates whether quiet mode is active.
        summary_only: Indicates whether only summary lines should be shown.
    """

    if quiet and mode != "error":
        return

    important_modes = {"summary", "warning", "error"}
    if summary_only and mode not in important_modes:
        return

    console.print(message)


def _format_summary_line(command: str, root: Path | str, metrics: Mapping[str, Any]) -> str:
    """Return a consistent summary line for CLI commands.

    Args:
        command: Command name to include in the summary.
        root: Target root path relevant to the command.
        metrics: Mapping of metric names to values.

    Returns:
        str: Rich-formatted summary string.
    """

    formatted_root = str(root)
    parts = ", ".join(f"{key}={value}" for key, value in metrics.items())
    return f"[green]{command} summary for {formatted_root}: {parts}.[/green]"


def _emit_errors(
    errors: Mapping[str, list[str]],
    *,
    quiet: bool,
    summary_only: bool,
) -> None:
    """Emit structured error output honoring quiet/summary preferences.

    Args:
        errors: Mapping of error categories to message lists.
        quiet: Indicates whether quiet mode is active.
        summary_only: Indicates whether only summary lines should be shown.
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
    batch: "WatchBatchResult",
    *,
    json_output: bool,
    quiet: bool,
    summary_only: bool,
) -> None:
    """Render output for a processed watch batch.

    Args:
        batch: Result payload produced by the watch service.
        json_output: Indicates whether JSON mode is active.
        quiet: Indicates whether quiet mode is active.
        summary_only: Indicates whether only summary lines should be shown.
    """

    if json_output:
        console.print_json(data=batch.json_payload)
        return

    llm_summary_fn = _llm_summary
    emit_message_fn = _emit_message

    trigger_count = len(batch.triggered_paths)
    llm_context = batch.json_payload.get("context", {}).get("llm")  # type: ignore[arg-type]
    if llm_context and not summary_only:
        emit_message_fn(
            f"[cyan]LLM configuration: {llm_summary_fn(llm_context)}[/cyan]",
            mode="detail",
            quiet=quiet,
            summary_only=summary_only,
        )

    if trigger_count and not summary_only:
        emit_message_fn(
            f"[cyan]Watch batch {batch.json_payload['context']['batch_id']} "
            f"processed {trigger_count} triggered path(s).[/cyan]",
            mode="detail",
            quiet=quiet,
            summary_only=summary_only,
        )

    _emit_errors(batch.errors, quiet=quiet, summary_only=summary_only)

    if batch.notes:
        emit_message_fn(
            "[yellow]Plan notes:[/yellow]",
            mode="warning",
            quiet=quiet,
            summary_only=summary_only,
        )
        for note in batch.notes:
            emit_message_fn(
                f"  - {note}",
                mode="warning",
                quiet=quiet,
                summary_only=summary_only,
            )

    if batch.ingestion.needs_review:
        emit_message_fn(
            f"[yellow]{len(batch.ingestion.needs_review)} files require review based on the "
            "current confidence threshold.[/yellow]",
            mode="warning",
            quiet=quiet,
            summary_only=summary_only,
        )

    if batch.quarantine_paths:
        emit_message_fn(
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
            emit_message_fn(
                deleted_msg,
                mode="warning",
                quiet=quiet,
                summary_only=summary_only,
            )
        if removal_counts.get("moved_out"):
            emit_message_fn(
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

    emit_message_fn(
        _format_summary_line("Watch", batch.target_root, summary_metrics),
        mode="summary",
        quiet=quiet,
        summary_only=summary_only,
    )


def _not_implemented(command: str) -> None:
    """Emit a placeholder message for incomplete CLI commands.

    Args:
        command: Name of the command lacking an implementation.
    """

    console.print(
        f"[yellow]`{command}` is not implemented yet. "
        "Track progress in SPEC.md and notes/STATUS.md.[/yellow]"
    )


__all__ = [
    "_collect_llm_metadata",
    "_llm_summary",
    "_handle_cli_error",
    "_emit_message",
    "_format_summary_line",
    "_emit_errors",
    "_emit_watch_batch",
    "_not_implemented",
]
