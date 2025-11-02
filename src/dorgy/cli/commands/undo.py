"""Undo command implementation for the Dorgy CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import click

from dorgy.cli.context import console
from dorgy.cli.helpers.formatting import _format_history_event
from dorgy.cli.helpers.messages import _emit_message, _format_summary_line, _handle_cli_error
from dorgy.cli.lazy import _load_dependency
from dorgy.cli_options import (
    ModeResolution,
    dry_run_option,
    json_option,
    quiet_option,
    resolve_mode_settings,
    summary_option,
)
from dorgy.config import ConfigError, ConfigManager


@click.command()
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
    """Rollback the last organization plan applied to ``PATH``.

    Args:
        ctx: Click context tracking global mode flags.
        path: Collection root to roll back.
        dry_run: Indicates whether to preview without mutating files.
        json_output: Indicates whether JSON output mode is active.
        summary_mode: Indicates whether summary-only output is requested.
        quiet: Indicates whether quiet mode is requested.

    Raises:
        click.ClickException: When validation fails before performing the rollback.
    """

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


def register_undo_command(cli: click.Group) -> None:
    """Register the undo command with the top-level CLI group.

    Args:
        cli: Root Click command group.
    """

    cli.add_command(undo)


__all__ = ["register_undo_command", "undo"]
