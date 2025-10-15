"""Classification engine built on top of DSPy.

This module exposes a thin wrapper around DSPy programs so the rest of the
codebase can request classifications without depending directly on DSPy.
When DSPy is unavailable, the engine falls back to lightweight heuristics so
we can still exercise the higher-level pipeline in development and tests.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterable, Optional

try:  # pragma: no cover - optional dependency
    import dspy  # type: ignore
except ImportError:  # pragma: no cover - executed when DSPy absent
    dspy = None

from .models import (
    ClassificationBatch,
    ClassificationDecision,
    ClassificationRequest,
)

LOGGER = logging.getLogger(__name__)

_CATEGORY_ALIASES = {
    "text": "Documents",
    "application": "Documents",
    "audio": "Media/Audio",
    "video": "Media/Video",
    "image": "Media/Images",
}


class ClassificationEngine:
    """Apply DSPy programs to classify and rename files.

    The engine prefers DSPy when available, but automatically falls back to
    heuristic classification so development and tests can proceed without the
    optional dependency.
    """

    def __init__(self) -> None:
        self._has_dspy = dspy is not None
        if self._has_dspy:
            try:
                self._program = self._build_program()
            except NotImplementedError:
                LOGGER.info("DSPy program not yet implemented; using heuristic fallback instead.")
                self._program = None
                self._has_dspy = False
        if not self._has_dspy:
            self._program = None
            LOGGER.info("DSPy not installed; using heuristic fallback for classification.")

    def classify(self, requests: Iterable[ClassificationRequest]) -> ClassificationBatch:
        """Run the DSPy program for each request.

        Args:
            requests: Iterable of classification requests to evaluate.

        Returns:
            ClassificationBatch: Aggregated decisions and errors.
        """
        batch = ClassificationBatch()
        for request in requests:
            try:
                if self._has_dspy and self._program is not None:
                    decision = self._classify_with_dspy(request)
                else:
                    decision = self._fallback_classify(request)
                batch.decisions.append(decision)
            except Exception as exc:  # pragma: no cover - defensive safeguard
                batch.errors.append(f"{request.descriptor.path}: {exc}")
        return batch

    def _build_program(self):
        """Construct the DSPy program used for classification.

        Returns:
            Any: DSPy program object that can be executed for classification.
        """
        raise NotImplementedError(
            "ClassificationEngine._build_program will be implemented in Phase 3."
        )

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _classify_with_dspy(self, request: ClassificationRequest) -> ClassificationDecision:
        """Leverage DSPy program to classify the file.

        Args:
            request: Classification request to evaluate.

        Returns:
            ClassificationDecision: Result derived from DSPy output.
        """
        raise NotImplementedError("DSPy integration not yet implemented.")

    def _fallback_classify(self, request: ClassificationRequest) -> ClassificationDecision:
        """Heuristic classification used when DSPy is unavailable.

        Args:
            request: Classification request to evaluate.

        Returns:
            ClassificationDecision: Result derived from heuristics.
        """
        descriptor = request.descriptor
        mime = descriptor.mime_type.lower()
        tags = descriptor.tags[:]
        path = descriptor.path
        prompt = request.prompt or ""

        primary_category = self._category_from_mime(mime, tags, path)
        secondary_categories = []
        rename = self._rename_suggestion(path, descriptor.display_name)

        if primary_category not in tags:
            tags.append(primary_category)

        if prompt:
            lowered = prompt.lower()
            if "finance" in lowered and "Finance" not in primary_category:
                secondary_categories.append("Finance")
            if "legal" in lowered and "Legal" not in secondary_categories:
                secondary_categories.append("Legal")

        confidence = 0.6 if primary_category != "General" else 0.4
        needs_review = confidence < 0.5

        reasoning = f"Heuristic classification based on mime={mime} tags={tags} path={path.name}."

        return ClassificationDecision(
            primary_category=primary_category,
            secondary_categories=secondary_categories,
            tags=tags or [primary_category],
            confidence=confidence,
            rename_suggestion=rename,
            reasoning=reasoning,
            needs_review=needs_review,
        )

    # ------------------------------------------------------------------ #
    # Heuristic helpers                                                  #
    # ------------------------------------------------------------------ #

    def _category_from_mime(self, mime: str, tags: list[str], path: Path) -> str:
        """Derive a category from MIME type, tags, or filename."""
        if tags:
            candidate = tags[0].lower()
            mapped = _CATEGORY_ALIASES.get(candidate)
            if mapped:
                return mapped
            if "/" not in candidate:
                return candidate.title()

        if mime.startswith("image/"):
            return "Media/Images"
        if mime in {"application/pdf", "application/msword"} or mime.startswith("text/"):
            return "Documents"
        if mime.startswith("audio/"):
            return "Media/Audio"
        if mime.startswith("video/"):
            return "Media/Video"
        if path.suffix.lower() in {".csv", ".xlsx"}:
            return "Data/Spreadsheets"
        return "General"

    def _rename_suggestion(self, path: Path, display_name: str) -> Optional[str]:
        """Generate a simple rename suggestion without extension."""
        stem = display_name.rsplit(".", 1)[0]
        stem = re.sub(r"[ _]+", "-", stem.strip().lower())
        if not stem:
            stem = path.stem
        return stem or None
