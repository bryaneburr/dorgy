"""Version command implementation for the Dorgy CLI."""

from __future__ import annotations

import platform
import tomllib
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Any

import click

from dorgy.cli.context import console
from dorgy.cli.helpers.messages import _emit_message, _handle_cli_error
from dorgy.cli.helpers.options import (
    ModeResolution,
    json_option,
    quiet_option,
    resolve_mode_settings,
    summary_option,
)
from dorgy.config import DEFAULT_CONFIG_PATH, ConfigError, DorgyConfig, load_config


@dataclass(frozen=True, slots=True)
class VersionInfo:
    """Structured representation of version metadata."""

    version: str
    source: str
    location: str | None


def _find_pyproject(start: Path) -> Path | None:
    """Return the nearest ``pyproject.toml`` path when present.

    Args:
        start: Path used as the starting point for traversal.

    Returns:
        Path | None: Discovered ``pyproject.toml`` path or ``None`` when absent.
    """

    for candidate in [start, *start.parents]:
        pyproject_path = candidate / "pyproject.toml"
        if pyproject_path.exists():
            return pyproject_path
    return None


def _read_pyproject_version(pyproject: Path) -> str:
    """Read the project version from a ``pyproject.toml`` file.

    Args:
        pyproject: Path to a TOML project file.

    Returns:
        str: Version string declared under the ``project.version`` key.

    Raises:
        ValueError: If the version cannot be located.
        tomllib.TOMLDecodeError: When the file contains invalid TOML.
    """

    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    project = data.get("project", {})
    version = project.get("version")
    if not isinstance(version, str):
        raise ValueError("Version not found in pyproject.toml.")
    return version


def _collect_version_info() -> VersionInfo:
    """Resolve Dorgy version metadata from installed distributions or sources.

    Returns:
        VersionInfo: Structured version details including the resolution source.

    Raises:
        metadata.PackageNotFoundError: When the package metadata is unavailable
            and no ``pyproject.toml`` fallback exists.
        ValueError: When a ``pyproject.toml`` is present but missing a version.
    """

    try:
        dist = metadata.distribution("dorgy")
        location = dist.locate_file(".")
        return VersionInfo(
            version=dist.version,
            source="package_metadata",
            location=str(Path(str(location)).resolve()),
        )
    except metadata.PackageNotFoundError:
        pass

    pyproject = _find_pyproject(Path(__file__).resolve())
    if pyproject is None:
        raise metadata.PackageNotFoundError("Dorgy package metadata not found.")

    version = _read_pyproject_version(pyproject)
    return VersionInfo(version=version, source="pyproject", location=str(pyproject.parent))


@click.command()
@json_option("Emit version information as JSON.")
@summary_option("Only emit the version summary line.")
@quiet_option("Suppress non-error output.")
@click.pass_context
def version(
    ctx: click.Context,
    json_output: bool,
    summary_mode: bool,
    quiet: bool,
) -> None:
    """Display the installed Dorgy version and environment details.

    Args:
        ctx: Click context carrying CLI mode flags.
        json_output: Indicates whether JSON output is requested.
        summary_mode: Indicates whether summary-only output is requested.
        quiet: Indicates whether quiet mode is requested.
    """

    json_enabled = json_output
    cli_defaults = DorgyConfig().cli
    config_error: str | None = None

    config_path = DEFAULT_CONFIG_PATH.expanduser()
    if config_path.exists():
        try:
            cli_defaults = load_config().cli
        except ConfigError as exc:
            config_error = str(exc)

    try:
        mode: ModeResolution = resolve_mode_settings(
            ctx,
            cli_defaults,
            quiet_flag=quiet,
            summary_flag=summary_mode,
            json_flag=json_output,
        )
    except click.ClickException as exc:
        _handle_cli_error(str(exc), code="cli_error", json_output=json_enabled, original=exc)
        return

    quiet_enabled = mode.quiet
    summary_only = mode.summary
    json_enabled = mode.json_output

    try:
        version_info = _collect_version_info()
    except (metadata.PackageNotFoundError, ValueError, tomllib.TOMLDecodeError) as exc:
        _handle_cli_error(
            "Unable to determine Dorgy version.",
            code="version_unavailable",
            json_output=json_enabled,
            original=exc,
        )
        return

    details: dict[str, Any] = {
        "version": version_info.version,
        "python_version": platform.python_version(),
        "source": version_info.source,
    }
    if version_info.location:
        details["location"] = version_info.location
    if config_error:
        details["notes"] = {"config_error": config_error}

    if json_enabled:
        console.print_json(data=details)
        return

    emit = _emit_message
    emit(
        f"Dorgy version {version_info.version}",
        mode="detail",
        quiet=quiet_enabled,
        summary_only=summary_only,
    )
    emit(
        f"Python {details['python_version']}",
        mode="detail",
        quiet=quiet_enabled,
        summary_only=summary_only,
    )
    if version_info.location:
        emit(
            f"Install location: {version_info.location}",
            mode="detail",
            quiet=quiet_enabled,
            summary_only=summary_only,
        )
    if version_info.source == "pyproject":
        emit(
            "Version resolved from pyproject metadata (package metadata unavailable).",
            mode="warning",
            quiet=quiet_enabled,
            summary_only=summary_only,
        )
    if config_error:
        emit(
            f"Config load error: {config_error}",
            mode="warning",
            quiet=quiet_enabled,
            summary_only=summary_only,
        )
    emit(
        f"Dorgy version summary: {version_info.version} (Python {details['python_version']}).",
        mode="summary",
        quiet=quiet_enabled,
        summary_only=summary_only,
    )


def register_version_command(cli: click.Group) -> None:
    """Register the version command with the top-level CLI group.

    Args:
        cli: Root Click command group.
    """

    cli.add_command(version)


__all__ = ["register_version_command", "version"]
