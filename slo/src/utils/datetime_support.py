"""Datetime helpers shared across the app."""

from datetime import datetime, timezone


def now_utc() -> datetime:
    """Current UTC datetime, timezone-aware."""
    return datetime.now(tz=timezone.utc)


def utc_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return now_utc().isoformat()
