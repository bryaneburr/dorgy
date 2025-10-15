"""State data models for organized collections (Phase 0 scaffolding)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class FileRecord(BaseModel):
    """Metadata describing a file in an organized collection."""

    path: str
    hash: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    last_modified: Optional[datetime] = None


class CollectionState(BaseModel):
    """Aggregate metadata for an organized directory."""

    root: str
    files: Dict[str, FileRecord] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


__all__ = ["FileRecord", "CollectionState"]
