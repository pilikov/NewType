"""Emigre news crawler. Parses single-page News with anchors."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.crawlers.news.date_extract import _normalize_date
from src.crawlers.news.date_filter import filter_items_by_date_window
from src.models import FontNewsItem


class EmigreNewsCrawler:
    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    def crawl(self, session, timeout: int = 20) -> list[FontNewsItem]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = str(self.source_config.get("base_url", "https://www.emigre.com")).rstrip("/")
        news_url = str(self.source_config.get("news_url", "https://www.emigre.com/News"))

        items: list[FontNewsItem] = []
        try:
            r = session.get(news_url, timeout=timeout)
            r.raise_for_status()
            r.encoding = r.encoding or "utf-8"
        except requests.RequestException:
            return items

        soup = BeautifulSoup(r.text, "html.parser")

        for h2 in soup.select("h2.catalog-title"):
            a = h2.find("a", href=True)
            if not a:
                continue
            href = a.get("href", "").strip()
            if "News#" not in href and "News#" not in (a.get("href") or ""):
                continue

            title = (a.get_text() or "").strip()
            if not title or len(title) < 3:
                continue

            if title.lower() in ("about emigre", "general info", "contact us"):
                continue

            anchor = ""
            if "#" in href:
                anchor = href.split("#", 1)[1]
            full_url = f"{base_url}/News#{anchor}" if anchor else f"{base_url}/News"

            published_at = None
            for sib in h2.find_next_siblings():
                if sib.name == "h2":
                    break
                if sib.name == "p" and "margin-bottom-30" in str(sib.get("class", [])):
                    text = (sib.get_text() or "").strip()
                    if re.match(r"^(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}$", text, re.I):
                        published_at = _normalize_date(text)
                    break

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
