"""Adobe Fonts blog news crawler. Uses sitemap (RSS feed is stale since 2022)."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any
from xml.etree import ElementTree as ET

import requests

from src.models import FontNewsItem

_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
_URL_DATE = re.compile(r"/publish/\d{4}/(\d{2})/(\d{2})/")
_FONT_KEYWORDS = re.compile(
    r"\b(font|fonts|typography|typeface|type)\b",
    re.I,
)


def _parse_ymd(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(str(s).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _slug_to_title(slug: str) -> str:
    """Convert URL slug to readable title."""
    return slug.replace("-", " ").title()


def _parse_sitemap_items(xml_text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items

    for url_el in root.iter():
        tag = url_el.tag.split("}")[-1] if "}" in url_el.tag else url_el.tag
        if tag != "url":
            continue
        loc = None
        lastmod = None
        for child in url_el:
            ctag = child.tag.split("}")[-1] if "}" in child.tag else child.tag
            if ctag == "loc" and child.text:
                loc = child.text.strip()
            elif ctag == "lastmod" and child.text:
                lastmod = child.text.strip()
        if loc and "/publish/" in loc:
            items.append({"url": loc, "lastmod": lastmod})
    return items


class AdobeNewsCrawler:
    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    def crawl(self, session, timeout: int = 20) -> list[FontNewsItem]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        crawl_cfg = self.source_config.get("crawl", {})
        sitemap_url = str(
            crawl_cfg.get("sitemap_url", "https://blog.adobe.com/en/sitemap.xml")
        )
        lookback_days = int(crawl_cfg.get("lookback_days", 365))
        font_only = crawl_cfg.get("font_only", True)

        items: list[FontNewsItem] = []
        today = datetime.now().date()
        start_date = _parse_ymd(crawl_cfg.get("start_date"))
        end_date = _parse_ymd(crawl_cfg.get("end_date"))
        if start_date is not None and end_date is not None:
            cutoff = start_date
            max_date = end_date
        else:
            cutoff = today - timedelta(days=lookback_days)
            max_date = today

        try:
            r = session.get(
                sitemap_url,
                timeout=timeout,
                headers={"Accept": "application/xml, text/xml"},
            )
            r.raise_for_status()
        except requests.RequestException:
            return items

        parsed = _parse_sitemap_items(r.text)
        for p in parsed:
            url = (p.get("url") or "").strip()
            if not url or "/publish/" not in url:
                continue

            m = _URL_DATE.search(url)
            if not m:
                continue
            month, day = int(m.group(1)), int(m.group(2))
            year = int(url.split("/publish/")[1][:4])
            try:
                pub_date = datetime(year, month, day).date()
            except ValueError:
                continue
            if pub_date < cutoff:
                continue
            if pub_date > max_date:
                continue

            slug = url.rstrip("/").split("/")[-1] or ""
            if font_only and not _FONT_KEYWORDS.search(slug):
                continue

            title = _slug_to_title(slug)
            items.append(
                FontNewsItem(
                    source_id=source_id,
                    source_name=source_name,
                    title=title,
                    url=url,
                    published_at=pub_date.isoformat(),
                    raw={"sitemap_lastmod": p.get("lastmod")},
                )
            )

        return items
