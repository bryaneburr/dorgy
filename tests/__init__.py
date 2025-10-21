"""Test package for Dorgy."""

import os

# Enable heuristic classifier for the test suite unless explicitly overridden.
os.environ.setdefault("DORGY_USE_FALLBACKS", "1")
