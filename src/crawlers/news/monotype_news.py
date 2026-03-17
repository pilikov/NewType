"""Monotype news crawler. Parses news-press from company/news-press."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.crawlers.news.date_filter import filter_items_by_date_window
from src.models import FontNewsItem


class MonotypeNewsCrawler:
    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    def crawl(self, session, timeout: int = 20) -> list[FontNewsItem]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = str(self.source_config.get("base_url", "https://www.monotype.com"))
        news_url = str(
            self.source_config.get("news_url")
            or self.source_config.get("crawl", {}).get("news_url")
            or "https://www.monotype.com/company/news-press"
        )
        item_limit = int(
            self.source_config.get("crawl", {}).get("item_limit", 40)
        )

        items: list[FontNewsItem] = []
        try:
            r = session.get(news_url, timeout=timeout)
            r.raise_for_status()
        except requests.RequestException:
            return items

        soup = BeautifulSoup(r.text, "html.parser")
        seen_urls: set[str] = set()

        for wrapper in soup.find_all("div", class_="news-and-event-wrapper"):
            if len(items) >= item_limit:
                break

            title_el = wrapper.find("div", class_="news-and-event-title")
            if not title_el:
                continue
            a = title_el.find("a", href=True)
            if not a:
                continue

            href = a.get("href", "").strip()
            if not href or "/company/news-press" in href:
                continue
            if "/company/thought-leadership/" not in href and "/company/press-release/" not in href and "/company/spotlights/" not in href and "/company/news/" not in href:
                continue

            full_url = urljoin(base_url, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            title = (a.get_text() or "").strip()
            if not title or len(title) < 5:
                continue

            published_at = None
            date_el = wrapper.find("div", class_="news-and-event-date")
            if date_el:
                time_el = date_el.find("time", attrs={"datetime": True})
                if time_el and time_el.get("datetime"):
                    dt_str = time_el["datetime"]
                    if dt_str:
                        try:
                            dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                            published_at = dt.strftime("%Y-%m-%d")
                        except (ValueError, TypeError):
                            pass

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
