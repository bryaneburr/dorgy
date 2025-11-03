"""Search-related helpers used by Dorgy CLI commands."""

from __future__ import annotations

import importlib
from typing import Any

import click


def _load_embedding_function(path: str | None) -> Any | None:
    """Import and return a Chromadb embedding function specified by path.

    Args:
        path: Dotted or module:path reference to the embedding callable.

    Returns:
        Any | None: Resolved callable or ``None`` when no path supplied.

    Raises:
        click.ClickException: If the module or attribute cannot be imported.
    """

    if not path:
        return None
    module_path: str
    attr_name: str
    if ":" in path:
        module_path, attr_name = path.split(":", 1)
    else:
        module_path, _, attr_name = path.rpartition(".")
    if not module_path or not attr_name:
        raise click.ClickException(
            "search.embedding_function must be formatted as 'package.module:callable' "
            "or 'package.module.callable'."
        )
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:  # pragma: no cover - defensive
        raise click.ClickException(
            f"Unable to import search embedding module '{module_path}': {exc}"
        ) from exc
    try:
        return getattr(module, attr_name)
    except AttributeError as exc:  # pragma: no cover - defensive
        raise click.ClickException(
            f"Embedding function '{attr_name}' not found in module '{module_path}'."
        ) from exc


__all__ = ["_load_embedding_function"]
