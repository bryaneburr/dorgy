"""Classification engine built on top of DSPy.

This module exposes a thin wrapper around DSPy programs so the rest of the
codebase can request classifications without depending directly on DSPy.
"""

from __future__ import annotations

from typing import Iterable

try:  # pragma: no cover - optional dependency
    import dspy  # type: ignore
except ImportError:  # pragma: no cover - executed when DSPy absent
    dspy = None

from .models import ClassificationBatch, ClassificationRequest


class ClassificationEngine:
    """Apply DSPy programs to classify and rename files.

    Raises:
        RuntimeError: If DSPy is not installed in the current environment.
    """

    def __init__(self) -> None:
        if dspy is None:
            raise RuntimeError(
                "DSPy is not installed; install `dspy` to enable classification features."
            )
        self._program = self._build_program()

    def classify(self, requests: Iterable[ClassificationRequest]) -> ClassificationBatch:
        """Run the DSPy program for each request.

        Args:
            requests: Iterable of classification requests to evaluate.

        Returns:
            ClassificationBatch: Aggregated decisions and errors.
        """
        raise NotImplementedError("ClassificationEngine.classify will be implemented in Phase 3.")

    def _build_program(self):
        """Construct the DSPy program used for classification.

        Returns:
            Any: DSPy program object that can be executed for classification.
        """
        raise NotImplementedError("ClassificationEngine._build_program will be implemented in Phase 3.")
