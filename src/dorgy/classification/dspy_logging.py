"""Utilities for reducing noisy logging emitted by DSPy dependencies."""

from __future__ import annotations

import logging
from typing import ClassVar

_JSON_ADAPTER_LOGGER_NAME = "dspy.adapters.json_adapter"
_DSPY_STRUCTURED_WARNING_TOKEN = "Failed to use structured output format"


class _JsonAdapterFallbackFilter(logging.Filter):
    """Filter that suppresses redundant DSPy structured-output fallback warnings."""

    _token: ClassVar[str] = _DSPY_STRUCTURED_WARNING_TOKEN

    def filter(self, record: logging.LogRecord) -> bool:
        """Return ``False`` when the record matches the targeted DSPy warning."""

        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - defensive guard for logging internals
            return True
        return self._token not in message


_FILTER_INSTANCE: _JsonAdapterFallbackFilter | None = None


def configure_dspy_logging(*, suppress_json_adapter_warning: bool = True) -> None:
    """Apply runtime logging tweaks that keep DSPy console output tidy.

    Args:
        suppress_json_adapter_warning: When ``True``, removes the structured-output
            fallback warning emitted by ``dspy.adapters.json_adapter`` so dry runs do
            not surface redundant noise to CLI users.
    """

    global _FILTER_INSTANCE
    if not suppress_json_adapter_warning:
        return

    adapter_logger = logging.getLogger(_JSON_ADAPTER_LOGGER_NAME)
    if _FILTER_INSTANCE is None:
        _FILTER_INSTANCE = _JsonAdapterFallbackFilter()
    for existing in getattr(adapter_logger, "filters", []):
        if isinstance(existing, _JsonAdapterFallbackFilter):
            break
    else:
        adapter_logger.addFilter(_FILTER_INSTANCE)
