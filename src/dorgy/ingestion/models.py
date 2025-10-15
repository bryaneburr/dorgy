"""Data models used by the ingestion pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class PendingFile(BaseModel):
    """File discovered on disk awaiting processing.

    Attributes:
        path: Absolute path to the pending file.
        size_bytes: Size of the file in bytes.
        modified_at: Timestamp of the last modification.
        locked: Whether the file is currently locked.
        oversized: Whether the file exceeds the configured size limit.
    """

    path: Path
    size_bytes: int
    modified_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    locked: bool = False
    oversized: bool = False


class FileDescriptor(BaseModel):
    """Normalized description produced by ingestion.

    Attributes:
        path: Absolute path to the file.
        display_name: Human-friendly name to present in the UI.
        mime_type: Detected MIME type of the file.
        hash: Optional content hash.
        preview: Optional textual preview.
        metadata: Additional metadata extracted from the file.
        tags: Candidate tags describing the file.
        needs_review: Whether manual review is required.
    """

    path: Path
    display_name: str
    mime_type: str
    hash: Optional[str] = None
    preview: Optional[str] = None
    metadata: Dict[str, str] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    needs_review: bool = False


class IngestionResult(BaseModel):
    """Aggregate result from running the ingestion pipeline.

    Attributes:
        processed: Descriptors produced during ingestion.
        needs_review: Paths that require manual review.
        quarantined: Paths suggested for quarantine.
        errors: Errors encountered during processing.
    """

    processed: List[FileDescriptor] = Field(default_factory=list)
    needs_review: List[Path] = Field(default_factory=list)
    quarantined: List[Path] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
