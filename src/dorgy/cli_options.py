"""Reusable Click option factories and validation helpers for Dorgy CLI commands.

This module centralizes common Click option patterns (quiet/summary/json, dry-run,
output paths) and provides helpers for reconciling command-line flags with
configuration defaults. Commands can import these decorators to avoid repeating
option declarations and rely on :func:`resolve_mode_settings` to validate
mutually exclusive combinations while honouring configuration fallbacks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, TypeVar

import click
from click.core import ParameterSource

from dorgy.config.models import CLIOptions

Callback = TypeVar("Callback", bound=Callable[..., Any])


def json_option(help_text: str | None = None) -> Callable[[Callback], Callback]:
    """Return a Click option decorator enabling `--json` toggles.

    Args:
        help_text: Optional override for the help description.

    Returns:
        Callable[[Callback], Callback]: Decorator applying the option.
    """

    description = help_text or "Emit command output as JSON."
    return click.option("--json", "json_output", is_flag=True, help=description)


def summary_option(help_text: str | None = None) -> Callable[[Callback], Callback]:
    """Return a Click option decorator enabling `--summary` toggles.

    Args:
        help_text: Optional help text override.

    Returns:
        Callable[[Callback], Callback]: Decorator applying the option.
    """

    description = help_text or "Only emit summary lines."
    return click.option("--summary", "summary_mode", is_flag=True, help=description)


def quiet_option(help_text: str | None = None) -> Callable[[Callback], Callback]:
    """Return a Click option decorator enabling `--quiet` toggles.

    Args:
        help_text: Optional help text override.

    Returns:
        Callable[[Callback], Callback]: Decorator applying the option.
    """

    description = help_text or "Suppress non-error output."
    return click.option("--quiet", is_flag=True, help=description)


def dry_run_option(help_text: str | None = None) -> Callable[[Callback], Callback]:
    """Return a Click option decorator enabling `--dry-run` toggles.

    Args:
        help_text: Optional help text override.

    Returns:
        Callable[[Callback], Callback]: Decorator applying the option.
    """

    description = help_text or "Preview the command without modifying files."
    return click.option("--dry-run", is_flag=True, help=description)


def output_option(help_text: str | None = None) -> Callable[[Callback], Callback]:
    """Return an option decorator for output directory overrides.

    Args:
        help_text: Optional help text override.

    Returns:
        Callable[[Callback], Callback]: Decorator applying the option.
    """

    description = help_text or "Directory for organized files."
    return click.option(
        "--output",
        type=click.Path(file_okay=False, path_type=str),
        help=description,
    )


def classify_prompt_option(help_text: str | None = None) -> Callable[[Callback], Callback]:
    """Return a Click option decorator for classification prompt overrides.

    Args:
        help_text: Optional help text override.

    Returns:
        Callable[[Callback], Callback]: Decorator applying the option.
    """

    description = help_text or "Provide extra classification guidance."
    return click.option("--classify-prompt", type=str, help=description)


def classify_prompt_file_option(
    help_text: str | None = None,
) -> Callable[[Callback], Callback]:
    """Return a Click option decorator for classification prompt files.

    Args:
        help_text: Optional help text override.

    Returns:
        Callable[[Callback], Callback]: Decorator applying the option.
    """

    description = help_text or "Read classification guidance from a text file."
    return click.option(
        "--classify-prompt-file",
        type=click.Path(exists=True, dir_okay=False, readable=True, path_type=str),
        help=description,
    )


def structure_prompt_option(help_text: str | None = None) -> Callable[[Callback], Callback]:
    """Return a Click option decorator for structure planning prompts.

    Args:
        help_text: Optional help text override.

    Returns:
        Callable[[Callback], Callback]: Decorator applying the option.
    """

    description = help_text or "Provide extra instructions for structure planning."
    return click.option("--structure-prompt", type=str, help=description)


def structure_prompt_file_option(
    help_text: str | None = None,
) -> Callable[[Callback], Callback]:
    """Return a Click option decorator for structure prompt files.

    Args:
        help_text: Optional help text override.

    Returns:
        Callable[[Callback], Callback]: Decorator applying the option.
    """

    description = help_text or "Read structure planning instructions from a text file."
    return click.option(
        "--structure-prompt-file",
        type=click.Path(exists=True, dir_okay=False, readable=True, path_type=str),
        help=description,
    )


def recursive_option(help_text: str | None = None) -> Callable[[Callback], Callback]:
    """Return a Click option decorator for recursive behavior toggles.

    Args:
        help_text: Optional help text override.

    Returns:
        Callable[[Callback], Callback]: Decorator applying the option.
    """

    description = help_text or "Include subdirectories during processing."
    return click.option("-r", "--recursive", is_flag=True, help=description)


@dataclass(frozen=True, slots=True)
class ModeResolution:
    """Resolved CLI presentation settings derived from flags and defaults.

    Attributes:
        quiet: Whether quiet mode should be active for the command.
        summary: Whether summary-only mode should be active.
        json_output: Whether JSON output is enabled.
        explicit_quiet: Indicates if quiet mode was explicitly requested.
        explicit_summary: Indicates if summary mode was explicitly requested.
        explicit_json: Indicates if JSON mode was explicitly requested.
    """

    quiet: bool
    summary: bool
    json_output: bool
    explicit_quiet: bool
    explicit_summary: bool
    explicit_json: bool


def resolve_mode_settings(
    ctx: click.Context,
    cli_defaults: CLIOptions,
    *,
    quiet_flag: bool,
    summary_flag: bool,
    json_flag: bool,
    quiet_param: str = "quiet",
    summary_param: str = "summary_mode",
    json_param: str = "json_output",
) -> ModeResolution:
    """Resolve presentation mode flags using configuration defaults."""

    explicit_quiet = ctx.get_parameter_source(quiet_param) == ParameterSource.COMMANDLINE
    explicit_summary = ctx.get_parameter_source(summary_param) == ParameterSource.COMMANDLINE
    explicit_json = ctx.get_parameter_source(json_param) == ParameterSource.COMMANDLINE

    quiet_enabled = quiet_flag if explicit_quiet else cli_defaults.quiet_default
    summary_only = summary_flag if explicit_summary else cli_defaults.summary_default
    json_output = json_flag

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

    return ModeResolution(
        quiet=quiet_enabled,
        summary=summary_only,
        json_output=json_output,
        explicit_quiet=explicit_quiet,
        explicit_summary=explicit_summary,
        explicit_json=explicit_json,
    )


__all__ = [
    "ModeResolution",
    "classify_prompt_file_option",
    "classify_prompt_option",
    "dry_run_option",
    "json_option",
    "output_option",
    "quiet_option",
    "recursive_option",
    "resolve_mode_settings",
    "structure_prompt_file_option",
    "structure_prompt_option",
    "summary_option",
]
