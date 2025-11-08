"""LLM-assisted structure planner for organizing file trees."""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

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
    "You are organising a user's personal documents. Follow these rules exactly:\n"
    '1. Generate JSON matching {"files": [{"source": "<relative path>", '
    '"destination": "<relative path>"}]} and nothing else.\n'
    "2. Propose a destination for every provided file exactly once. Do not invent files "
    "or skip any entries.\n"
    "3. Destinations must keep the original filename (including extension) and use at "
    "least two path segments (e.g., 'Projects/Taxes/file.pdf').\n"
    "4. Only place a file directly under the root when you intentionally use a "
    "fallback folder named 'misc/<filename>'.\n"
    "5. Prefer a small, meaningful set of top-level folders, add subfolders when it "
    "improves grouping, and avoid chains deeper than four levels.\n"
    "6. Reuse existing folder hints from the collection when sensible, keep names "
    "concise with hyphens, and never include absolute paths or drive letters.\n"
    "7. Whenever multiple files share a theme (same category, institution, project, or "
    "year), create a top-level folder describing the theme and group files into nested "
    "subfolders (e.g., 'Taxes/2024/1099/filename.pdf').\n"
    "Example output format:\n"
    "{\n"
    '  "files": [\n'
    '    {"source": "1099_2024.pdf", "destination": "Taxes/2024/Forms/1099_2024.pdf"},\n'
    '    {"source": "project_alpha_update.pdf", "destination": '
    '"Legal/Correspondence/Project-Alpha/project_alpha_update.pdf"}\n'
    "  ]\n"
    "}\n"
)

_FALLBACK_PARENT = Path("misc")


@dataclass
class StructurePlannerMetrics:
    """Lightweight telemetry describing the most recent planner run."""

    attempts: int = 0
    reminder_used: bool = False
    normalized_missing: int = 0
    normalized_shallow: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "attempts": self.attempts,
            "reminder_used": self.reminder_used,
            "normalized_missing": self.normalized_missing,
            "normalized_shallow": self.normalized_shallow,
            "normalized_total": self.normalized_missing + self.normalized_shallow,
        }


