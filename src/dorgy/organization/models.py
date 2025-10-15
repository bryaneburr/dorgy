"""Organization plan data models."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


class RenameOperation(BaseModel):
    """Represents a file rename action.

    Attributes:
        source: Original file path prior to the rename.
        destination: Target path after the rename.
        reasoning: Optional explanation for the rename.
        conflict_strategy: Conflict policy applied when resolving name collisions.
        conflict_applied: Indicates whether a conflict was encountered.
    """

    source: Path
    destination: Path
    reasoning: Optional[str] = None
    conflict_strategy: Optional[str] = None
    conflict_applied: bool = False


class MoveOperation(BaseModel):
    """Represents moving a file to a new directory.

    Attributes:
        source: Starting file path before the move.
        destination: Destination path after the move.
        reasoning: Optional explanation for the move.
        conflict_strategy: Conflict policy applied when resolving destination collisions.
        conflict_applied: Indicates whether a conflict was encountered.
    """

    source: Path
    destination: Path
    reasoning: Optional[str] = None
    conflict_strategy: Optional[str] = None
    conflict_applied: bool = False


class MetadataOperation(BaseModel):
    """Represents metadata updates (tags/categories) on a file."""

    path: Path
    add: List[str] = Field(default_factory=list)
    remove: List[str] = Field(default_factory=list)


class OperationPlan(BaseModel):
    """Aggregated organization plan."""

    renames: List[RenameOperation] = Field(default_factory=list)
    moves: List[MoveOperation] = Field(default_factory=list)
    metadata_updates: List[MetadataOperation] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)
