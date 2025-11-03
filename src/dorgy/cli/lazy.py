"""Lazy import helpers for the Dorgy CLI package."""

from __future__ import annotations

import importlib
import sys
from typing import Any

_LAZY_ATTRS: dict[str, tuple[str, str]] = {
    "ClassificationCache": ("dorgy.classification", "ClassificationCache"),
    "VisionCache": ("dorgy.classification", "VisionCache"),
    "VisionCaptioner": ("dorgy.classification", "VisionCaptioner"),
    "LLMUnavailableError": (
        "dorgy.classification.exceptions",
        "LLMUnavailableError",
    ),
    "LLMResponseError": ("dorgy.classification.exceptions", "LLMResponseError"),
    "StructurePlanner": ("dorgy.classification.structure", "StructurePlanner"),
    "FileDescriptor": ("dorgy.ingestion", "FileDescriptor"),
    "IngestionPipeline": ("dorgy.ingestion", "IngestionPipeline"),
    "HashComputer": ("dorgy.ingestion.detectors", "HashComputer"),
    "TypeDetector": ("dorgy.ingestion.detectors", "TypeDetector"),
    "DirectoryScanner": ("dorgy.ingestion.discovery", "DirectoryScanner"),
    "MetadataExtractor": ("dorgy.ingestion.extractors", "MetadataExtractor"),
    "OperationExecutor": ("dorgy.organization.executor", "OperationExecutor"),
    "MoveOperation": ("dorgy.organization.models", "MoveOperation"),
    "OperationPlan": ("dorgy.organization.models", "OperationPlan"),
    "OrganizerPlanner": ("dorgy.organization.planner", "OrganizerPlanner"),
    "CollectionState": ("dorgy.state", "CollectionState"),
    "FileRecord": ("dorgy.state", "FileRecord"),
    "MissingStateError": ("dorgy.state", "MissingStateError"),
    "OperationEvent": ("dorgy.state", "OperationEvent"),
    "StateError": ("dorgy.state", "StateError"),
    "StateRepository": ("dorgy.state", "StateRepository"),
    "WatchBatchResult": ("dorgy.watch", "WatchBatchResult"),
    "WatchService": ("dorgy.watch", "WatchService"),
    "SearchEntry": ("dorgy.search", "SearchEntry"),
    "SearchIndex": ("dorgy.search", "SearchIndex"),
    "SearchIndexError": ("dorgy.search", "SearchIndexError"),
    "ensure_index": ("dorgy.search.lifecycle", "ensure_index"),
    "update_entries": ("dorgy.search.lifecycle", "update_entries"),
    "refresh_metadata": ("dorgy.search.lifecycle", "refresh_metadata"),
    "drop_index": ("dorgy.search.lifecycle", "drop_index"),
    "descriptor_document_text": (
        "dorgy.search.text",
        "descriptor_document_text",
    ),
}


def __getattr__(name: str) -> Any:
    """Fetch a lazily loaded dependency exported by the CLI package.

    Args:
        name: Attribute name requested from the CLI package.

    Returns:
        Any: The resolved attribute value from the registered module.

    Raises:
        AttributeError: If the attribute is not registered for lazy loading.
    """

    if name in _LAZY_ATTRS:
        module_name, attr_name = _LAZY_ATTRS[name]
        module = importlib.import_module(module_name)
        value = getattr(module, attr_name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _load_dependency(name: str, module: str, attr: str) -> Any:
    """Load a dependency while respecting monkeypatched globals.

    Args:
        name: Attribute name requested by the caller.
        module: Module path containing the attribute.
        attr: Attribute name within the module to retrieve.

    Returns:
        Any: The resolved attribute from the module.
    """

    package = sys.modules.get("dorgy.cli")
    if name in globals():
        cached = globals()[name]
        if package is not None and hasattr(package, name):
            candidate = getattr(package, name)
            if candidate is not cached:
                globals()[name] = candidate
                return candidate
        return cached
    if package is not None and hasattr(package, name):
        value = getattr(package, name)
        globals()[name] = value
        return value
    module_obj = importlib.import_module(module)
    value = getattr(module_obj, attr)
    globals()[name] = value
    if package is not None:
        setattr(package, name, value)
    return value


__all__ = ["_LAZY_ATTRS", "_load_dependency"]
