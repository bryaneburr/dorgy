"""State management helpers shared by Dorgy CLI commands."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

import click

from dorgy.cli.lazy import _load_dependency

if TYPE_CHECKING:
    from dorgy.state import CollectionState, FileRecord


def _normalise_state_key(value: str) -> str:
    """Return a normalized representation for state paths using forward slashes.

    Args:
        value: Original path string.

    Returns:
        str: Normalized path using forward slashes.
    """

    return value.replace("\\", "/")


def _detect_collection_root(path: Path) -> Path:
    """Return the collection root that owns the given path.

    Args:
        path: Absolute path within a managed collection.

    Returns:
        Path: Collection root containing the Dorgy state directory.

    Raises:
        MissingStateError: If no containing collection can be found.
    """

    MissingStateError = _load_dependency("MissingStateError", "dorgy.state", "MissingStateError")

    candidate = path if path.is_dir() else path.parent
    for current in [candidate, *candidate.parents]:
        state_path = current / ".dorgy" / "state.json"
        if state_path.exists():
            return current
    raise MissingStateError(f"No collection state found for {path}.")


def _resolve_move_destination(
    source: Path,
    candidate: Path,
    strategy: str,
) -> tuple[Path | None, bool, str | None, bool]:
    """Resolve naming conflicts for a move/rename destination.

    Args:
        source: Source filesystem path.
        candidate: Desired destination path.
        strategy: Conflict resolution strategy name.

    Returns:
        tuple[Path | None, bool, str | None, bool]: Resolved destination, conflict flag,
            optional note, and skip indicator.
    """

    normalized = (strategy or "append_number").lower()
    if normalized not in {"append_number", "timestamp", "skip"}:
        normalized = "append_number"

    if candidate.resolve() == source.resolve():
        return candidate, False, None, False

    conflict_applied = False
    base_candidate = candidate
    final_candidate = candidate
    counter = 1
    timestamp_applied = False

    while final_candidate.exists():
        conflict_applied = True
        if normalized == "skip":
            note = (
                f"Skipped move for {source} because {final_candidate} already exists "
                "and the conflict strategy is 'skip'."
            )
            return None, True, note, True
        if normalized == "timestamp" and not timestamp_applied:
            timestamp_applied = True
            timestamp_value = datetime.now(timezone.utc)
            suffix = timestamp_value.strftime("%Y%m%d-%H%M%S")
            base_candidate = candidate.with_name(f"{candidate.stem}-{suffix}{candidate.suffix}")
            final_candidate = base_candidate
            continue
        final_candidate = base_candidate.with_name(
            f"{base_candidate.stem}-{counter}{base_candidate.suffix}"
        )
        counter += 1

    note_text: str | None = None
    if conflict_applied:
        note_text = f"Resolved conflict for {source} -> {final_candidate} using '{normalized}'."
    return final_candidate, conflict_applied, note_text, False


def _plan_state_changes(
    state: "CollectionState",
    root: Path,
    source: Path,
    destination: Path,
) -> list[tuple[str, str]]:
    """Compute state path updates required for a move/rename operation.

    Args:
        state: Loaded collection state model.
        root: Collection root path.
        source: Original filesystem path.
        destination: Target filesystem path.

    Returns:
        list[tuple[str, str]]: Sequence of (old_key, new_key) mappings.

    Raises:
        click.ClickException: If the source path is not tracked.
    """

    relative_to_collection = _load_dependency(
        "relative_to_collection",
        "dorgy.cli_support",
        "relative_to_collection",
    )

    source_rel = _normalise_state_key(relative_to_collection(source, root))
    dest_rel = _normalise_state_key(relative_to_collection(destination, root))
    mappings: list[tuple[str, str]] = []

    if source.is_dir():
        prefix = source_rel.rstrip("/")
        for key in list(state.files.keys()):
            normalised_key = _normalise_state_key(key)
            if normalised_key == prefix or normalised_key.startswith(f"{prefix}/"):
                suffix = normalised_key[len(prefix) :].lstrip("/")
                new_key = dest_rel if not suffix else f"{dest_rel}/{suffix}"
                mappings.append((key, new_key))
        if not mappings:
            raise click.ClickException(
                f"No tracked files found under {source_rel}. Run `dorgy org` to refresh state."
            )
        return mappings

    matched_key: str | None = None
    for key in state.files.keys():
        if _normalise_state_key(key) == source_rel:
            matched_key = key
            break
    if matched_key is None:
        raise click.ClickException(
            f"{source_rel} is not tracked in the collection state. "
            "Run `dorgy org` to refresh metadata before moving files."
        )

    mappings.append((matched_key, dest_rel))
    return mappings


def _apply_state_changes(
    state: "CollectionState",
    changes: Iterable[tuple[str, str]],
) -> None:
    """Apply planned state path updates to the in-memory state model.

    Args:
        state: State model to mutate.
        changes: Iterable of (old_key, new_key) mappings.
    """

    staged: list[tuple[str, "FileRecord"]] = []
    for old_key, new_key in changes:
        record = state.files.pop(old_key, None)
        if record is None:
            continue
        staged.append((new_key, record))
    for new_key, record in staged:
        record.path = new_key
        state.files[new_key] = record


__all__ = [
    "_apply_state_changes",
    "_detect_collection_root",
    "_normalise_state_key",
    "_plan_state_changes",
    "_resolve_move_destination",
]
