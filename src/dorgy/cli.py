"""Command line interface for the Dorgy project."""

from __future__ import annotations

import difflib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

import click
import yaml
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from dorgy.classification import (
    ClassificationBatch,
    ClassificationCache,
    ClassificationDecision,
    ClassificationEngine,
    ClassificationRequest,
)
from dorgy.config import ConfigError, ConfigManager, DorgyConfig, resolve_with_precedence
from dorgy.ingestion import FileDescriptor, IngestionPipeline
from dorgy.ingestion.detectors import HashComputer, TypeDetector
from dorgy.ingestion.discovery import DirectoryScanner
from dorgy.ingestion.extractors import MetadataExtractor
from dorgy.organization.executor import OperationExecutor
from dorgy.organization.planner import OrganizerPlanner
from dorgy.state import (
    CollectionState,
    FileRecord,
    MissingStateError,
    OperationEvent,
    StateError,
    StateRepository,
)

console = Console()


def _not_implemented(command: str) -> None:
    """Emit a placeholder message for incomplete CLI commands.

    Args:
        command: Name of the command to mention in the status message.
    """
    console.print(
        f"[yellow]`{command}` is not implemented yet. "
        "Track progress in SPEC.md and notes/STATUS.md.[/yellow]"
    )


def _assign_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    """Assign a nested value within a dictionary for a dotted path.

    Args:
        target: Mapping to mutate in-place.
        path: Sequence of keys representing the nested location.
        value: Value to assign at the nested location.

    Raises:
        ConfigError: If a non-mapping value is encountered along the path.
    """

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


def _descriptor_to_record(
    descriptor: FileDescriptor,
    decision: Optional[ClassificationDecision],
    root: Path,
) -> FileRecord:
    """Convert ingestion and classification data into a state record.

    Args:
        descriptor: Descriptor produced by the ingestion pipeline.
        decision: Classification decision associated with the descriptor, if any.
        root: Root directory for the collection.

    Returns:
        FileRecord: The state record ready to be saved.
    """

    try:
        relative = descriptor.path.relative_to(root)
    except ValueError:
        relative = descriptor.path

    last_modified = None
    modified_raw = descriptor.metadata.get("modified_at")
    if modified_raw:
        try:
            normalized = (
                modified_raw.replace("Z", "+00:00") if modified_raw.endswith("Z") else modified_raw
            )
            last_modified = datetime.fromisoformat(normalized)
        except ValueError:
            last_modified = None

    categories: list[str] = []
    tags: list[str] = descriptor.tags
    confidence: Optional[float] = None
    rename_suggestion: Optional[str] = None
    reasoning: Optional[str] = None

    needs_review = False

    if decision is not None:
        categories = [decision.primary_category]
        categories.extend(decision.secondary_categories)
        tags = decision.tags or categories
        confidence = decision.confidence
        rename_suggestion = decision.rename_suggestion
        reasoning = decision.reasoning
        needs_review = decision.needs_review

    return FileRecord(
        path=str(relative),
        hash=descriptor.hash,
        tags=tags,
        categories=categories,
        confidence=confidence,
        last_modified=last_modified,
        rename_suggestion=rename_suggestion,
        reasoning=reasoning,
        needs_review=needs_review,
    )


