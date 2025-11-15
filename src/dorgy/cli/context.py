"""Shared runtime objects for the Dorgy CLI package."""

from __future__ import annotations

import logging

from rich.console import Console

console = Console(color_system=None, no_color=True)
"""Rich console singleton used by CLI commands for output without color."""

LOGGER = logging.getLogger("dorgy.cli")
"""Package-level logger for CLI diagnostics."""

__all__ = ["console", "LOGGER"]
