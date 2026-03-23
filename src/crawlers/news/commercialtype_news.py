"""Commercial Type news crawler. Discovers articles via seed slugs and related links."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.crawlers.news.date_extract import extract_published_at
from src.crawlers.news.date_filter import filter_items_by_date_window
from src.crawlers.news.image_extract import extract_og_image
from src.models import FontNewsItem

_DEFAULT_SEED_SLUGS = [
    "2025_in_review",
    "delusse",
    "guided_licensing",
    "focal_maxi",
    "royal_gothics_staying_power",
    "double_acts",
]


class CommercialTypeNewsCrawler:
    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    def crawl(self, session, timeout: int = 20) -> list[FontNewsItem]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = str(
            self.source_config.get("base_url", "https://commercialtype.com")
        ).rstrip("/")
        crawl_cfg = self.source_config.get("crawl", {})
        seed_slugs = crawl_cfg.get("seed_slugs") or _DEFAULT_SEED_SLUGS
        max_items = int(crawl_cfg.get("max_items", 25))
        discover_more = crawl_cfg.get("discover_more", True)

        items: list[FontNewsItem] = []
        seen_slugs: set[str] = set()
        to_visit = list(seed_slugs)

        while to_visit and len(items) < max_items:
            slug = to_visit.pop(0).strip()
            if not slug or slug in seen_slugs:
                continue
            seen_slugs.add(slug)
            full_url = f"{base_url}/news/{slug}"

            try:
                r = session.get(full_url, timeout=timeout)
                r.raise_for_status()
            except requests.RequestException:
                continue

            soup = BeautifulSoup(r.text, "html.parser")
            title = None
            if soup.find("title"):
                raw = (soup.find("title").get_text() or "").strip()
                if "»" in raw:
                    title = raw.split("»")[-1].strip()
                else:
                    title = raw
            if not title or len(title) < 3:
                title = slug.replace("_", " ").title()

            published_at = extract_published_at(r.text, full_url)
            image_url = extract_og_image(r.text, full_url)

            items.append(
                FontNewsItem(
                    source_id=source_id,
                    source_name=source_name,
                    title=title,
                    url=full_url,
                    published_at=published_at,
                    image_url=image_url,
                    raw={},
                )
            )

            if discover_more:
                for a in soup.find_all("a", href=True):
                    href = a.get("href", "").strip()
                    if "/news/" not in href or href == "/news":
                        continue
                    path = href.split("/news/")[-1].split("/")[0].split("?")[0]
                    if path and len(path) > 2 and path not in seen_slugs:
                        to_visit.append(path)

            time.sleep(0.25)

        start_s, end_s = crawl_cfg.get("start_date"), crawl_cfg.get("end_date")
        if start_s and end_s:
            try:
                start_d = datetime.strptime(str(start_s)[:10], "%Y-%m-%d").date()
                end_d = datetime.strptime(str(end_s)[:10], "%Y-%m-%d").date()
                items = filter_items_by_date_window(items, start_d, end_d)
            except ValueError:
                pass

        return items
