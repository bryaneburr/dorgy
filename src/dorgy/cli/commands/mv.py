"""Move command implementation for the Dorgy CLI."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

import click

from dorgy.cli.context import console
from dorgy.cli.helpers.messages import _emit_message, _format_summary_line, _handle_cli_error
from dorgy.cli.helpers.search import _load_embedding_function
from dorgy.cli.helpers.state import (
    _apply_state_changes,
    _detect_collection_root,
    _normalise_state_key,
    _plan_state_changes,
    _resolve_move_destination,
)
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

if TYPE_CHECKING:
    from dorgy.state import OperationEvent


@click.command()
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
    """Move or rename tracked files within an organized collection.

    Args:
        ctx: Click context tracking global mode flags.
        source: Source path to move.
        destination: Destination path for the move.
        conflict_strategy: Conflict resolution strategy name.
        dry_run: Indicates whether to preview without mutating files.
        json_output: Indicates whether JSON output mode is active.
        summary_mode: Indicates whether summary-only output is requested.
        quiet: Indicates whether quiet mode is requested.

    Raises:
        click.ClickException: When validation fails before executing the move.
    """

    from dorgy.cli_support import relative_to_collection

    OperationExecutor = _load_dependency(
        "OperationExecutor", "dorgy.organization.executor", "OperationExecutor"
    )
    OperationPlan = _load_dependency("OperationPlan", "dorgy.organization.models", "OperationPlan")
    MoveOperation = _load_dependency("MoveOperation", "dorgy.organization.models", "MoveOperation")
    StateRepository = _load_dependency("StateRepository", "dorgy.state", "StateRepository")
    MissingStateError = _load_dependency("MissingStateError", "dorgy.state", "MissingStateError")
    SearchIndexError = _load_dependency("SearchIndexError", "dorgy.search", "SearchIndexError")
    ensure_search_index = _load_dependency("ensure_index", "dorgy.search.lifecycle", "ensure_index")
    refresh_search_metadata = _load_dependency(
        "refresh_metadata", "dorgy.search.lifecycle", "refresh_metadata"
    )

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
        search_notes: list[str] = []
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
                if state.search is None:
                    from dorgy.state.models import SearchState

                    state.search = SearchState()
                if state.search.enabled:
                    try:
                        search_index = ensure_search_index(
                            root,
                            state,
                            embedding_function=_load_embedding_function(
                                config.search.embedding_function
                            ),
                        )
                        records_to_refresh: list[tuple[Any, Mapping[str, Any] | None]] = []
                        for _, new_key in changes:
                            record = state.files.get(new_key)
                            if record is None:
                                continue
                            records_to_refresh.append((record, {"source": "mv"}))
                        refresh_search_metadata(search_index, state, records_to_refresh)
                        if records_to_refresh and not json_output:
                            _emit_message(
                                (
                                    "[cyan]Updated search metadata for "
                                    f"{len(records_to_refresh)} file(s).[/cyan]"
                                ),
                                mode="detail",
                                quiet=quiet_enabled,
                                summary_only=summary_only,
                            )
                    except SearchIndexError as exc:
                        state.search.enabled = False
                        search_notes.append(f"Search indexing skipped: {exc}")
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
        combined_notes = list(plan.notes)
        combined_notes.extend(search_notes)
        if combined_notes:
            json_payload["notes"] = combined_notes
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

            if combined_notes:
                _emit_message(
                    "[yellow]Notes:[/yellow]",
                    mode="warning",
                    quiet=quiet_enabled,
                    summary_only=summary_only,
                )
                for entry in combined_notes:
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


def register_mv_command(cli: click.Group) -> None:
    """Register the move command with the top-level CLI group.

    Args:
        cli: Root Click command group.
    """

    cli.add_command(mv)


__all__ = ["mv", "register_mv_command"]
