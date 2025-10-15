"""Configuration resolution helpers for Phase 1."""

from __future__ import annotations

from typing import Any, Dict, Mapping

from .models import DorgyConfig


def resolve_with_precedence(
    *,
    defaults: DorgyConfig,
    file_overrides: Mapping[str, Any] | None = None,
    env_overrides: Mapping[str, str] | None = None,
    cli_overrides: Mapping[str, Any] | None = None,
) -> DorgyConfig:
    """Merge configuration sources according to the precedence defined in SPEC.md."""
    raise NotImplementedError("resolve_with_precedence will be implemented during Phase 1.")


def flatten_for_env(config: DorgyConfig) -> Dict[str, str]:
    """Flatten the config into `DORGY__SECTION__KEY` environment variable mappings."""
    raise NotImplementedError("flatten_for_env will be implemented during Phase 1.")


__all__ = ["resolve_with_precedence", "flatten_for_env"]
