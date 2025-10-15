"""State management errors."""


class StateError(Exception):
    """Base exception for state repository operations."""


class MissingStateError(StateError):
    """Raised when no state is available for a collection."""
