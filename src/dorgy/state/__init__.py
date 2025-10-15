"""State management for Dorgy."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .errors import MissingStateError, StateError
from .models import CollectionState

DEFAULT_STATE_DIRNAME = ".dorgy"


class StateRepository:
    """Manage the persistence of collection metadata."""

    def __init__(self, base_dirname: str = DEFAULT_STATE_DIRNAME) -> None:
        self._base_dirname = base_dirname

    @property
    def base_dirname(self) -> str:
        """Return the directory name used for collection metadata."""
        return self._base_dirname

    def load(self, root: Path) -> CollectionState:
        """Load collection state for the given root."""
        directory = self._state_dir(root)
        state_path = directory / "state.json"
        if not state_path.exists():
            raise MissingStateError(f"No collection state found at {state_path}")

        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StateError(f"Invalid collection state data: {exc}") from exc

        return CollectionState.model_validate(data)

    def save(self, root: Path, state: CollectionState) -> None:
        """Persist collection state for the given root."""
        directory = self.initialize(root)
        now = datetime.now(timezone.utc)
        state.updated_at = now
        if state.created_at.tzinfo is None:
            state.created_at = state.created_at.replace(tzinfo=timezone.utc)
        payload = state.model_dump(mode="json")
        (directory / "state.json").write_text(
            json.dumps(payload, indent=2, sort_keys=False), encoding="utf-8"
        )
        (directory / "dorgy.log").touch(exist_ok=True)

    def initialize(self, root: Path) -> Path:
        """Prepare the metadata directories for a tracked collection."""
        directory = self._state_dir(root)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "needs-review").mkdir(exist_ok=True)
        (directory / "quarantine").mkdir(exist_ok=True)
        (directory / "orig.json").touch(exist_ok=True)
        return directory

    def write_original_structure(self, root: Path, tree: dict[str, Any]) -> None:
        """Persist the original structure snapshot for undo operations."""
        directory = self.initialize(root)
        (directory / "orig.json").write_text(json.dumps(tree, indent=2), encoding="utf-8")

    def load_original_structure(self, root: Path) -> dict[str, Any] | None:
        """Load the original structure snapshot if present."""
        path = self._state_dir(root) / "orig.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise StateError(f"Invalid orig.json data: {exc}") from exc

    def _state_dir(self, root: Path) -> Path:
        return root / self._base_dirname


__all__ = [
    "StateRepository",
    "DEFAULT_STATE_DIRNAME",
    "CollectionState",
    "StateError",
    "MissingStateError",
]
