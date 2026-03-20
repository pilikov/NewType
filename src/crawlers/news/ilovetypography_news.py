"""I Love Typography news crawler. Uses paginated RSS feed."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any

import requests

from src.crawlers.news.date_filter import filter_items_by_date_window
from src.models import FontNewsItem


def _strip_ns(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


class ILoveTypographyNewsCrawler:
    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontNewsItem]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = str(
            self.source_config.get("base_url", "https://ilovetypography.com")
        ).rstrip("/")
        crawl_cfg = self.source_config.get("crawl", {})
        rss_path = str(crawl_cfg.get("rss_path", "/feed/"))
        max_pages = int(crawl_cfg.get("max_pages", 100))
        lookback_days = int(crawl_cfg.get("lookback_days", 60))

        today = date.today()
        start_s = crawl_cfg.get("start_date")
        end_s = crawl_cfg.get("end_date")
        if start_s and end_s:
            try:
                cutoff = datetime.strptime(str(start_s)[:10], "%Y-%m-%d").date()
                max_date = datetime.strptime(str(end_s)[:10], "%Y-%m-%d").date()
            except ValueError:
                cutoff = today - timedelta(days=lookback_days)
                max_date = today
        else:
            cutoff = today - timedelta(days=lookback_days)
            max_date = today

        rss_base = f"{base_url}{rss_path}"
        items: list[FontNewsItem] = []
        seen_urls: set[str] = set()
        stop = False

        for page in range(1, max_pages + 1):
            url = rss_base if page == 1 else f"{rss_base}?paged={page}"
            try:
                r = session.get(
                    url,
                    timeout=timeout,
                    headers={"Accept": "application/xml, text/xml"},
                )
                if r.status_code == 404:
                    break
                r.raise_for_status()
            except requests.RequestException:
                break

            try:
                root = ET.fromstring(r.text)
            except ET.ParseError:
                break

            page_items = 0
            for elem in root.iter():
                if _strip_ns(elem.tag) != "item":
                    continue
                page_items += 1

                title = ""
                link = ""
                pub_date_str = ""
                category = ""

                for child in elem:
                    tag = _strip_ns(child.tag)
                    text = (child.text or "").strip()
                    if tag == "title":
                        title = text
                    elif tag == "link":
                        link = text
                    elif tag == "pubDate":
                        pub_date_str = text
                    elif tag == "category" and not category:
                        category = text

                if not title or not link:
                    continue
                if link in seen_urls:
                    continue
                seen_urls.add(link)

                pub_date = _parse_rfc2822_date(pub_date_str)
                if pub_date is None:
                    continue
                if pub_date < cutoff:
                    stop = True
                    continue
                if pub_date > max_date:
                    continue

                items.append(
                    FontNewsItem(
                        source_id=source_id,
                        source_name=source_name,
                        title=title,
                        url=link,
                        published_at=pub_date.isoformat(),
                        image_url=None,
                        raw={"category": category} if category else {},
                    )
                )

            if page_items == 0 or stop:
                break

        return items


def _parse_rfc2822_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date()
    except (ValueError, TypeError):
        return None
