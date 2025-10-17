"""Classification engine built on top of DSPy.

This module exposes a thin wrapper around DSPy programs so the rest of the
codebase can request classifications without depending directly on DSPy.
When DSPy is unavailable, the engine falls back to lightweight heuristics so
we can still exercise the higher-level pipeline in development and tests.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Iterable, Optional

try:  # pragma: no cover - optional dependency
    import dspy  # type: ignore
except ImportError:  # pragma: no cover - executed when DSPy absent
    dspy = None

from dorgy.config.models import LLMSettings

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

    def __init__(self, settings: Optional[LLMSettings] = None) -> None:
        use_fallback = os.getenv("DORGY_USE_FALLBACK") == "1"
        self._settings = settings or LLMSettings()

        if use_fallback:
            self._has_dspy = False
            self._program = None
            LOGGER.info("Heuristic fallback enabled by DORGY_USE_FALLBACK=1.")
            return

        if dspy is None:
            raise RuntimeError(
                "DSPy is not installed. Install the `dspy` package (and any provider-specific "
                "dependencies), or set DORGY_USE_FALLBACK=1 to enable the heuristic classifier."
            )

        self._settings = settings or LLMSettings()
        self._configure_language_model()
        self._program = self._build_program()
        self._has_dspy = True

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
                batch.decisions.append(None)
        return batch

    def _build_program(self):
        """Construct the DSPy program used for classification.

        Returns:
            Any: DSPy program object that can be executed for classification.
        """

        if dspy is None:  # pragma: no cover - guarded by caller
            raise RuntimeError("DSPy is not installed")

        class FileClassificationSignature(dspy.Signature):
            """Classify a file into categories and generate tags."""

            filename: str = dspy.InputField()
            file_type: str = dspy.InputField()
            content_preview: str = dspy.InputField()
            metadata: str = dspy.InputField()
            prompt: str = dspy.InputField()

            primary_category: str = dspy.OutputField()
            secondary_categories: list[str] = dspy.OutputField()
            tags: list[str] = dspy.OutputField()
            confidence: str = dspy.OutputField()
            reasoning: str = dspy.OutputField()

        class FileRenamingSignature(dspy.Signature):
            """Generate a descriptive filename for a file."""

            filename: str = dspy.InputField()
            file_type: str = dspy.InputField()
            content_preview: str = dspy.InputField()
            metadata: str = dspy.InputField()
            category: str = dspy.InputField()
            prompt: str = dspy.InputField()

            suggested_name: str = dspy.OutputField()
            reasoning: str = dspy.OutputField()

        class DorgyClassifier(dspy.Module):
            def __init__(self) -> None:
                super().__init__()
                self.classifier = dspy.ChainOfThought(FileClassificationSignature)
                self.renamer = dspy.ChainOfThought(FileRenamingSignature)

            def forward(self, payload: dict[str, str]):
                classification = self.classifier(**payload)
                rename = self.renamer(
                    filename=payload["filename"],
                    file_type=payload["file_type"],
                    content_preview=payload["content_preview"],
                    metadata=payload["metadata"],
                    category=classification.primary_category,
                    prompt=payload["prompt"],
                )
                return classification, rename

        return DorgyClassifier()

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #

    def _configure_language_model(self) -> None:
        """Configure the DSPy language model according to LLM settings."""
        default_settings = LLMSettings()
        configured = any(
            [
                self._settings.api_base_url,
                self._settings.api_key,
                self._settings.provider != default_settings.provider,
                self._settings.model != default_settings.model,
            ]
        )
        if not configured:
            raise RuntimeError(
                "LLM configuration is incomplete. Update ~/.dorgy/config.yaml with valid values "
                "for the llm block (provider/model/api_key or api_base_url), or set "
                "DORGY_USE_FALLBACK=1 to force the heuristic classifier."
            )

        api_key_missing = self._settings.api_key is None

        if self._settings.api_base_url and api_key_missing:
            # Local gateways (e.g., Ollama) don't require authentication, so supply an empty string.
            self._settings.api_key = ""
            api_key_missing = False

        if (
            self._settings.provider
            and self._settings.provider != "local"
            and self._settings.api_base_url is None
            and api_key_missing
        ):
            raise RuntimeError(
                "llm.provider is set to a remote provider but llm.api_key is missing. Provide the "
                "API key or set DORGY_USE_FALLBACK=1 to use the heuristic classifier."
            )

        lm_kwargs: dict[str, object] = {
            "model": self._settings.model,
            "temperature": self._settings.temperature,
            "max_tokens": self._settings.max_tokens,
        }

        if self._settings.api_base_url:
            lm_kwargs["api_base"] = self._settings.api_base_url
        elif self._settings.provider:
            lm_kwargs["provider"] = self._settings.provider

        if self._settings.api_key is not None:
            lm_kwargs["api_key"] = self._settings.api_key

        try:
            language_model = dspy.LM(**lm_kwargs)
            dspy.settings.configure(lm=language_model)
        except Exception as exc:  # pragma: no cover - DSPy misconfiguration
            raise RuntimeError(
                "Unable to configure the DSPy language model. Verify your llm.* settings "
                "(provider/model/api_key/api_base_url) or set DORGY_USE_FALLBACK=1 to use the "
                "heuristic classifier."
            ) from exc

    def _classify_with_dspy(self, request: ClassificationRequest) -> ClassificationDecision:
        """Leverage DSPy program to classify the file.

        Args:
            request: Classification request to evaluate.

        Returns:
            ClassificationDecision: Result derived from DSPy output.
        """
        if self._program is None:
            raise RuntimeError("DSPy program has not been initialised")

        descriptor = request.descriptor
        metadata_dump = json.dumps(descriptor.metadata, ensure_ascii=False)

        payload = {
            "filename": descriptor.display_name,
            "file_type": descriptor.mime_type,
            "content_preview": descriptor.preview or "",
            "metadata": metadata_dump,
            "prompt": request.prompt or "",
        }

        classification, rename = self._program.forward(payload)

        try:
            confidence = float(classification.confidence)
        except (ValueError, TypeError):
            confidence = 0.0

        secondary = classification.secondary_categories or []
        tags = classification.tags or []
        rename_suggestion = getattr(rename, "suggested_name", None)

        needs_review = confidence < 0.5
        reasoning_parts = [classification.reasoning]
        if getattr(rename, "reasoning", None):
            reasoning_parts.append(rename.reasoning)
        reasoning = "\n".join(part for part in reasoning_parts if part)

        return ClassificationDecision(
            primary_category=classification.primary_category or "General",
            secondary_categories=[cat for cat in secondary if cat],
            tags=[tag for tag in tags if tag],
            confidence=confidence,
            rename_suggestion=rename_suggestion or None,
            reasoning=reasoning or None,
            needs_review=needs_review,
        )

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
