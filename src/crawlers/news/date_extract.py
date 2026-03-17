"""Extract published date from article page HTML."""

from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup


def extract_published_at(html: str, url: str = "") -> str | None:
    """Extract publication date from article page. Returns ISO string or None."""
    soup = BeautifulSoup(html, "html.parser")

    # meta article:published_time
    meta = soup.find("meta", attrs={"property": "article:published_time"})
    if meta and meta.get("content"):
        return _normalize_date(meta["content"])

    meta = soup.find("meta", attrs={"name": "article:published_time"})
    if meta and meta.get("content"):
        return _normalize_date(meta["content"])

    meta = soup.find("meta", attrs={"property": "og:published_time"})
    if meta and meta.get("content"):
        return _normalize_date(meta["content"])

    # time datetime
    time_el = soup.find("time", attrs={"datetime": True})
    if time_el and time_el.get("datetime"):
        return _normalize_date(time_el["datetime"])

    # data-published, data-date
    for el in soup.find_all(attrs={"data-published": True}):
        val = el.get("data-published")
        if val:
            return _normalize_date(val)
    for el in soup.find_all(attrs={"data-date": True}):
        val = el.get("data-date")
        if val:
            return _normalize_date(val)

    # div.date, time without datetime (Bold Monday: "30 Nov 2025")
    for sel in ("div.date", "time"):
        el = soup.select_one(sel)
        if el and el.get_text(strip=True):
            return _normalize_date(el.get_text(strip=True))

    # div.byline (Commercial Type: "January 22 (Thursday)")
    byline = soup.select_one("div.byline")
    if byline and byline.get_text(strip=True):
        return _normalize_date(byline.get_text(strip=True), url=url)

    return None


_MONTH_ABBREV = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _normalize_date(value: str, url: str = "") -> str | None:
    """Return ISO datetime string for display, or YYYY-MM-DD for date-only."""
    if not value or not value.strip():
        return None
    val = value.strip()
    try:
        dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    try:
        dt = parsedate_to_datetime(val)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", val)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # "30 Nov 2025", "15 Jul 2025". Bold Monday, Fontstand
    m = re.search(r"(\d{1,2})\s+(\w{3})\s+(\d{4})", val)
    if m:
        day, mon, year = m.groups()
        month_num = _MONTH_ABBREV.get(mon.lower())
        if month_num is not None:
            return f"{year}-{month_num:02d}-{int(day):02d}"
    # "February 3, 2026", "December 4, 2025". Emigre
    m = re.search(r"(\w+)\s+(\d{1,2}),?\s+(\d{4})", val)
    if m:
        mon, day, year = m.groups()
        month_num = _MONTH_ABBREV.get(mon.lower()[:3])
        if month_num is not None:
            return f"{year}-{month_num:02d}-{int(day):02d}"
    # "January 22 (Thursday)" - Commercial Type, year from weekday
    m = re.search(r"(\w+)\s+(\d{1,2})\s*\(([^)]+)\)", val)
    if m:
        mon, day, weekday = m.groups()
        month_num = _MONTH_ABBREV.get(mon.lower()[:3])
        if month_num is not None:
            year = _year_from_weekday(int(day), month_num, weekday)
            if year:
                return f"{year}-{month_num:02d}-{int(day):02d}"
    # "January 22" without weekday - try recent years
    m = re.search(r"(\w+)\s+(\d{1,2})(?:\s*\([^)]+\))?", val)
    if m:
        mon, day = m.groups()
        month_num = _MONTH_ABBREV.get(mon.lower()[:3])
        if month_num is not None:
            year = datetime.now().year
            return f"{year}-{month_num:02d}-{int(day):02d}"
    return None


def _year_from_weekday(day: int, month: int, weekday_str: str) -> int | None:
    """Resolve year from 'Month DD (Weekday)' - e.g. Jan 22 (Thursday) -> 2026."""
    weekday_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    target_wd = weekday_map.get(weekday_str.strip().lower())
    if target_wd is None:
        return None
    for year in range(datetime.now().year, datetime.now().year - 3, -1):
        try:
            dt = datetime(year, month, day)
            if dt.weekday() == target_wd:
                return year
        except ValueError:
            continue
    return None
