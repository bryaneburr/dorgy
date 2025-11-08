"""Status command implementation for the Dorgy CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click
from click.core import ParameterSource
from rich.table import Table

from dorgy.cli.context import console
from dorgy.cli.helpers.formatting import _format_history_event
from dorgy.cli.helpers.messages import _emit_message, _format_summary_line, _handle_cli_error
from dorgy.cli.helpers.options import (
    ModeResolution,
    json_option,
    quiet_option,
    resolve_mode_settings,
    summary_option,
)
from dorgy.cli.lazy import _load_dependency
from dorgy.config import ConfigError, ensure_config, load_config

if TYPE_CHECKING:
    from dorgy.state import OperationEvent


@click.command()
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
    """Display a summary of the collection state for ``PATH``.

    Args:
        ctx: Click context tracking global mode flags.
        path: Collection root to summarize.
        json_output: Indicates whether JSON output mode is active.
        history_limit: Maximum number of history events to display.
        summary_mode: Indicates whether summary-only output is requested.
        quiet: Indicates whether quiet mode is requested.

    Raises:
        click.ClickException: When validation fails before reading the state.
    """

    StateRepository = _load_dependency("StateRepository", "dorgy.state", "StateRepository")
    MissingStateError = _load_dependency("MissingStateError", "dorgy.state", "MissingStateError")
    StateError = _load_dependency("StateError", "dorgy.state", "StateError")

    json_enabled = json_output
    try:
        ensure_config()
        config = load_config()

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


def register_status_command(cli: click.Group) -> None:
    """Register the status command with the top-level CLI group.

    Args:
        cli: Root Click command group.
    """

    cli.add_command(status)


__all__ = ["register_status_command", "status"]
