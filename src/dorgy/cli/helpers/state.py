"""State management helpers shared by Dorgy CLI commands."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Optional

import click

from dorgy.cli.lazy import _load_dependency

if TYPE_CHECKING:
    from dorgy.ingestion import FileDescriptor
    from dorgy.state import CollectionState, FileRecord


def relative_to_collection(path: Path, root: Path) -> str:
    """Return ``path`` relative to ``root`` when possible."""

    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def build_original_snapshot(
    descriptors: Iterable["FileDescriptor"],
    root: Path,
) -> dict[str, Any]:
    """Create a snapshot of pre-organization descriptors."""

    generated_at = datetime.now(timezone.utc).isoformat()
    entries: list[dict[str, Any]] = []
    directories: set[str] = set()
    root_resolved = root.resolve()
    for descriptor in descriptors:
        entries.append(
            {
                "path": relative_to_collection(descriptor.path, root),
                "display_name": descriptor.display_name,
                "mime_type": descriptor.mime_type,
                "hash": descriptor.hash,
                "size_bytes": descriptor.metadata.get("size_bytes"),
                "tags": list(descriptor.tags),
            }
        )

        current = descriptor.path.resolve().parent
        while True:
            try:
                relative_dir = current.relative_to(root_resolved)
            except ValueError:
                break
            if not relative_dir.parts:
                break
            directories.add(relative_dir.as_posix())
            if current == root_resolved:
                break
            current = current.parent

    return {
        "generated_at": generated_at,
        "entries": entries,
        "directories": sorted(directories),
    }


def descriptor_to_record(
    descriptor: "FileDescriptor",
    decision: Optional[Any],
    root: Path,
) -> "FileRecord":
    """Convert a descriptor and decision into a state record."""

    FileRecord = _load_dependency("FileRecord", "dorgy.state", "FileRecord")

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
    vision_caption = descriptor.metadata.get("vision_caption")
    raw_labels = descriptor.metadata.get("vision_labels")
    if isinstance(raw_labels, list):
        vision_labels = [str(label).strip() for label in raw_labels if str(label).strip()]
    elif isinstance(raw_labels, str):
        vision_labels = [part.strip() for part in raw_labels.split(",") if part.strip()]
    else:
        vision_labels = []

    raw_confidence = descriptor.metadata.get("vision_confidence")
    vision_confidence: Optional[float] = None
    if isinstance(raw_confidence, (int, float)):
        vision_confidence = float(raw_confidence)
    elif isinstance(raw_confidence, str):
        try:
            vision_confidence = float(raw_confidence)
        except ValueError:
            vision_confidence = None

    vision_reasoning = descriptor.metadata.get("vision_reasoning")
    if isinstance(vision_reasoning, str) and not vision_reasoning.strip():
        vision_reasoning = None
    if vision_caption is not None and isinstance(vision_caption, str):
        vision_caption = vision_caption.strip() or None
    else:
        vision_caption = None

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
        vision_caption=vision_caption,
        vision_labels=vision_labels,
        vision_confidence=vision_confidence,
        vision_reasoning=vision_reasoning,
    )


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
    "build_original_snapshot",
    "descriptor_to_record",
    "relative_to_collection",
]
