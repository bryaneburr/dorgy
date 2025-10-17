"""Test package for Dorgy."""

import os

# Enable heuristic classifier for the test suite unless explicitly overridden.
os.environ.setdefault("DORGY_USE_FALLBACK", "1")
