from __future__ import annotations

from datetime import date, datetime


def parse_ymd(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_iso_day(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_mon_dd_yyyy(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%b %d, %Y").date()
    except ValueError:
        return None


def parse_dd_dot_mon_yyyy(value: str | None) -> date | None:
    """Parse '11. Mar 2026' (Grilli Type format)."""
    if not value:
        return None
    s = (value or "").strip()
    if not s:
        return None
    try:
        return datetime.strptime(s, "%d. %b %Y").date()
    except ValueError:
        return None
