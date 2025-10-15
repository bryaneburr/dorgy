"""Command line interface for the Dorgy project."""

from __future__ import annotations

import click
from rich.console import Console

console = Console()


def _not_implemented(command: str) -> None:
    """Emit a standard placeholder message until the command is wired up."""
    console.print(
        f"[yellow]`{command}` is not implemented yet. "
        "Track progress in SPEC.md and notes/STATUS.md.[/yellow]"
    )


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
def config_view() -> None:
    """Display effective configuration."""
    _not_implemented("dorgy config view")


@config.command("set")
@click.argument("key")
@click.option("--value", required=True, help="Value to assign to KEY.")
def config_set(**_: object) -> None:
    """Persist a configuration value."""
    _not_implemented("dorgy config set")


@config.command("edit")
def config_edit() -> None:
    """Open configuration for interactive editing."""
    _not_implemented("dorgy config edit")


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
