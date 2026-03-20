"""It's Nice That news crawler. Uses /api/search?tags=Typography."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import requests

from src.crawlers.news.date_filter import filter_items_by_date_window
from src.models import FontNewsItem


class ItsNiceThatNewsCrawler:
    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontNewsItem]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = str(
            self.source_config.get("base_url", "https://www.itsnicethat.com")
        ).rstrip("/")
        crawl_cfg = self.source_config.get("crawl", {})
        tag = str(crawl_cfg.get("tag", "Typography"))
        max_pages = int(crawl_cfg.get("max_pages", 50))

        api_url = f"{base_url}/api/search"
        items: list[FontNewsItem] = []
        seen_urls: set[str] = set()

        for page in range(1, max_pages + 1):
            try:
                r = session.get(
                    api_url,
                    params={"tags": tag, "page": page},
                    timeout=timeout,
                    headers={"Accept": "application/json"},
                )
                r.raise_for_status()
                data = r.json()
            except requests.RequestException:
                break

            edges = (data.get("items") or {}).get("edges") or []
            if not edges:
                break

            for edge in edges:
                node = edge.get("node") or {}
                title = (node.get("title") or "").strip()
                url_path = (node.get("url") or "").strip()
                date_str = (node.get("publicationDate") or "").strip()

                if not title or not url_path:
                    continue

                full_url = f"{base_url}{url_path}" if url_path.startswith("/") else url_path
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)

                published_at = None
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str)
                        published_at = dt.strftime("%Y-%m-%d")
                    except (ValueError, TypeError):
                        pass

                img = node.get("listingImage") or {}
                image_url = img.get("src") or img.get("psrc") or None

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

            page_info = data.get("pageInfo") or {}
            if not page_info.get("hasNextPage", False):
                break

        start_s = crawl_cfg.get("start_date")
        end_s = crawl_cfg.get("end_date")
        if start_s and end_s:
            try:
                start_d = datetime.strptime(str(start_s)[:10], "%Y-%m-%d").date()
                end_d = datetime.strptime(str(end_s)[:10], "%Y-%m-%d").date()
                items = filter_items_by_date_window(items, start_d, end_d)
            except ValueError:
                pass

        return items
