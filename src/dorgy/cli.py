"""Command line interface for the Dorgy project."""

from __future__ import annotations

import difflib
from typing import Any

import click
import yaml
from rich.console import Console
from rich.syntax import Syntax

from dorgy.config import ConfigError, ConfigManager, DorgyConfig, resolve_with_precedence

console = Console()


def _not_implemented(command: str) -> None:
    """Emit a standard placeholder message until the command is wired up."""
    console.print(
        f"[yellow]`{command}` is not implemented yet. "
        "Track progress in SPEC.md and notes/STATUS.md.[/yellow]"
    )


def _assign_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    """Assign a nested value within a dictionary given a dotted path."""

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


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="dorgy")
def cli() -> None:
    """Dorgy automatically organizes your files using AI-assisted workflows."""


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
def org(**_: object) -> None:
    """Organize files within PATH."""
    _not_implemented("dorgy org")


@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=str))
@click.option("-r", "--recursive", is_flag=True, help="Watch subdirectories too.")
@click.option(
    "--output",
    type=click.Path(file_okay=False, path_type=str),
    help="Directory for organized files.",
)
def watch(**_: object) -> None:
    """Continuously organize new files within PATH."""
    _not_implemented("dorgy watch")


@cli.group()
def config() -> None:
    """Manage Dorgy configuration."""


@config.command("view")
@click.option("--no-env", is_flag=True, help="Ignore environment overrides when displaying output.")
def config_view(no_env: bool) -> None:
    """Display effective configuration."""
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
    """Persist a configuration value."""
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
    """Open configuration for interactive editing."""
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
    """Search within an organized collection."""
    _not_implemented("dorgy search")


@cli.command()
@click.argument("source", type=click.Path(exists=True, path_type=str))
@click.argument("destination", type=click.Path(path_type=str))
def mv(**_: object) -> None:
    """Move a file or directory within an organized collection."""
    _not_implemented("dorgy mv")


@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=str))
def undo(**_: object) -> None:
    """Restore a collection to its original structure."""
    _not_implemented("dorgy undo")


def main() -> None:
    """Entry point used by console scripts."""
    cli()


if __name__ == "__main__":
    main()
