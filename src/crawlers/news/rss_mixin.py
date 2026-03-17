"""Shared RSS parsing for news crawlers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import requests

from src.models import FontNewsItem


def _parse_rfc2822(value: str) -> datetime | None:
    if not value or not value.strip():
        return None
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(value.strip())
    except (ValueError, TypeError):
        return None


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _find_text(parent, local_name: str) -> str:
    for child in parent:
        if _strip_ns(child.tag) == local_name and child.text:
            return (child.text or "").strip()
    return ""


def _find_link(parent) -> str:
    import xml.etree.ElementTree as ET
    for child in parent:
        if _strip_ns(child.tag) == "link":
            href = child.get("href") or (child.text or "").strip()
            if href:
                return href
    return ""


def _resolve_url(link: str, base_url: str) -> str:
    from urllib.parse import urljoin
    if not link:
        return base_url
    if link.startswith("http://") or link.startswith("https://"):
        return link
    return urljoin(base_url, link)


def _parse_rss_items(xml_text: str, base_url: str) -> list[dict[str, Any]]:
    import xml.etree.ElementTree as ET
    items: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    for elem in root.iter():
        if _strip_ns(elem.tag) == "item":
            title = _find_text(elem, "title")
            link = _find_link(elem) or _find_text(elem, "link")
            pub_date = _find_text(elem, "pubDate")
            url = _resolve_url(link, base_url)
            items.append({"title": title, "url": url, "published_at": pub_date})
        elif _strip_ns(elem.tag) == "entry":
            title = _find_text(elem, "title")
            link = _find_link(elem)
            pub_date = _find_text(elem, "updated") or _find_text(elem, "published")
            url = _resolve_url(link, base_url)
            items.append({"title": title, "url": url, "published_at": pub_date})

    return items


def parse_rss_feed(
    session: requests.Session,
    timeout: int,
    rss_url: str,
    base_url: str,
    source_id: str,
    source_name: str,
    lookback_days: int = 1,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[FontNewsItem]:
    items: list[FontNewsItem] = []
    today = datetime.now().date()
    if start_date is not None and end_date is not None:
        cutoff = start_date
        max_date = end_date
    else:
        cutoff = today - timedelta(days=lookback_days)
        max_date = today

    try:
        r = session.get(rss_url, timeout=timeout, headers={"Accept": "application/xml, text/xml"})
        r.raise_for_status()
    except requests.RequestException:
        return items

    parsed = _parse_rss_items(r.text, base_url)
    for p in parsed:
        title = (p.get("title") or "").strip()
        url = (p.get("url") or "").strip()
        pub_str = (p.get("published_at") or "").strip()
        if not title or not url:
            continue

        dt = _parse_rfc2822(pub_str)
        if dt is None:
            try:
                dt = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            except ValueError:
                continue
        pub_date = dt.date()
        if pub_date < cutoff:
            continue
        if pub_date > max_date:
            continue

        items.append(
            FontNewsItem(
                source_id=source_id,
                source_name=source_name,
                title=title,
                url=url,
                published_at=pub_str or dt.isoformat(),
                raw={"rss_pub_date": pub_str},
            )
        )

    return items
