"""Option parsing helpers for the Dorgy CLI."""

from __future__ import annotations

from datetime import datetime

import click


def _parse_csv_option(raw: str | None) -> list[str]:
    """Convert a comma-separated option value into a list of strings.

    Args:
        raw: Raw comma-separated option value.

    Returns:
        list[str]: Trimmed option values.
    """

    if not raw:
        return []
    return [segment.strip() for segment in raw.split(",") if segment.strip()]


def _parse_datetime_option(option_name: str, raw: str | None) -> datetime | None:
    """Parse an ISO8601 datetime option value.

    Args:
        option_name: CLI flag name used for error reporting.
        raw: Raw datetime string supplied by the user.

    Returns:
        datetime | None: Parsed datetime or ``None`` when not provided.

    Raises:
        click.ClickException: If the value cannot be parsed.
    """

    if raw is None:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise click.ClickException(
            f"Invalid value for {option_name!r}; expected ISO 8601 timestamp"
        ) from exc


__all__ = ["_parse_csv_option", "_parse_datetime_option"]