def _run_classification(
    descriptors: Iterable[FileDescriptor],
    prompt: Optional[str],
    root: Path,
    dry_run: bool,
    config: DorgyConfig,
    cache: Optional[ClassificationCache],
) -> ClassificationBatch:
    """Run the classification engine with graceful degradation.

    Args:
        descriptors: Descriptors to classify.
        prompt: Optional prompt supplied by the user.
        root: Collection root path.
        dry_run: Indicates whether we are in dry-run mode.
        config: Loaded configuration object.
        cache: Optional cache for reusing classification results.

    Returns:
        ClassificationBatch: Decisions and errors from the classification step.
    """

    descriptors = list(descriptors)
    if not descriptors:
        return ClassificationBatch()

    if cache is not None:
        cache.load()

    decisions: list[Optional[ClassificationDecision]] = [None] * len(descriptors)
    errors: list[str] = []
    missing_requests: list[ClassificationRequest] = []
    missing_indices: list[int] = []
    missing_keys: list[Optional[str]] = []

    for index, descriptor in enumerate(descriptors):
        key = _decision_key(descriptor, root)
        cached = cache.get(key) if cache is not None and key is not None else None
        if cached is not None:
            decisions[index] = cached
        else:
            missing_indices.append(index)
            missing_keys.append(key)
            missing_requests.append(
                ClassificationRequest(
                    descriptor=descriptor,
                    prompt=prompt,
                    collection_root=root,
                )
            )

    if missing_requests:
        engine = ClassificationEngine()
        batch = engine.classify(missing_requests)
        errors.extend(batch.errors)
        for idx, decision, key in zip(missing_indices, batch.decisions, missing_keys, strict=False):
            if decision is not None:
                decisions[idx] = decision
                if not dry_run and cache is not None and key is not None:
                    cache.set(key, decision)

    if cache is not None and not dry_run:
        cache.save()

    return ClassificationBatch(decisions=decisions, errors=errors)


def _zip_decisions(
    batch: ClassificationBatch,
    descriptors: Iterable[FileDescriptor],
) -> Iterable[tuple[Optional[ClassificationDecision], FileDescriptor]]:
    """Zip decisions with descriptors, filling missing entries with ``None``.

    Args:
        batch: Result batch returned by the classification engine.
        descriptors: Original descriptors from ingestion.

    Yields:
        Tuples of (decision or ``None``, descriptor).
    """

    decisions = list(batch.decisions)
    descriptors = list(descriptors)
    for index, descriptor in enumerate(descriptors):
        decision = decisions[index] if index < len(decisions) else None
        yield decision, descriptor


def _relative_to_collection(path: Path, root: Path) -> str:
    """Return the relative path of ``path`` to ``root`` if possible."""

    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _build_original_snapshot(
    descriptors: Iterable[FileDescriptor],
    root: Path,
) -> dict[str, Any]:
    """Create a snapshot describing the pre-organization file structure.

    Args:
        descriptors: File descriptors produced before any moves/renames.
        root: Collection root path used to compute relative paths.

    Returns:
        dict[str, Any]: Snapshot payload ready to persist via the state repository.
    """

    generated_at = datetime.now(timezone.utc).isoformat()
    entries: list[dict[str, Any]] = []
    for descriptor in descriptors:
        entries.append(
            {
                "path": _relative_to_collection(descriptor.path, root),
                "display_name": descriptor.display_name,
                "mime_type": descriptor.mime_type,
                "hash": descriptor.hash,
                "size_bytes": descriptor.metadata.get("size_bytes"),
                "tags": list(descriptor.tags),
            }
        )

    return {"generated_at": generated_at, "entries": entries}


def _decision_key(descriptor: FileDescriptor, root: Path) -> Optional[str]:
    """Compute a stable cache key for a descriptor."""

    if descriptor.hash:
        return descriptor.hash
    return _relative_to_collection(descriptor.path, root)


