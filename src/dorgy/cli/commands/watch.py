"""Watch command implementation for the Dorgy CLI."""

from __future__ import annotations

from pathlib import Path

import click
from click.core import ParameterSource

from dorgy.cli.context import console
from dorgy.cli.helpers.messages import _emit_message, _emit_watch_batch, _handle_cli_error
from dorgy.cli.helpers.progress import _ProgressScope
from dorgy.cli.helpers.search import _load_embedding_function
from dorgy.cli.lazy import _load_dependency
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
from dorgy.config import ConfigError, ConfigManager
from dorgy.shutdown import ShutdownRequested


@click.command()
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
@click.option(
    "--with-search",
    is_flag=True,
    help="Build or update the local search index after each watch batch.",
)
@click.option(
    "--without-search",
    is_flag=True,
    help="Skip search indexing for this run, overriding config and prior state.",
)
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
    with_search: bool,
    without_search: bool,
) -> None:
    """Continuously monitor ``PATHS`` and organize changes as they arrive.

    Args:
        ctx: Click context tracking global mode flags.
        paths: Collection roots to monitor.
        recursive: Whether to traverse subdirectories while watching.
        classify_prompt: Inline classification guidance provided via CLI.
        classify_prompt_file: Path to a file containing classification guidance.
        structure_prompt: Inline structure guidance provided via CLI.
        structure_prompt_file: Path to a structure guidance file.
        output: Optional destination root used when copying organized files.
        dry_run: Indicates whether to preview changes without mutating files.
        debounce: Optional debounce interval override in seconds.
        json_output: Indicates whether JSON output mode is active.
        summary_mode: Indicates whether summary-only output is requested.
        quiet: Indicates whether quiet mode is requested.
        allow_deletions: Whether deletions are permitted for watch batches.
        once: Runs a single batch when True instead of streaming.
        with_search: Forces search indexing after each batch.
        without_search: Skips search indexing regardless of configuration.

    Raises:
        click.ClickException: When validation fails before launching the watch.
    """

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
    if with_search and without_search:
        raise click.ClickException("--with-search cannot be combined with --without-search.")

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
    embedding_function = None
    if config.search.embedding_function:
        embedding_function = _load_embedding_function(config.search.embedding_function)

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
            with_search=with_search,
            without_search=without_search,
            embedding_function=embedding_function,
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


def register_watch_command(cli: click.Group) -> None:
    """Register the watch command with the top-level CLI group.

    Args:
        cli: Root Click command group.
    """

    cli.add_command(watch)


__all__ = ["register_watch_command", "watch"]
