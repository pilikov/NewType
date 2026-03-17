"""
Watermarks for daily (incremental) news crawl runs.

Stored in state/news_daily_watermarks.json. Each source has last_run_utc and last_date
so the next daily run can restrict to [last_date, today] without full crawl.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.utils import dump_json, load_json


def get_news_watermarks_path(state_dir: Path) -> Path:
    return state_dir / "news_daily_watermarks.json"


def load_news_daily_watermarks(state_dir: Path) -> dict[str, dict[str, Any]]:
    """Load watermarks: { source_id: { "last_run_utc": "...", "last_date": "YYYY-MM-DD" } }."""
    path = get_news_watermarks_path(state_dir)
    data = load_json(path, default={})
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if isinstance(v, dict)}


def save_news_daily_watermarks(
    state_dir: Path, watermarks: dict[str, dict[str, Any]]
) -> None:
    path = get_news_watermarks_path(state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    dump_json(path, watermarks)


def get_news_source_watermark(
    watermarks: dict[str, dict[str, Any]],
    source_id: str,
) -> dict[str, Any]:
    """Return watermark for source (never None)."""
    return dict(watermarks.get(source_id) or {})


def update_news_source_watermark(
    watermarks: dict[str, dict[str, Any]],
    source_id: str,
    *,
    last_date: str | None = None,
) -> None:
    """Update in-place watermark for source after successful daily run."""
    now = datetime.now(timezone.utc)
    entry = watermarks.setdefault(source_id, {})
    entry["last_run_utc"] = now.isoformat().replace("+00:00", "Z")
    entry["last_date"] = last_date or now.date().isoformat()


def news_daily_start_end_dates(
    watermarks: dict[str, dict[str, Any]],
    source_id: str,
    *,
    fallback_days_back: int = 1,
) -> tuple[date, date]:
    """
    Return (start_date, end_date) for next daily run.
    end_date = today; start_date = last_date from watermark or (today - fallback_days_back).
    """
    today = date.today()
    w = get_news_source_watermark(watermarks, source_id)
    last = w.get("last_date")
    if last:
        try:
            start = datetime.strptime(last, "%Y-%m-%d").date()
            if start > today:
                start = today
            return start, today
        except ValueError:
            pass
    start = today - timedelta(days=fallback_days_back)
    return start, today
