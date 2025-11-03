"""CLI application assembly for the Dorgy command suite."""

from __future__ import annotations

import sys

import click

from dorgy.cli.context import console
from dorgy.shutdown import ShutdownRequested, shutdown_manager

from .commands.config import register_config_group
from .commands.mv import register_mv_command
from .commands.org import register_org_command
from .commands.search import register_search_command
from .commands.status import register_status_command
from .commands.undo import register_undo_command
from .commands.watch import register_watch_command


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="dorgy")
def cli() -> None:
    """Dorgy automatically organizes your files using AI-assisted workflows."""


# Register commands when the module is imported so Click sees them once.
register_org_command(cli)
register_watch_command(cli)
register_config_group(cli)
register_search_command(cli)
register_mv_command(cli)
register_status_command(cli)
register_undo_command(cli)


def main() -> None:
    """Execute the CLI entry point and manage shutdown semantics.

    Returns:
        None: The function exits the process on completion.
    """

    with shutdown_manager:
        try:
            cli()
        except ShutdownRequested:
            console.print("[yellow]Operation cancelled by user request.[/yellow]")
            sys.exit(130)
        except KeyboardInterrupt:
            console.print("[yellow]Operation cancelled by user request.[/yellow]")
            sys.exit(130)


__all__ = ["cli", "main"]
