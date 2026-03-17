"""Fontstand news crawler. Parses news page, fetches article pages for dates."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.crawlers.news.date_extract import extract_published_at
from src.crawlers.news.date_filter import filter_items_by_date_window
from src.models import FontNewsItem


class FontstandNewsCrawler:
    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    def crawl(self, session, timeout: int = 20) -> list[FontNewsItem]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = str(self.source_config.get("base_url", "https://fontstand.com"))
        news_url = str(self.source_config.get("news_url", "https://fontstand.com/news"))
        date_fetch_limit = int(
            self.source_config.get("crawl", {}).get("date_fetch_limit", 10)
        )

        items: list[FontNewsItem] = []
        try:
            r = session.get(news_url, timeout=timeout)
            r.raise_for_status()
        except requests.RequestException:
            return items

        soup = BeautifulSoup(r.text, "html.parser")
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            if not href or "/news/" not in href or "/news/new-releases" in href:
                continue
            full_url = urljoin(base_url, href)
            if full_url in seen:
                continue
            # Skip section index pages (e.g. /news/design-news/, /news/essays/)
            path = href.split("?")[0].rstrip("/")
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 2 and parts[0] == "news" and len(parts) == 2:
                continue
            seen.add(full_url)
            title = (a.get_text() or "").strip()
            if not title or len(title) < 5:
                continue

            published_at = None
            if len(items) < date_fetch_limit:
                try:
                    ar = session.get(full_url, timeout=timeout)
                    ar.raise_for_status()
                    published_at = extract_published_at(ar.text, full_url)
                except requests.RequestException:
                    pass
                time.sleep(0.3)

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
            if len(items) >= 40:
                break

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
