"""LLM-assisted structure planner for organizing file trees."""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, Iterable, Optional

try:  # pragma: no cover - optional dependency
    import dspy  # type: ignore
except ImportError:  # pragma: no cover - executed when DSPy absent
    dspy = None

from dorgy.classification.dspy_logging import configure_dspy_logging
from dorgy.classification.exceptions import LLMResponseError, LLMUnavailableError
from dorgy.classification.models import ClassificationDecision
from dorgy.config.models import LLMSettings
from dorgy.ingestion.models import FileDescriptor

LOGGER = logging.getLogger(__name__)

_BASE_INSTRUCTIONS = (
    "You are organising a user's personal documents. Produce a concise nested folder "
    "structure that groups related files together. Prefer reusing a small number of "
    "top-level folders and nest subfolders when appropriate. Generate JSON with the "
    'shape {"files": [{"source": "<original relative path>", "destination": '
    '"<relative destination path>"}]}. Do not include absolute paths or drive letters. '
    "Destinations must keep the original filename extension exactly once. Use hyphenated "
    "folder names and avoid extremely long directory chains. Prefer placing files inside "
    "meaningful directories instead of leaving them at the root; create subfolders when it "
    "helps keep related items together, and only leave a file at the top level if no "
    "sensible grouping exists."
)

