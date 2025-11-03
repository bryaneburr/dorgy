"""Configuration helper utilities for the Dorgy CLI."""

from __future__ import annotations

from typing import Any

from dorgy.config import ConfigError


def _assign_nested(target: dict[str, Any], path: list[str], value: Any) -> None:
    """Assign a nested value within a dictionary for a dotted path.

    Args:
        target: Mapping to mutate in place.
        path: Path segments leading to the desired nested key.
        value: Value to assign at the nested location.

    Raises:
        ConfigError: If the path traverses a non-mapping value.
    """

    node = target
    for segment in path[:-1]:
        existing = node.get(segment)
        if existing is None:
            existing = {}
            node[segment] = existing
        elif not isinstance(existing, dict):
            raise ConfigError(
                f"Cannot assign into '{segment}' because it is not a mapping in the config file."
            )
        node = existing
    node[path[-1]] = value


__all__ = ["_assign_nested"]