def _apply_rename(path: Path, suggestion: str) -> Path:
    """Rename ``path`` to match ``suggestion`` while avoiding collisions."""

    suffix = path.suffix
    sanitized = suggestion.strip()
    if not sanitized:
        return path

    base_candidate = sanitized
    candidate = path.with_name(f"{base_candidate}{suffix}")
    counter = 1
    while candidate.exists() and candidate != path:
        candidate = path.with_name(f"{base_candidate}-{counter}{suffix}")
        counter += 1

    if candidate == path:
        return path

    path.rename(candidate)
    return candidate


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(package_name="dorgy")
def cli() -> None:
    """Dorgy automatically organizes your files using AI-assisted workflows.

    Returns:
        None: This function is invoked for its side effects.
    """


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
    """Organize files rooted at PATH using the configured ingestion pipeline.

    Args:
        path: Root directory to organize.
        recursive: Whether to include subdirectories during scanning.
        prompt: Additional natural-language guidance for the workflow.
        output: Destination directory for organized files (future feature).
        dry_run: If True, skip making filesystem mutations.
        json_output: If True, emit JSON describing proposed changes.

    Raises:
        click.ClickException: If configuration loading or validation fails.
    """
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
    state_dir = Path(path).expanduser().resolve() / ".dorgy"
    staging_dir = None if dry_run else state_dir / "staging"
    classification_cache = ClassificationCache(state_dir / "classifications.json")

    pipeline = IngestionPipeline(
        scanner=scanner,
        detector=TypeDetector(),
        hasher=HashComputer(),
        extractor=MetadataExtractor(),
        processing=config.processing,
        staging_dir=staging_dir,
        allow_writes=not dry_run,
    )

    result = pipeline.run([root])
    classification_batch = _run_classification(
        result.processed,
        prompt,
        root,
        dry_run,
        config,
        classification_cache,
    )

    paired = list(_zip_decisions(classification_batch, result.processed))
    confidence_threshold = config.ambiguity.confidence_threshold
    for decision, descriptor in paired:
        if decision is not None and decision.confidence < confidence_threshold:
            decision.needs_review = True
            if descriptor.path not in result.needs_review:
                result.needs_review.append(descriptor.path)

    planner = OrganizerPlanner()
    plan = planner.build_plan(
        descriptors=[descriptor for _, descriptor in paired],
        decisions=[decision for decision, _ in paired],
        rename_enabled=config.organization.rename_files,
        root=root,
        conflict_strategy=config.organization.conflict_resolution,
    )
    rename_map = {operation.source: operation.destination for operation in plan.renames}
    move_map = {operation.source: operation.destination for operation in plan.moves}

    if json_output:
        payload = []
        for decision, descriptor in paired:
            rename_target = rename_map.get(descriptor.path)
            move_key = rename_target if rename_target is not None else descriptor.path
            move_target = move_map.get(move_key)
            payload.append(
                {
                    "descriptor": descriptor.model_dump(mode="python"),
                    "classification": decision.model_dump(mode="python")
                    if decision is not None
                    else None,
                    "operations": {
                        "rename": rename_target.as_posix() if rename_target is not None else None,
                        "move": move_target.as_posix() if move_target is not None else None,
                    },
                }
            )
        console.print_json(data=payload)
    else:
        table = Table(title=f"Organization preview for {root}")
        table.add_column("File", overflow="fold")
        table.add_column("Type")
        table.add_column("Size", justify="right")
        table.add_column("Category")
        table.add_column("Preview", overflow="fold")
        for decision, descriptor in paired:
            metadata = descriptor.metadata
            try:
                relative_path = descriptor.path.relative_to(root)
            except ValueError:
                relative_path = descriptor.path
            category = decision.primary_category if decision else "-"
            table.add_row(
                str(relative_path),
                descriptor.mime_type,
                metadata.get("size_bytes", "?"),
                category,
                (descriptor.preview or "")[:120],
            )
        console.print(table)
        console.print(
            f"[green]Processed {len(result.processed)} files; "
            f"{len(result.needs_review)} flagged, {len(result.errors)} errors.[/green]"
        )
        if result.quarantined:
            console.print(
                f"[yellow]{len(result.quarantined)} files marked for quarantine.[/yellow]"
            )
        if classification_batch.decisions:
            review_count = sum(
                1
                for decision in classification_batch.decisions
                if decision is not None and decision.needs_review
            )
            console.print(
                f"[green]Classification completed ({len(classification_batch.decisions)} files, "
                f"{review_count} marked for review).[/green]"
            )
        if plan.renames:
            console.print(f"[cyan]{len(plan.renames)} rename operations planned/applied.[/cyan]")
        if plan.moves:
            console.print(f"[cyan]{len(plan.moves)} move operations planned/applied.[/cyan]")
        if prompt:
            console.print(
                "[yellow]Prompt support arrives with the Phase 3 classification workflow.[/yellow]"
            )
        if output:
            console.print(
                "[yellow]Output path support is coming soon; files stay in place for now.[/yellow]"
            )
        if plan.notes:
            console.print("[yellow]Plan notes:[/yellow]")
            for note in plan.notes:
                console.print(f"  - {note}")
        combined_errors = [*result.errors, *classification_batch.errors]
        if combined_errors:
            console.print("[red]Errors:[/red]")
            for error in combined_errors:
                console.print(f"  - {error}")

    if dry_run:
        console.print("[yellow]Dry run selected; skipping state persistence.[/yellow]")
        return

    repository = StateRepository()
    state_dir = repository.initialize(root)
    quarantine_dir = state_dir / "quarantine"
    if result.quarantined and config.processing.corrupted_files.action == "quarantine":
        moved_paths: list[Path] = []
        for original in result.quarantined:
            target = quarantine_dir / original.name
            counter = 1
            while target.exists():
                target = target.with_name(f"{original.stem}-{counter}{original.suffix}")
                counter += 1
            try:
                shutil.move(str(original), str(target))
            except Exception as exc:  # pragma: no cover - filesystem issues
                console.print(f"[red]Failed to quarantine {original}: {exc}[/red]")
                result.errors.append(f"{original}: quarantine failed ({exc})")
            else:
                moved_paths.append(target)
        result.quarantined = moved_paths
        if moved_paths:
            console.print(f"[yellow]Moved {len(moved_paths)} files to quarantine.[/yellow]")
    try:
        state = repository.load(root)
    except MissingStateError:
        state = CollectionState(root=str(root))

    snapshot: dict[str, Any] | None = None
    if not dry_run:
        snapshot = _build_original_snapshot([descriptor for _, descriptor in paired], root)

    executor = OperationExecutor(staging_root=state_dir / "staging")
    events: list[OperationEvent] = []
    if not dry_run:
        try:
            if snapshot is not None:
                repository.write_original_structure(root, snapshot)
            events = executor.apply(plan, root)
        except Exception as exc:
            raise click.ClickException(f"Failed to apply organization plan: {exc}") from exc

    for decision, descriptor in paired:
        original_path = descriptor.path

        rename_target = rename_map.get(original_path)
        if rename_target is not None:
            descriptor.path = rename_target
            descriptor.display_name = descriptor.path.name

        move_target = move_map.get(descriptor.path)
        if move_target is not None:
            descriptor.path = move_target
            descriptor.display_name = descriptor.path.name

        record = _descriptor_to_record(descriptor, decision, root)
        old_relative = _relative_to_collection(original_path, root)

        state.files.pop(old_relative, None)
        state.files[record.path] = record

    repository.save(root, state)
    if events:
        repository.append_history(root, events)
    console.print(f"[green]Persisted state for {len(result.processed)} files.[/green]")

    log_path = state_dir / "dorgy.log"
    try:
        with log_path.open("a", encoding="utf-8") as log_file:
            timestamp = datetime.now(timezone.utc).isoformat()
            log_file.write(
                f"[{timestamp}] processed={len(result.processed)} "
                f"needs_review={len(result.needs_review)} "
                f"quarantined={len(result.quarantined)} "
                f"classification={len(classification_batch.decisions)} "
                f"classification_errors={len(classification_batch.errors)} "
                f"renames={len(plan.renames)} moves={len(plan.moves)} "
                f"errors={len(result.errors)}\n"
            )
            for error in result.errors:
                log_file.write(f"  error: {error}\n")
            for error in classification_batch.errors:
                log_file.write(f"  classification_error: {error}\n")
            for q_path in result.quarantined:
                log_file.write(f"  quarantined: {q_path}\n")
            for rename_op in plan.renames:
                log_file.write(f"  rename: {rename_op.source} -> {rename_op.destination}\n")
            for move_op in plan.moves:
                log_file.write(f"  move: {move_op.source} -> {move_op.destination}\n")
    except OSError as exc:  # pragma: no cover - logging best effort
        console.print(f"[yellow]Unable to update log file: {exc}[/yellow]")


