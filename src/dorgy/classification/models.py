"""Classification data models.

This module defines Pydantic models representing requests and outputs for the
classification pipeline.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from pydantic import BaseModel, Field

from dorgy.ingestion import FileDescriptor


class ClassificationRequest(BaseModel):
    """Input payload consumed by the classification engine.

    Attributes:
        descriptor: File descriptor produced by the ingestion pipeline.
        prompt: Optional domain-specific instructions from the user.
        collection_root: Absolute path to the collection being organized.
    """

    descriptor: FileDescriptor
    prompt: Optional[str] = None
    collection_root: Path


class ClassificationDecision(BaseModel):
    """Single classification decision for a file.

    Attributes:
        primary_category: Top-level category recommendation.
        secondary_categories: Additional suggested categories.
        tags: Descriptive tags to attach to the file.
        confidence: Confidence score between 0 and 1.
        rename_suggestion: Optional recommended new filename without extension.
        reasoning: Free-form explanation of the decision.
        needs_review: Flag set when human review is required.
    """

    primary_category: str
    secondary_categories: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    confidence: float = 0.0
    rename_suggestion: Optional[str] = None
    reasoning: Optional[str] = None
    needs_review: bool = False


class ClassificationBatch(BaseModel):
    """Aggregate classification outcome for a batch run.

    Attributes:
        decisions: Classification decisions aligned with requests (``None`` when an error occurs).
        errors: Human-readable error messages for failed items.
    """

    decisions: List[Optional[ClassificationDecision]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class VisionCaption(BaseModel):
    """Captioning result derived from a DSPy image signature.

    Attributes:
        caption: Concise textual description of the image.
        labels: Short labels summarizing key elements within the image.
        confidence: Confidence score between 0 and 1 when provided by the model.
        reasoning: Optional reasoning or explanation returned by the model.
    """

    caption: str
    labels: List[str] = Field(default_factory=list)
    confidence: Optional[float] = None
    reasoning: Optional[str] = None
