"""Grilli Type blog news crawler. Uses API /api/v1/blog/posts + single-post for dates."""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests

from src.crawlers.news.date_filter import filter_items_by_date_window
from src.crawlers.shared.dates import parse_dd_dot_mon_yyyy
from src.models import FontNewsItem


class GrilliTypeNewsCrawler:
    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontNewsItem]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = str(
            self.source_config.get("base_url", "https://www.grillitype.com")
        ).rstrip("/")
        crawl_cfg = self.source_config.get("crawl", {})
        posts_endpoint = str(
            crawl_cfg.get("posts_endpoint", "/api/v1/blog/posts")
        )
        max_items = int(crawl_cfg.get("max_items", 50))
        fetch_dates_for = int(crawl_cfg.get("fetch_dates_for", 50))

        posts_url = urljoin(base_url, posts_endpoint)
        detail_endpoint = "/api/v1/blogs"
        items: list[FontNewsItem] = []

        try:
            r = session.get(
                posts_url,
                params={"count": max_items},
                timeout=timeout,
                headers={"Accept": "application/json"},
            )
            r.raise_for_status()
            payload = r.json()
        except requests.RequestException:
            return items

        rows = payload.get("data") or []
        if not isinstance(rows, list):
            return items
        rows = rows[:max_items]

        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            name = str(row.get("name") or "").strip()
            slug = str(row.get("slug") or "").strip()
            category = str(row.get("category") or "").strip()
            if not slug:
                continue
            if not name:
                name = slug.replace("-", " ").title()

            post_url = urljoin(
                base_url, f"/blog/{category}/{slug}" if category else f"/blog/{slug}"
            )
            published_at = None

            if i < fetch_dates_for and category:
                detail_url = urljoin(base_url, f"{detail_endpoint}/{category}/{slug}")
                try:
                    dr = session.get(
                        detail_url,
                        timeout=timeout,
                        headers={"Accept": "application/json"},
                    )
                    dr.raise_for_status()
                    detail = dr.json()
                    meta = detail.get("meta") or {}
                    date_str = meta.get("date")
                    if date_str:
                        d = parse_dd_dot_mon_yyyy(date_str)
                        if d:
                            published_at = d.isoformat()
                    time.sleep(0.2)
                except requests.RequestException:
                    pass

            items.append(
                FontNewsItem(
                    source_id=source_id,
                    source_name=source_name,
                    title=name,
                    url=post_url,
                    published_at=published_at,
                    raw={
                        "category": category or row.get("category"),
                        "typeface": row.get("typeface"),
                        "image": row.get("image"),
                    },
                )
            )

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
