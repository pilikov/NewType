"""Dalton Maag blog news crawler. Parses blog index page."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.crawlers.news.date_filter import filter_items_by_date_window
from src.models import FontNewsItem

_DATE_IN_URL = re.compile(r"/(\d{4})-(\d{2})-(\d{2})-[^/]+\.html$")


class DaltonMaagNewsCrawler:
    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    def crawl(self, session, timeout: int = 20) -> list[FontNewsItem]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = str(self.source_config.get("base_url", "https://www.daltonmaag.com")).rstrip("/")
        news_url = str(
            self.source_config.get("news_url")
            or "https://www.daltonmaag.com/resources/blog/index.html"
        )

        items: list[FontNewsItem] = []
        try:
            r = session.get(news_url, timeout=timeout)
            r.raise_for_status()
            r.encoding = r.encoding or "utf-8"
        except requests.RequestException:
            return items

        soup = BeautifulSoup(r.text, "html.parser")
        seen: set[str] = set()

        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if "/resources/blog/" not in href or not href.endswith(".html"):
                continue
            if "index.html" in href:
                continue

            full_url = urljoin(base_url, href)
            if full_url in seen:
                continue
            seen.add(full_url)

            title = (a.get_text() or "").strip()
            if not title or len(title) < 5 or title.lower() in ("find out more", "read more"):
                parent = a.find_parent("div", class_=lambda c: c and "section-card" in str(c))
                if parent:
                    h2 = parent.find("h2")
                    if h2:
                        title = (h2.get_text() or "").strip()
            if not title or len(title) < 5:
                continue

            published_at = None
            m = _DATE_IN_URL.search(href) or _DATE_IN_URL.search(full_url)
            if m:
                published_at = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

            items.append(
                FontNewsItem(
                    source_id=source_id,
                    source_name=source_name,
                    title=title,
                    url=full_url,
                    published_at=published_at,
                    raw={},
                )
            )

        crawl_cfg = self.source_config.get("crawl", {})
        start_s, end_s = crawl_cfg.get("start_date"), crawl_cfg.get("end_date")
        if start_s and end_s:
            try:
                start_d = datetime.strptime(str(start_s)[:10], "%Y-%m-%d").date()
                end_d = datetime.strptime(str(end_s)[:10], "%Y-%m-%d").date()
                items = filter_items_by_date_window(items, start_d, end_d)
            except ValueError:
                pass

        return items
