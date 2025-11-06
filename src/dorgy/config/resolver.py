"""Configuration resolution helpers."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC
from typing import Any, Dict, Mapping

import yaml
from durango.sources.user import deep_merge_dicts
from pydantic import ValidationError

from .exceptions import ConfigError
from .models import DorgyConfig


def resolve_with_precedence(
    *,
    defaults: DorgyConfig,
    file_overrides: Mapping[str, Any] | None = None,
    env_overrides: Mapping[str, Any] | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
) -> DorgyConfig:
    """Merge configuration inputs into a validated config object.

    Args:
        defaults: Fully-populated configuration defaults.
        file_overrides: Overrides loaded from the configuration file.
        env_overrides: Mapping of environment variable-derived overrides.
        cli_overrides: Overrides supplied via the CLI layer.

    Returns:
        DorgyConfig: The merged and validated configuration model.

    Raises:
        ConfigError: If merged values fail validation.
    """
    baseline = defaults.model_dump(mode="python")

    merged = dict(baseline)
    for name, source in (
        ("file", file_overrides),
        ("environment", env_overrides),
        ("cli", cli_overrides),
    ):
        if source is None:
            continue
        overrides = normalize_override_mapping(source, source_name=name)
        merged = deep_merge_dicts(merged, overrides)

    try:
        return DorgyConfig.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration values: {exc}") from exc


def flatten_for_env(config: DorgyConfig) -> Dict[str, str]:
    """Render configuration into `DORGY__SECTION__KEY` environment variables.

    Args:
        config: The configuration model to flatten.

    Returns:
        Dict[str, str]: Mapping of environment variable names to serialized values.
    """
    flat: Dict[str, str] = {}
    data = config.model_dump(mode="python")

    def _recurse(prefix: list[str], value: Any) -> None:
        """Populate the flattened mapping for a nested value."""
        if isinstance(value, dict):
            for key, child in value.items():
                _recurse(prefix + [str(key)], child)
        else:
            env_key = "DORGY__" + "__".join(part.upper() for part in prefix)
            if isinstance(value, (dict, list)):
                rendered = yaml.safe_dump(value, default_flow_style=True).strip()
            else:
                rendered = "null" if value is None else str(value)
            flat[env_key] = rendered

    for top_key, child_value in data.items():
        _recurse([str(top_key)], child_value)

    return flat


def normalize_override_mapping(source: Mapping[str, Any], *, source_name: str) -> dict[str, Any]:
    """Normalize overrides expressed through dotted keys into nested mappings.

    Args:
        source: Raw override mapping to normalize.
        source_name: Human-readable label for the override source.

    Returns:
        dict[str, Any]: Nested mapping representing the overrides.

    Raises:
        ConfigError: If keys are not strings or values conflict structurally.
    """
    if not isinstance(source, MappingABC):
        raise ConfigError(f"{source_name.capitalize()} overrides must be a mapping.")

    result: dict[str, Any] = {}
    for key, value in dict(source).items():
        if not isinstance(key, str):
            raise ConfigError(f"{source_name.capitalize()} override keys must be strings.")
        path = key.split(".") if "." in key else [key]
        _assign(result, path, value, source_name=source_name)
    return result


def _assign(target: dict[str, Any], path: list[str], value: Any, *, source_name: str) -> None:
    """Assign a value within a nested mapping, creating intermediate dictionaries.

    Args:
        target: Mapping to mutate.
        path: Sequence of keys describing the nested location.
        value: Value to assign at the nested location.
        source_name: Origin label for error reporting.

    Raises:
        ConfigError: If the assignment collides with a non-mapping value.
    """
    node = target
    for segment in path[:-1]:
        existing = node.get(segment)
        if existing is None:
            existing = {}
            node[segment] = existing
        elif not isinstance(existing, dict):
            joined = ".".join(path)
            raise ConfigError(
                f"{source_name.capitalize()} override for {joined} conflicts with existing value."
            )
        node = existing
    leaf = path[-1]
    if isinstance(value, MappingABC):
        nested = normalize_override_mapping(value, source_name=source_name)
        existing_leaf = node.get(leaf, {})
        if not isinstance(existing_leaf, MappingABC):
            existing_leaf = {}
        node[leaf] = deep_merge_dicts(existing_leaf, nested)
    else:
        node[leaf] = value


__all__ = ["resolve_with_precedence", "flatten_for_env", "normalize_override_mapping"]
