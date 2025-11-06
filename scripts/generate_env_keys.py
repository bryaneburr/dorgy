"""Utility script to render environment variable keys for Dorgy defaults."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

import yaml

from dorgy.config.models import DorgyConfig


def _flatten(prefix: list[str], value: Any) -> Iterable[tuple[list[str], Any]]:
    """Yield flattened (path, value) pairs for nested configuration."""
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _flatten(prefix + [str(key)], child)
    else:
        yield prefix, value


def main() -> None:
    """Print environment variable keys with representative default values."""
    defaults = DorgyConfig().model_dump(mode="python")
    for path, value in _flatten([], defaults):
        env_key = "DORGY__" + "__".join(part.upper() for part in path)
        if isinstance(value, (dict, list)):
            rendered = yaml.safe_dump(value, default_flow_style=True).strip()
        elif value is None:
            rendered = "null"
        else:
            rendered = str(value)
        print(f"{env_key}={rendered}")


if __name__ == "__main__":
    main()