_CODE_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(?P<body>.*?)\s*```", re.DOTALL | re.IGNORECASE)


class FileTreeSignature(dspy.Signature):  # type: ignore[misc]
    """DSPy signature that requests a destination tree proposal."""

    files_json: str = dspy.InputField()
    goal: str = dspy.InputField()
    tree_json: str = dspy.OutputField()


class StructurePlanner:
    """Use an LLM to propose a nested destination tree for descriptors."""

    def __init__(self, settings: Optional[LLMSettings] = None) -> None:
        legacy_flag = os.getenv("DORGY_USE_FALLBACK")
        if legacy_flag is not None:
            LOGGER.warning(
                "DORGY_USE_FALLBACK is deprecated; set DORGY_USE_FALLBACKS=1 to enable heuristics."
            )

        use_fallback = os.getenv("DORGY_USE_FALLBACKS") == "1"
        self._settings = settings or LLMSettings()
        self._use_fallback = use_fallback
        self._enabled = False
        self._program: Optional[dspy.Module] = None  # type: ignore[attr-defined]

        if use_fallback:
            LOGGER.info("Structure planner fallback enabled by DORGY_USE_FALLBACKS=1.")
            return

        if dspy is None:
            raise LLMUnavailableError(
                "Structure planner requires DSPy. Install the `dspy` package or set "
                "DORGY_USE_FALLBACKS=1 to use heuristic structure placement."
            )

        configure_dspy_logging()
        self._configure_language_model()
        self._program = dspy.Predict(FileTreeSignature)
        self._enabled = True
        LOGGER.debug("Structure planner initialised with LLM model %s.", self._settings.model)

    def _configure_language_model(self) -> None:
        if dspy is None:  # pragma: no cover
            return

        default_settings = LLMSettings()
        configured = any(
            [
                self._settings.api_base_url,
                self._settings.api_key,
                self._settings.model != default_settings.model,
            ]
        )
        if not configured:
            LOGGER.debug("Structure planner using default local LLM configuration.")

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
        except Exception as exc:  # pragma: no cover - DSPy misconfiguration
            raise LLMUnavailableError(
                "Unable to configure the DSPy language model for structure planning. "
                "Verify your llm.* settings (model/api_key/api_base_url)."
            ) from exc
        dspy.settings.configure(lm=language_model)

    def propose(
        self,
        descriptors: Iterable[FileDescriptor],
        decisions: Iterable[ClassificationDecision | None],
        *,
        source_root: Path,
        prompt: Optional[str] = None,
    ) -> Dict[Path, Path]:
        """Return a mapping of descriptor paths to proposed destinations.

        Args:
            descriptors: Ingestion descriptors from the pipeline.
            decisions: Classification decisions aligned with descriptors.
            source_root: Root directory of the collection being organised.
            prompt: Optional user-provided guidance appended to the planner prompt.

        Returns:
            Mapping of descriptor absolute paths to relative destinations.
        """

        if self._use_fallback or not self._enabled or self._program is None:
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

        try:
            response = self._program(
                files_json=json.dumps(payload, ensure_ascii=False),
                goal=self._compose_goal_prompt(prompt),
            )
        except Exception as exc:  # pragma: no cover - defensive safeguard
            LOGGER.debug("Structure planner request failed: %s", exc)
            return {}

        tree_json = getattr(response, "tree_json", "") if response else ""
        if not tree_json:
            LOGGER.debug("Structure planner returned empty tree response.")
            raise LLMResponseError(
                "Structure planner returned an empty response; enable DORGY_USE_FALLBACKS=1 to "
                "continue with heuristic structure placement."
            )

        parsed = self._decode_tree_payload(tree_json)
        if parsed is None:
            snippet = tree_json if isinstance(tree_json, str) else repr(tree_json)
            LOGGER.debug("Structure planner produced unparseable JSON: %s", snippet[:200])
            raise LLMResponseError(
                "Structure planner produced an invalid JSON payload. "
                f"Partial response: {snippet[:160]!r}"
            )

        files = parsed.get("files")
        if not isinstance(files, list):
            LOGGER.debug("Structure planner response missing 'files' array.")
            raise LLMResponseError(
                "Structure planner response is missing the required 'files' array."
            )

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

        if descriptor_list and not mapping:
            LOGGER.debug(
                "Structure planner produced no destinations for %d descriptor(s).",
                len(descriptor_list),
            )
            raise LLMResponseError(
                "Structure planner did not produce destinations for any files. "
                "Verify the configured LLM settings or set DORGY_USE_FALLBACKS=1 to use heuristics."
            )

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

    @staticmethod
    def _decode_tree_payload(tree_json: object) -> Optional[dict]:
        """Return parsed JSON content from structure planner output.

        Args:
            tree_json: Raw payload produced by the DSPy program.

        Returns:
            Parsed JSON object when available, otherwise ``None``.
        """

        if isinstance(tree_json, dict):
            return tree_json
        if isinstance(tree_json, list):
            return {"files": tree_json}
        if not isinstance(tree_json, str):
            return None

        text = tree_json.strip()
        if not text:
            return None

        candidates = StructurePlanner._candidate_json_strings(text)
        decoder = json.JSONDecoder()

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                try:
                    parsed, _ = decoder.raw_decode(candidate)
                except json.JSONDecodeError:
                    continue
            if isinstance(parsed, dict):
                return parsed
            if isinstance(parsed, list):
                return {"files": parsed}
        return None

    @staticmethod
    def _candidate_json_strings(value: str) -> list[str]:
        """Return candidate JSON segments extracted from ``value``.

        Args:
            value: Raw textual payload returned by the language model.

        Returns:
            List of potential JSON substrings ordered by preference.
        """

        candidates: list[str] = []
        match = _CODE_FENCE_PATTERN.search(value)
        if match:
            body = match.group("body").strip()
            if body:
                candidates.append(body)

        if value:
            candidates.append(value)

        sliced = StructurePlanner._slice_json_segment(value, "{", "}")
        if sliced is not None:
            candidates.append(sliced)

        array_slice = StructurePlanner._slice_json_segment(value, "[", "]")
        if array_slice is not None:
            candidates.append(array_slice)

        normalized: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            stripped = candidate.strip()
            if not stripped or stripped in seen:
                continue
            seen.add(stripped)
            normalized.append(stripped)
        return normalized

    @staticmethod
    def _slice_json_segment(value: str, opener: str, closer: str) -> Optional[str]:
        """Return substring enclosed by ``opener`` and ``closer`` when present.

        Args:
            value: Source string to inspect.
            opener: Starting delimiter to search for.
            closer: Ending delimiter to search for.

        Returns:
            Extracted substring when both delimiters are present; otherwise ``None``.
        """

        start = value.find(opener)
        end = value.rfind(closer)
        if start == -1 or end == -1 or end <= start:
            return None
        return value[start : end + 1]

    @staticmethod
    def _compose_goal_prompt(prompt: Optional[str]) -> str:
        """Return the LLM goal instructions including any user guidance.

        Args:
            prompt: Optional user-provided instructions to append.

        Returns:
            Full prompt text supplied to the structure planner model.
        """

        if prompt is None:
            return _BASE_INSTRUCTIONS
        stripped = prompt.strip()
        if not stripped:
            return _BASE_INSTRUCTIONS
        return f"{_BASE_INSTRUCTIONS}\n\nUser guidance:\n{stripped}"
