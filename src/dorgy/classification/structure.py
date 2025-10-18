"""LLM-assisted structure planner for organizing file trees."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, Iterable, Optional

try:  # pragma: no cover - optional dependency
    import dspy  # type: ignore
except ImportError:  # pragma: no cover - executed when DSPy absent
    dspy = None

from dorgy.classification.dspy_logging import configure_dspy_logging
from dorgy.classification.models import ClassificationDecision
from dorgy.config.models import LLMSettings
from dorgy.ingestion.models import FileDescriptor

LOGGER = logging.getLogger(__name__)


class FileTreeSignature(dspy.Signature):  # type: ignore[misc]
    """DSPy signature that requests a destination tree proposal."""

    files_json: str = dspy.InputField()
    goal: str = dspy.InputField()
    tree_json: str = dspy.OutputField()


class StructurePlanner:
    """Use an LLM to propose a nested destination tree for descriptors."""

    def __init__(self, settings: Optional[LLMSettings] = None) -> None:
        use_fallback = os.getenv("DORGY_USE_FALLBACK") == "1"
        self._settings = settings or LLMSettings()
        self._enabled = not use_fallback and dspy is not None
        self._program: Optional[dspy.Module] = None  # type: ignore[attr-defined]
        if self._enabled:
            configure_dspy_logging()
            self._configure_language_model()
            self._program = dspy.Predict(FileTreeSignature)
            LOGGER.debug(
                "Structure planner initialised with LLM provider %s.", self._settings.provider
            )
        else:
            LOGGER.debug("Structure planner disabled (fallback or DSPy unavailable).")

    def _configure_language_model(self) -> None:
        if dspy is None:  # pragma: no cover
            return

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
            LOGGER.debug("Structure planner using default local LLM configuration.")

        api_key_missing = self._settings.api_key is None

        if self._settings.api_base_url and api_key_missing:
            self._settings.api_key = ""
            api_key_missing = False

        if (
            self._settings.provider
            and self._settings.provider != "local"
            and self._settings.api_base_url is None
            and api_key_missing
        ):
            raise RuntimeError(
                "Structure planner requires llm.api_key when using a remote provider."
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

        language_model = dspy.LM(**lm_kwargs)
        dspy.settings.configure(lm=language_model)

    def propose(
        self,
        descriptors: Iterable[FileDescriptor],
        decisions: Iterable[ClassificationDecision | None],
        *,
        source_root: Path,
    ) -> Dict[Path, Path]:
        """Return a mapping of descriptor paths to proposed destinations.

        Args:
            descriptors: Ingestion descriptors from the pipeline.
            decisions: Classification decisions aligned with descriptors.
            source_root: Root directory of the collection being organised.

        Returns:
            Mapping of descriptor absolute paths to relative destinations.
        """

        if not self._enabled or self._program is None:
            return {}

        descriptor_list = list(descriptors)
        decision_list = list(decisions)
        if not descriptor_list:
            return {}

        payload: list[dict[str, object]] = []
        for index, descriptor in enumerate(descriptor_list):
            decision = decision_list[index] if index < len(decision_list) else None
            try:
                relative = str(descriptor.path.relative_to(source_root))
            except ValueError:
                relative = descriptor.path.name
            preview = (descriptor.preview or "").strip()
            if len(preview) > 400:
                preview = preview[:397] + "..."
            metadata = dict(descriptor.metadata or {})
            size = None
            if "size_bytes" in metadata:
                try:
                    size = int(metadata["size_bytes"])
                except (TypeError, ValueError):
                    metadata.pop("size_bytes", None)
            entry: dict[str, object] = {
                "source": str(relative),
                "mime_type": descriptor.mime_type,
                "size_bytes": size,
                "metadata": metadata,
                "preview": preview,
                "tags": [],
                "primary_category": None,
                "secondary_categories": [],
                "confidence": None,
            }
            if decision is not None:
                entry.update(
                    {
                        "primary_category": decision.primary_category,
                        "secondary_categories": decision.secondary_categories,
                        "tags": decision.tags,
                        "confidence": decision.confidence,
                    }
                )
            payload.append(entry)

        instructions = (
            "You are organising a user's personal documents. Produce a concise nested folder "
            "structure that groups related files together. Prefer reusing a small number of "
            "top-level folders and nest subfolders when appropriate. Generate JSON with the "
            'shape {"files": [{"source": "<original relative path>", "destination": '
            '"<relative destination path>"}]}. Do not include absolute paths or drive letters. '
            "Destinations must keep the original filename extension exactly once. Use hyphenated "
            "folder names and avoid extremely long directory chains."
        )

        try:
            response = self._program(
                files_json=json.dumps(payload, ensure_ascii=False),
                goal=instructions,
            )
        except Exception as exc:  # pragma: no cover - defensive safeguard
            LOGGER.debug("Structure planner request failed: %s", exc)
            return {}

        tree_json = getattr(response, "tree_json", "") if response else ""
        if not tree_json:
            LOGGER.debug("Structure planner returned empty tree response.")
            return {}

        try:
            parsed = json.loads(tree_json)
        except json.JSONDecodeError as exc:
            LOGGER.debug("Failed to parse structure planner response: %s", exc)
            return {}

        files = parsed.get("files")
        if not isinstance(files, list):
            LOGGER.debug("Structure planner response missing 'files' array.")
            return {}

        mapping: Dict[Path, Path] = {}
        for entry in files:
            if not isinstance(entry, dict):
                continue
            source = entry.get("source")
            destination = entry.get("destination")
            if not isinstance(source, str) or not isinstance(destination, str):
                continue
            source_path = self._match_descriptor(source, descriptor_list, source_root)
            if source_path is None:
                continue
            destination_path = Path(destination.strip().lstrip("/\\"))
            if destination_path.parts:
                mapping[source_path] = destination_path

        LOGGER.debug("Structure planner produced destinations for %d file(s).", len(mapping))
        return mapping

    @staticmethod
    def _match_descriptor(
        relative: str,
        descriptors: Iterable[FileDescriptor],
        root: Path,
    ) -> Optional[Path]:
        for descriptor in descriptors:
            try:
                descriptor_relative = descriptor.path.relative_to(root)
            except ValueError:
                descriptor_relative = descriptor.path
            if str(descriptor_relative).strip() == relative.strip():
                return descriptor.path
        return None