_CODE_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(?P<body>.*?)\s*```", re.DOTALL | re.IGNORECASE)


class FileTreeSignature(dspy.Signature):  # type: ignore[misc]
    """DSPy signature that requests a destination tree proposal."""

    files_json: str = dspy.InputField()
    goal: str = dspy.InputField()
    tree_json: str = dspy.OutputField()


class StructurePlanner:
    """Use an LLM to propose a nested destination tree for descriptors."""

    def __init__(
        self,
        settings: Optional[LLMSettings] = None,
        *,
        enable_reprompt: bool = True,
    ) -> None:
        legacy_flag = os.getenv("DORGY_USE_FALLBACK")
        if legacy_flag is not None:
            LOGGER.warning(
                "DORGY_USE_FALLBACK is deprecated; set DORGY_USE_FALLBACKS=1 to enable heuristics."
            )

        use_fallback = os.getenv("DORGY_USE_FALLBACKS") == "1"
        self._settings = settings or LLMSettings()
        self._use_fallback = use_fallback
        self._allow_reprompt = enable_reprompt
        self._enabled = False
        self._program: Optional[dspy.Module] = None  # type: ignore[attr-defined]
        self._last_metrics = StructurePlannerMetrics()

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
            self._last_metrics = StructurePlannerMetrics()
            return {}

        descriptor_list = list(descriptors)
        decision_list = list(decisions)
        if not descriptor_list:
            self._last_metrics = StructurePlannerMetrics()
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

        payload_json = json.dumps(payload, ensure_ascii=False)
        summary = self._build_descriptor_summary(descriptor_list, decision_list, source_root)

        attempts = 0
        max_attempts = 2 if self._allow_reprompt else 1
        reminder_used = False
        reminder_prompt: Optional[str] = None
        mapping: Dict[Path, Path] = {}
        missing_sources: List[Path] = []
        shallow_sources: List[Tuple[Path, Path]] = []

        while attempts < max_attempts:
            attempts += 1
            effective_prompt = self._merge_prompts(prompt, reminder_prompt)
            goal = self._compose_goal_prompt(summary, effective_prompt)
            try:
                response = self._program(files_json=payload_json, goal=goal)
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

            mapping = self._build_mapping(files, descriptor_list, source_root)

            if descriptor_list and not mapping:
                if attempts >= 2:
                    LOGGER.debug(
                        "Structure planner produced no destinations for %d descriptor(s).",
                        len(descriptor_list),
                    )
                    raise LLMResponseError(
                        "Structure planner did not produce destinations for any files. "
                        "Verify the configured LLM settings or set DORGY_USE_FALLBACKS=1 "
                        "to use heuristics."
                    )
            missing_sources, shallow_sources = self._detect_structure_issues(
                mapping,
                descriptor_list,
            )
            if not missing_sources and not shallow_sources:
                break

            reminder_prompt = self._build_violation_prompt(
                source_root,
                missing_sources,
                shallow_sources,
            )
            reminder_used = True

        if descriptor_list and not mapping:
            LOGGER.debug(
                "Structure planner produced no destinations for %d descriptor(s).",
                len(descriptor_list),
            )
            raise LLMResponseError(
                "Structure planner did not produce destinations for any files. "
                "Verify the configured LLM settings or set DORGY_USE_FALLBACKS=1 to use heuristics."
            )

        normalized_missing = 0
        normalized_shallow = 0
        if missing_sources or shallow_sources:
            normalized_missing = len(missing_sources)
            normalized_shallow = len(shallow_sources)
            mapping, adjustments = self._normalize_mapping(
                mapping,
                descriptor_list,
                missing_sources,
                shallow_sources,
                source_root,
            )
            for note in adjustments:
                LOGGER.warning(note)

        self._last_metrics = StructurePlannerMetrics(
            attempts=attempts,
            reminder_used=reminder_used,
            normalized_missing=normalized_missing,
            normalized_shallow=normalized_shallow,
        )
        LOGGER.debug("Structure planner produced destinations for %d file(s).", len(mapping))
        return mapping

    @property
    def last_metrics(self) -> StructurePlannerMetrics:
        return getattr(self, "_last_metrics", StructurePlannerMetrics())

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
    def _build_descriptor_summary(
        descriptors: Iterable[FileDescriptor],
        decisions: Iterable[ClassificationDecision | None],
        root: Path,
    ) -> str:
        descriptor_list = list(descriptors)
        decision_list = list(decisions)
        total = len(descriptor_list)
        if total == 0:
            return ""

        categories: Counter[str] = Counter()
        mime_groups: Counter[str] = Counter()
        parent_hints: Counter[str] = Counter()
        duplicate_stems: Counter[str] = Counter()

        for index, descriptor in enumerate(descriptor_list):
            decision = decision_list[index] if index < len(decision_list) else None
            if decision and decision.primary_category:
                categories[str(decision.primary_category)] += 1

            mime_type = descriptor.mime_type or "unknown/unknown"
            mime_group = mime_type.split("/", 1)[0].lower()
            mime_groups[mime_group] += 1

            try:
                relative = descriptor.path.relative_to(root)
            except ValueError:
                relative = descriptor.path
            relative_path = Path(relative)
            parent = relative_path.parent
            if parent and str(parent) not in {"", "."}:
                parent_hints[parent.as_posix()] += 1
            duplicate_stems[relative_path.stem.lower()] += 1

        lines = [f"Total files: {total}"]

        if categories:
            formatted = StructurePlanner._format_counter(categories)
            if formatted:
                lines.append(f"Primary categories: {formatted}")
        elif mime_groups:
            formatted = StructurePlanner._format_counter(mime_groups)
            if formatted:
                lines.append(f"MIME families: {formatted}")

        if parent_hints:
            formatted = StructurePlanner._format_counter(parent_hints)
            if formatted:
                lines.append(f"Existing folders to reuse: {formatted}")

        duplicates = [stem for stem, count in duplicate_stems.items() if count > 1]
        if duplicates:
            preview = ", ".join(sorted(duplicates)[:5])
            lines.append(f"Duplicate file stems detected: {preview}")

        return "\n".join(lines)

    @staticmethod
    def _format_counter(counter: Counter[str], *, limit: int = 4) -> str:
        return ", ".join(f"{name} ({count})" for name, count in counter.most_common(limit))

    @staticmethod
    def _build_mapping(
        entries: Iterable[dict[str, object]],
        descriptors: List[FileDescriptor],
        root: Path,
    ) -> Dict[Path, Path]:
        mapping: Dict[Path, Path] = {}
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            source = entry.get("source")
            destination = entry.get("destination")
            if not isinstance(source, str) or not isinstance(destination, str):
                continue
            source_path = StructurePlanner._match_descriptor(source, descriptors, root)
            if source_path is None:
                continue
            destination_path = Path(destination.strip().lstrip("/\\"))
            if destination_path.parts:
                mapping[source_path] = destination_path
        return mapping

    @staticmethod
    def _detect_structure_issues(
        mapping: Dict[Path, Path],
        descriptors: List[FileDescriptor],
    ) -> Tuple[List[Path], List[Tuple[Path, Path]]]:
        missing = [descriptor.path for descriptor in descriptors if descriptor.path not in mapping]
        shallow: List[Tuple[Path, Path]] = []
        for source, destination in mapping.items():
            if len(destination.parts) < 2:
                shallow.append((source, destination))
        return missing, shallow

    @staticmethod
    def _build_violation_prompt(
        root: Path,
        missing: Iterable[Path],
        shallow: Iterable[Tuple[Path, Path]],
    ) -> str:
        lines: list[str] = []
        missing_list = [StructurePlanner._relative_path(path, root) for path in missing]
        if missing_list:
            lines.append(
                "Assign destinations for every file. These entries were missing: "
                + ", ".join(sorted(missing_list))
            )

        shallow_list = [
            f"{StructurePlanner._relative_path(src, root)} -> {dest.as_posix()}"
            for src, dest in shallow
        ]
        if shallow_list:
            lines.append(
                "Ensure at least two path segments per destination. Update these mappings: "
                + ", ".join(sorted(shallow_list))
            )

        lines.append(
            "Return JSON matching the required schema with every file represented exactly once."
        )
        return "\n".join(lines)

    @staticmethod
    def _normalize_mapping(
        mapping: Dict[Path, Path],
        descriptors: List[FileDescriptor],
        missing: Iterable[Path],
        shallow: Iterable[Tuple[Path, Path]],
        root: Path,
    ) -> Tuple[Dict[Path, Path], List[str]]:
        descriptor_map = {descriptor.path: descriptor for descriptor in descriptors}
        normalized = dict(mapping)
        notes: List[str] = []

        for missing_path in missing:
            descriptor = descriptor_map.get(missing_path)
            if descriptor is None:
                continue
            fallback = StructurePlanner._fallback_destination(descriptor)
            normalized[missing_path] = fallback
            notes.append(
                "Assigned fallback destination %s for %s"
                % (fallback.as_posix(), StructurePlanner._relative_path(missing_path, root))
            )

        for source, destination in shallow:
            descriptor = descriptor_map.get(source)
            if descriptor is None:
                continue
            fixed = StructurePlanner._ensure_nested_destination(destination, descriptor)
            if fixed != destination:
                normalized[source] = fixed
                notes.append(
                    "Nested destination enforced for %s -> %s"
                    % (StructurePlanner._relative_path(source, root), fixed.as_posix())
                )

        return normalized, notes

    @staticmethod
    def _fallback_destination(descriptor: FileDescriptor) -> Path:
        return _FALLBACK_PARENT / descriptor.path.name

    @staticmethod
    def _ensure_nested_destination(destination: Path, descriptor: FileDescriptor) -> Path:
        clean = Path(str(destination).strip().lstrip("/\\"))
        if len(clean.parts) >= 2:
            return clean

        filename = descriptor.path.name
        if not clean.parts:
            return _FALLBACK_PARENT / filename

        target = clean.parts[0]
        candidate = Path(target)
        if candidate.suffix or candidate.name == filename:
            return _FALLBACK_PARENT / candidate.name

        return candidate / filename

    @staticmethod
    def _relative_path(path: Path, root: Path) -> str:
        try:
            return path.relative_to(root).as_posix()
        except ValueError:
            return path.name

    @staticmethod
    def _merge_prompts(base: Optional[str], supplement: Optional[str]) -> Optional[str]:
        parts = []
        for value in (base, supplement):
            if value is None:
                continue
            stripped = value.strip()
            if stripped:
                parts.append(stripped)
        if not parts:
            return None
        return "\n\n".join(parts)

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
    def _compose_goal_prompt(summary: str, prompt: Optional[str]) -> str:
        """Return the LLM goal instructions including context and user guidance.

        Args:
            summary: Auto-generated collection context derived from descriptors.
            prompt: Optional user-provided instructions to append.

        Returns:
            Full prompt text supplied to the structure planner model.
        """

        sections = [_BASE_INSTRUCTIONS]
        summary_block = (summary or "").strip()
        if summary_block:
            sections.append(f"Collection context:\n{summary_block}")

        if prompt is not None:
            stripped = prompt.strip()
            if stripped:
                sections.append(f"User guidance:\n{stripped}")

        return "\n\n".join(sections)
