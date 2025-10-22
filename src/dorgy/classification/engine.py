"""Classification engine built on top of DSPy.

This module exposes a thin wrapper around DSPy programs so the rest of the
codebase can request classifications without depending directly on DSPy.
When DSPy is unavailable, the engine falls back to lightweight heuristics only
when ``DORGY_USE_FALLBACKS=1`` so we can still exercise the higher-level
pipeline in development and tests.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable, Optional

try:  # pragma: no cover - optional dependency
    import dspy  # type: ignore
except ImportError:  # pragma: no cover - executed when DSPy absent
    dspy = None

from dorgy.classification.dspy_logging import configure_dspy_logging
from dorgy.classification.exceptions import LLMUnavailableError
from dorgy.config.models import LLMSettings
from dorgy.shutdown import ShutdownRequested, check_for_shutdown

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

_CONFIDENCE_PATTERN = re.compile(r"-?\d+(?:\.\d+)?")


def _coerce_confidence(raw: object, *, default: float = 0.5) -> float:
    """Return a normalised confidence score between 0 and 1.

    Args:
        raw: Value returned by the language model for confidence.
        default: Fallback value to use when the model omits a numeric score.

    Returns:
        float: Confidence bounded to the inclusive range ``[0.0, 1.0]``.
    """

    numeric: Optional[float] = None

    if isinstance(raw, (int, float)):
        numeric = float(raw)
    elif isinstance(raw, str):
        stripped = raw.strip()
        if stripped:
            candidate = stripped.replace(",", ".")
            match = _CONFIDENCE_PATTERN.search(candidate)
            if match:
                try:
                    numeric = float(match.group())
                except ValueError:
                    numeric = None
            if numeric is None:
                lowered = stripped.lower()
                if "high" in lowered:
                    numeric = 0.9
                elif "medium" in lowered:
                    numeric = 0.6
                elif "low" in lowered:
                    numeric = 0.2
    if numeric is None:
        numeric = default
    if not (numeric >= 0.0):
        numeric = default
    return max(0.0, min(1.0, numeric))


class ClassificationEngine:
    """Apply DSPy programs to classify and rename files.

    The engine prefers DSPy when available, but only falls back to heuristic
    classification when ``DORGY_USE_FALLBACKS=1`` so development and tests can
    proceed without the optional dependency.
    """

    def __init__(self, settings: Optional[LLMSettings] = None) -> None:
        legacy_flag = os.getenv("DORGY_USE_FALLBACK")
        if legacy_flag is not None:
            LOGGER.warning(
                "DORGY_USE_FALLBACK is deprecated; set DORGY_USE_FALLBACKS=1 to enable heuristics."
            )

        use_fallback = os.getenv("DORGY_USE_FALLBACKS") == "1"
        self._settings = settings or LLMSettings()
        self._use_fallbacks = use_fallback

        if use_fallback:
            self._has_dspy = False
            self._program = None
            LOGGER.info("Heuristic fallback enabled by DORGY_USE_FALLBACKS=1.")
            return

        if dspy is None:
            raise LLMUnavailableError(
                "DSPy is not installed. Install the `dspy` package (and any provider-specific "
                "dependencies), or set DORGY_USE_FALLBACKS=1 to enable the heuristic classifier."
            )

        configure_dspy_logging()
        self._configure_language_model()
        self._program = self._build_program()
        self._has_dspy = True

    def classify(
        self,
        requests: Iterable[ClassificationRequest],
        *,
        max_workers: int = 1,
        progress_callback: Optional[
            Callable[
                [
                    int,
                    ClassificationRequest,
                    int,
                    str,
                    Optional[float],
                    Optional[Exception],
                ],
                None,
            ]
        ] = None,
    ) -> ClassificationBatch:
        """Run the DSPy program for each request.

        Args:
            requests: Iterable of classification requests to evaluate.
            max_workers: Maximum number of concurrent worker threads.
            progress_callback: Optional callback invoked for progress updates. The
                callback receives the request index, original request, worker ID,
                event (``"start"``/``"complete"``), elapsed duration, and any
                raised exception.

        Returns:
            ClassificationBatch: Aggregated decisions and errors.
        """
        requests = list(requests)
        check_for_shutdown()
        batch = ClassificationBatch(decisions=[None] * len(requests), errors=[])
        if not requests:
            return batch

        worker_count = max(1, min(max_workers, len(requests)))

        worker_lock = threading.Lock()
        worker_ids: dict[int, int] = {}
        worker_counter = 0

        def _worker_id() -> int:
            nonlocal worker_counter
            thread_id = threading.get_ident()
            with worker_lock:
                worker = worker_ids.get(thread_id)
                if worker is None:
                    worker = worker_counter
                    worker_ids[thread_id] = worker
                    worker_counter += 1
                return worker

        def _notify_progress(
            index: int,
            request: ClassificationRequest,
            worker_id: int,
            event: str,
            duration: Optional[float],
            error: Optional[Exception],
        ) -> None:
            if progress_callback is None:
                return
            try:
                progress_callback(index, request, worker_id, event, duration, error)
            except Exception:  # pragma: no cover - progress callbacks are best effort
                LOGGER.debug(
                    "Progress callback failed for %s event=%s",
                    request.descriptor.path,
                    event,
                )

        def _classify_single(
            index: int, request: ClassificationRequest
        ) -> tuple[int, Optional[ClassificationDecision], Optional[str]]:
            check_for_shutdown()
            start = time.perf_counter()
            worker_id = _worker_id()
            _notify_progress(index, request, worker_id, "start", None, None)
            try:
                decision = self._classify_request(request)
            except Exception as exc:  # pragma: no cover - defensive safeguard
                duration = time.perf_counter() - start
                LOGGER.warning(
                    "Classification failed for %s after %.2fs: %s",
                    request.descriptor.path,
                    duration,
                    exc,
                )
                _notify_progress(index, request, worker_id, "complete", duration, exc)
                if not self._use_fallbacks or isinstance(exc, LLMUnavailableError):
                    raise
                LOGGER.info(
                    "Falling back to heuristic classification for %s after DSPy failure.",
                    request.descriptor.path,
                )
                decision = self._fallback_classify(request)
            duration = time.perf_counter() - start
            LOGGER.debug(
                "Classification completed for %s in %.2fs",
                request.descriptor.path,
                duration,
            )
            _notify_progress(index, request, worker_id, "complete", duration, None)
            return index, decision, None

        if worker_count == 1:
            for idx, request in enumerate(requests):
                check_for_shutdown()
                index, decision, error = _classify_single(idx, request)
                batch.decisions[index] = decision
                if error:
                    batch.errors.append(error)
            return batch

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {
                executor.submit(_classify_single, idx, request): idx
                for idx, request in enumerate(requests)
            }
            try:
                for future in as_completed(future_map):
                    check_for_shutdown()
                    index, decision, error = future.result()
                    batch.decisions[index] = decision
                    if error:
                        batch.errors.append(error)
            except ShutdownRequested:
                for future in future_map:
                    future.cancel()
                raise

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
                self.classifier = dspy.Predict(FileClassificationSignature)
                self.renamer = dspy.Predict(FileRenamingSignature)

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

    def _classify_request(self, request: ClassificationRequest) -> ClassificationDecision:
        """Return a classification decision using DSPy or heuristics."""

        if self._has_dspy and self._program is not None:
            return self._classify_with_dspy(request)

        if self._use_fallbacks:
            return self._fallback_classify(request)

        raise LLMUnavailableError(
            "Heuristic fallbacks are disabled. Set DORGY_USE_FALLBACKS=1 to allow heuristics when "
            "the configured language model cannot be used."
        )

    def _configure_language_model(self) -> None:
        """Configure the DSPy language model according to LLM settings."""
        default_settings = LLMSettings()
        configured = any(
            [
                self._settings.api_base_url,
                self._settings.api_key,
                self._settings.model != default_settings.model,
            ]
        )
        if not configured:
            raise LLMUnavailableError(
                "LLM configuration is incomplete. Update ~/.dorgy/config.yaml with valid values "
                "for the llm block (model/api_key/api_base_url), or set "
                "DORGY_USE_FALLBACKS=1 to force the heuristic classifier."
            )

        lm_kwargs: dict[str, object] = {
            "model": self._settings.model,
            "temperature": self._settings.temperature,
            "max_tokens": self._settings.max_tokens,
        }

        if self._settings.api_base_url:
            lm_kwargs["api_base"] = self._settings.api_base_url
        if self._settings.api_key is not None and self._settings.api_key != "":
            lm_kwargs["api_key"] = self._settings.api_key

        try:
            language_model = dspy.LM(**lm_kwargs)
            dspy.settings.configure(lm=language_model)
        except Exception as exc:  # pragma: no cover - DSPy misconfiguration
            raise LLMUnavailableError(
                "Unable to configure the DSPy language model. Verify your llm.* settings "
                "(model/api_key/api_base_url) or set DORGY_USE_FALLBACKS=1 to use the "
                "heuristic classifier."
            ) from exc

    def _fallback_confidence(self, classification: object) -> float:
        """Return a conservative confidence when the model omits a score.

        Args:
            classification: Raw DSPy classification object.

        Returns:
            float: Calibrated confidence derived from category and tag signals.
        """

        primary = getattr(classification, "primary_category", None)
        if isinstance(primary, str) and primary.strip():
            if primary.strip().lower() != "general":
                return 0.6
        tags = getattr(classification, "tags", None) or []
        if tags:
            return 0.5
        return 0.4

    def _classify_with_dspy(self, request: ClassificationRequest) -> ClassificationDecision:
        """Leverage DSPy program to classify the file.

        Args:
            request: Classification request to evaluate.

        Returns:
            ClassificationDecision: Result derived from DSPy output.
        """
        if self._program is None:
            raise LLMUnavailableError("DSPy program has not been initialised")

        descriptor = request.descriptor
        metadata_dump = json.dumps(descriptor.metadata, ensure_ascii=False)

        payload = {
            "filename": descriptor.display_name,
            "file_type": descriptor.mime_type,
            "content_preview": descriptor.preview or "",
            "metadata": metadata_dump,
            "prompt": request.prompt or "",
        }

        confidence_guidance = (
            "When providing the confidence value, respond with a decimal between 0 and 1 "
            "(for example 0.73). Avoid percentages or verbal qualifiers."
        )
        if payload["prompt"]:
            payload["prompt"] = f"{payload['prompt']}\n\n{confidence_guidance}"
        else:
            payload["prompt"] = confidence_guidance

        classification, rename = self._program(payload)

        confidence_raw = getattr(classification, "confidence", None)
        confidence = _coerce_confidence(confidence_raw)
        if confidence <= 0.0:
            confidence = self._fallback_confidence(classification)

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
