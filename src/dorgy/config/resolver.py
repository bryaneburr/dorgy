"""Configuration resolution helpers."""

from __future__ import annotations

from collections.abc import Mapping as MappingABC
from copy import deepcopy
from typing import Any, Dict, Mapping

import yaml
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
    """Merge configuration sources according to the precedence defined in SPEC.md."""
    baseline = defaults.model_dump(mode="python")

    merged = deepcopy(baseline)
    for name, source in (
        ("file", file_overrides),
        ("environment", env_overrides),
        ("cli", cli_overrides),
    ):
        if source is None:
            continue
        overrides = _normalize_mapping(source, source_name=name)
        merged = _deep_merge(merged, overrides)

    try:
        return DorgyConfig.model_validate(merged)
    except ValidationError as exc:
        raise ConfigError(f"Invalid configuration values: {exc}") from exc


def flatten_for_env(config: DorgyConfig) -> Dict[str, str]:
    """Flatten the config into `DORGY__SECTION__KEY` environment variable mappings."""
    flat: Dict[str, str] = {}
    data = config.model_dump(mode="python")

    def _recurse(prefix: list[str], value: Any) -> None:
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


def _normalize_mapping(source: Mapping[str, Any], *, source_name: str) -> dict[str, Any]:
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
        nested = _normalize_mapping(value, source_name=source_name)
        existing_leaf = node.get(leaf, {})
        if not isinstance(existing_leaf, MappingABC):
            existing_leaf = {}
        node[leaf] = _deep_merge(existing_leaf, nested)
    else:
        node[leaf] = value


def _deep_merge(base: Mapping[str, Any], overrides: Mapping[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key, value in base.items():
        merged[key] = deepcopy(value)
    for key, value in overrides.items():
        if isinstance(value, MappingABC) and isinstance(merged.get(key), MappingABC):
            merged[key] = _deep_merge(dict(merged[key]), value)  # type: ignore[arg-type]
        else:
            merged[key] = deepcopy(value)
    return merged


__all__ = ["resolve_with_precedence", "flatten_for_env"]
