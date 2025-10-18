"""Classification caching utilities.

This module provides a JSON-backed cache for classification decisions so that
expensive DSPy calls can be avoided on subsequent runs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from dorgy.classification.models import ClassificationDecision, VisionCaption


class ClassificationCache:
    """Persist classification decisions keyed by a deterministic identifier."""

    def __init__(self, path: Path) -> None:
        """Initialise the cache.

        Args:
            path: Location of the JSON cache file.
        """

        self._path = path
        self._data: Dict[str, Dict[str, Any]] = {}

    @property
    def path(self) -> Path:
        """Return the cache path."""

        return self._path

    def load(self) -> None:
        """Load cache contents from disk if available."""

        if not self._path.exists():
            self._data = {}
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self._data = {}
            return
        if isinstance(raw, dict):
            self._data = raw
        else:
            self._data = {}

    def save(self) -> None:
        """Persist cache contents to disk."""

        if not self._data:
            if self._path.exists():
                self._path.unlink()
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")

    def get(self, key: str) -> Optional[ClassificationDecision]:
        """Retrieve a cached decision.

        Args:
            key: Deterministic key for the file.

        Returns:
            Optional[ClassificationDecision]: Cached decision if present.
        """

        payload = self._data.get(key)
        if payload is None:
            return None
        return ClassificationDecision.model_validate(payload)

    def set(self, key: str, decision: ClassificationDecision) -> None:
        """Store a decision in the cache."""

        self._data[key] = decision.model_dump(mode="python")


class VisionCache:
    """Persist image captioning results keyed by a deterministic identifier."""

    def __init__(self, path: Path) -> None:
        """Initialise the cache.

        Args:
            path: Location of the JSON cache file.
        """

        self._path = path
        self._data: Dict[str, Dict[str, Any]] = {}

    @property
    def path(self) -> Path:
        """Return the cache path."""

        return self._path

    def load(self) -> None:
        """Load cache contents from disk if available."""

        if not self._path.exists():
            self._data = {}
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            self._data = {}
            return
        if isinstance(raw, dict):
            self._data = raw
        else:
            self._data = {}

    def save(self) -> None:
        """Persist cache contents to disk."""

        if not self._data:
            if self._path.exists():
                self._path.unlink()
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")

    def get(self, key: str) -> Optional[VisionCaption]:
        """Retrieve a cached captioning result."""

        payload = self._data.get(key)
        if payload is None:
            return None
        return VisionCaption.model_validate(payload)

    def set(self, key: str, caption: VisionCaption) -> None:
        """Store a captioning result in the cache."""

        self._data[key] = caption.model_dump(mode="python")
