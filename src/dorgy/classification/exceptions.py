"""Custom exceptions for classification and LLM integrations."""

from __future__ import annotations


class LLMUnavailableError(RuntimeError):
    """Raised when the language model layer is unavailable or misconfigured."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class LLMResponseError(RuntimeError):
    """Raised when the language model returns an invalid or unusable response."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
