"""Dorgy CLI package exposing the Click command entry point."""

from __future__ import annotations

import click as _click

from .app import cli, main
from .lazy import _LAZY_ATTRS, __getattr__, _load_dependency

click = _click

__all__ = ["cli", "main", "_LAZY_ATTRS", "__getattr__", "_load_dependency", "click"]
