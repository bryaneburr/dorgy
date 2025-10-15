"""Exception hierarchy for state management operations."""


class StateError(Exception):
    """Base exception for state repository operations."""


class MissingStateError(StateError):
    """Raised when no state is available for a collection."""
