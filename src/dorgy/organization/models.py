"""Organization plan data models."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field


class RenameOperation(BaseModel):
    """Represents a file rename action."""

    source: Path
    destination: Path
    reasoning: Optional[str] = None


class MoveOperation(BaseModel):
    """Represents moving a file to a new directory."""

    source: Path
    destination: Path
    reasoning: Optional[str] = None


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