@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=str))
@click.option("-r", "--recursive", is_flag=True, help="Watch subdirectories too.")
@click.option(
    "--output",
    type=click.Path(file_okay=False, path_type=str),
    help="Directory for organized files.",
)
def watch(**_: object) -> None:
    """Continuously organize new files within PATH.

    Args:
        _: Placeholder for Click-injected keyword arguments.

    Returns:
        None: This function is invoked for its side effects.
    """
    _not_implemented("dorgy watch")


@cli.group()
def config() -> None:
    """Manage Dorgy configuration files and overrides.

    Returns:
        None: This function is invoked for its side effects.
    """


@config.command("view")
@click.option("--no-env", is_flag=True, help="Ignore environment overrides when displaying output.")
def config_view(no_env: bool) -> None:
    """Display the effective configuration after applying precedence rules.

    Args:
        no_env: If True, ignore environment-derived overrides.

    Raises:
        click.ClickException: If configuration cannot be loaded.
    """
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
    """Persist a configuration value expressed as a dotted KEY.

    Args:
        key: Dotted path describing the configuration field to update.
        value: YAML-literal value to write into the configuration file.

    Raises:
        click.ClickException: If parsing, assignment, or validation fails.
    """
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
    """Open the configuration file in an interactive editor session.

    Raises:
        click.ClickException: If edited content is invalid or cannot be saved.
    """
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
    """Search within an organized collection.

    Args:
        _: Placeholder for Click-injected keyword arguments.

    Returns:
        None: This function is invoked for its side effects.
    """
    _not_implemented("dorgy search")


