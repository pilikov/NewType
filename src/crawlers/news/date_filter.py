"""Date window filter for daily news crawlers."""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.models import FontNewsItem


def parse_published_date(value: str | None) -> date | None:
    """Parse published_at string to date. Handles YYYY-MM-DD and ISO datetime."""
    if not value or not str(value).strip():
        return None
    s = str(value).strip()
    if len(s) >= 10:
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def filter_items_by_date_window(
    items: list[FontNewsItem],
    start_date: date,
    end_date: date,
    *,
    include_undated: bool = True,
) -> list[FontNewsItem]:
    """
    Filter items by published_at in [start_date, end_date].
    If include_undated=True, items without published_at are kept (conservative).
    """
    result: list[FontNewsItem] = []
    for item in items:
        pub = parse_published_date(item.published_at)
        if pub is None:
            if include_undated:
                result.append(item)
            continue
        if start_date <= pub <= end_date:
            result.append(item)
    return result
