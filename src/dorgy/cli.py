"""Command line interface for the Dorgy project."""

from __future__ import annotations

import difflib
from datetime import datetime
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from dorgy.config import ConfigError, ConfigManager, DorgyConfig, resolve_with_precedence
from dorgy.ingestion import FileDescriptor, IngestionPipeline
from dorgy.ingestion.detectors import HashComputer, TypeDetector
from dorgy.ingestion.discovery import DirectoryScanner
from dorgy.ingestion.extractors import MetadataExtractor
from dorgy.state import CollectionState, FileRecord, MissingStateError, StateRepository

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


def _descriptor_to_record(descriptor: FileDescriptor, root: Path) -> FileRecord:
    """Convert an ingestion descriptor into a state record."""

    try:
        relative = descriptor.path.relative_to(root)
    except ValueError:
        relative = descriptor.path

    categories_value = descriptor.metadata.get("categories")
    if isinstance(categories_value, str):
        categories = [categories_value]
    elif isinstance(categories_value, list):
        categories = [str(item) for item in categories_value]
    else:
        categories = descriptor.tags

    last_modified = None
    modified_raw = descriptor.metadata.get("modified_at")
    if modified_raw:
        try:
            last_modified = datetime.fromisoformat(modified_raw)
        except ValueError:
            last_modified = None

    return FileRecord(
        path=str(relative),
        hash=descriptor.hash,
        tags=descriptor.tags,
        categories=categories,
        confidence=None,
        last_modified=last_modified,
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
def org(
    path: str,
    recursive: bool,
    prompt: str | None,
    output: str | None,
    dry_run: bool,
    json_output: bool,
) -> None:
    """Organize files within PATH."""
    manager = ConfigManager()
    try:
        manager.ensure_exists()
        config = manager.load()
    except ConfigError as exc:
        raise click.ClickException(str(exc)) from exc

    root = Path(path).expanduser().resolve()
    recursive = recursive or config.processing.recurse_directories
    include_hidden = config.processing.process_hidden_files
    follow_symlinks = config.processing.follow_symlinks
    max_size_bytes = None
    if config.processing.max_file_size_mb > 0:
        max_size_bytes = config.processing.max_file_size_mb * 1024 * 1024

    scanner = DirectoryScanner(
        recursive=recursive,
        include_hidden=include_hidden,
        follow_symlinks=follow_symlinks,
        max_size_bytes=max_size_bytes,
    )
    pipeline = IngestionPipeline(
        scanner=scanner,
        detector=TypeDetector(),
        hasher=HashComputer(),
        extractor=MetadataExtractor(),
    )

    result = pipeline.run([root])

    if json_output:
        console.print_json(
            data=[descriptor.model_dump(mode="python") for descriptor in result.processed]
        )
    else:
        table = Table(title=f"Ingestion preview for {root}")
        table.add_column("File", overflow="fold")
        table.add_column("Type")
        table.add_column("Size", justify="right")
        table.add_column("Tags")
        table.add_column("Preview", overflow="fold")
        for descriptor in result.processed:
            metadata = descriptor.metadata
            try:
                relative_path = descriptor.path.relative_to(root)
            except ValueError:
                relative_path = descriptor.path
            table.add_row(
                str(relative_path),
                descriptor.mime_type,
                metadata.get("size_bytes", "?"),
                ", ".join(descriptor.tags) or "-",
                (descriptor.preview or "")[:120],
            )
        console.print(table)
        console.print(
            f"[green]Processed {len(result.processed)} files; "
            f"{len(result.needs_review)} flagged, {len(result.errors)} errors.[/green]"
        )
        if prompt:
            console.print(
                "[yellow]Prompt support arrives with the Phase 3 classification workflow.[/yellow]"
            )
        if output:
            console.print(
                "[yellow]Output path support is coming soon; files stay in place for now.[/yellow]"
            )
        if result.errors:
            console.print("[red]Errors:[/red]")
            for error in result.errors:
                console.print(f"  - {error}")

    if dry_run:
        console.print("[yellow]Dry run selected; skipping state persistence.[/yellow]")
        return

    repository = StateRepository()
    try:
        state = repository.load(root)
    except MissingStateError:
        state = CollectionState(root=str(root))

    for descriptor in result.processed:
        record = _descriptor_to_record(descriptor, root)
        state.files[record.path] = record

    repository.save(root, state)
    console.print(f"[green]Persisted state for {len(result.processed)} files.[/green]")


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