@cli.command()
@click.argument("source", type=click.Path(exists=True, path_type=str))
@click.argument("destination", type=click.Path(path_type=str))
def mv(**_: object) -> None:
    """Move a file or directory within an organized collection.

    Args:
        _: Placeholder for Click-injected keyword arguments.

    Returns:
        None: This function is invoked for its side effects.
    """
    _not_implemented("dorgy mv")


@cli.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False, path_type=str))
@click.option("--dry-run", is_flag=True, help="Preview rollback without applying it.")
def undo(path: str, dry_run: bool) -> None:
    """Rollback the last organization plan applied to PATH."""

    root = Path(path).expanduser().resolve()
    repository = StateRepository()
    executor = OperationExecutor(staging_root=root / ".dorgy" / "staging")

    try:
        state = repository.load(root)
    except MissingStateError as exc:
        raise click.ClickException(f"No organization state found for {root}: {exc}") from exc

    if dry_run:
        console.print("[yellow]Dry run: organization rollback simulated.[/yellow]")
        plan = executor._load_plan(root)  # type: ignore[attr-defined]
        if plan is None:
            console.print("[yellow]No plan available to roll back.[/yellow]")
        else:
            console.print(
                "[yellow]Plan contains "
                f"{len(plan.renames)} renames and {len(plan.moves)} moves.[/yellow]"
            )
        try:
            snapshot = repository.load_original_structure(root)
        except StateError as exc:
            console.print(f"[yellow]Unable to load original snapshot: {exc}[/yellow]")
        else:
            if snapshot:
                entries = snapshot.get("entries", [])
                console.print(
                    f"[yellow]Snapshot captured {len(entries)} original entries before organization.[/yellow]"
                )
                preview = [entry.get("path", "?") for entry in entries[:5]]
                if preview:
                    console.print("[yellow]Sample paths:[/yellow]")
                    for sample in preview:
                        console.print(f"  - {sample}")
        return

    try:
        executor.rollback(root)
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    repository.save(root, state)
    console.print(f"[green]Rolled back last plan for {root}.[/green]")


def main() -> None:
    """Invoke the Click CLI as the console script entry point.

    Returns:
        None: This function is invoked for its side effects.
    """
    cli()


if __name__ == "__main__":
    main()
