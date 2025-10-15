"""State management scaffolding for Dorgy."""

from __future__ import annotations

from pathlib import Path

from .models import CollectionState

DEFAULT_STATE_DIRNAME = ".dorgy"


class StateRepository:
    """Placeholder interface for reading and writing collection metadata."""

    def __init__(self, base_dirname: str = DEFAULT_STATE_DIRNAME) -> None:
        self._base_dirname = base_dirname

    @property
    def base_dirname(self) -> str:
        """Return the directory name used for collection metadata."""
        return self._base_dirname

    def load(self, root: Path) -> CollectionState:
        """Load collection state for the given root."""
        raise NotImplementedError("StateRepository.load will be implemented in Phase 2.")

    def save(self, root: Path, state: CollectionState) -> None:
        """Persist collection state for the given root."""
        raise NotImplementedError("StateRepository.save will be implemented in Phase 2.")

    def initialize(self, root: Path) -> Path:
        """Prepare the metadata directories for a tracked collection."""
        raise NotImplementedError("StateRepository.initialize will be implemented in Phase 2.")


__all__ = ["StateRepository", "DEFAULT_STATE_DIRNAME", "CollectionState"]
