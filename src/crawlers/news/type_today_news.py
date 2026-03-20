"""Type.Today journal news crawler. Uses API /api/v1/posts."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from urllib.parse import urljoin

import requests

from src.crawlers.shared.dates import parse_ymd
from src.models import FontNewsItem


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    return parse_ymd(str(s).strip())


class TypeTodayNewsCrawler:
    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontNewsItem]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = str(self.source_config.get("base_url", "https://type.today"))
        crawl_cfg = self.source_config.get("crawl", {})
        posts_endpoint = str(crawl_cfg.get("posts_endpoint", "/api/v1/posts"))
        journal_path = str(crawl_cfg.get("journal_path", "/en/journal"))
        page_size = int(crawl_cfg.get("page_size", 100))
        lookback_days = int(crawl_cfg.get("lookback_days", 60))

        today = date.today()
        start_date = _parse_date(crawl_cfg.get("start_date"))
        end_date = _parse_date(crawl_cfg.get("end_date"))
        if start_date is not None and end_date is not None:
            cutoff = start_date
            max_date = end_date
        else:
            cutoff = today - timedelta(days=lookback_days)
            max_date = today

        posts_url = urljoin(base_url, posts_endpoint)
        items: list[FontNewsItem] = []
        page = 1
        max_pages = 10

        while page <= max_pages:
            try:
                r = session.get(
                    posts_url,
                    params={
                        "page[size]": page_size,
                        "page[number]": page,
                        "fields[posts]": "slug,title,date,preview_image",
                    },
                    timeout=timeout,
                )
                r.raise_for_status()
                payload = r.json()
            except requests.RequestException:
                break

            rows = payload.get("data") or []
            if not isinstance(rows, list):
                break

            for row in rows:
                if not isinstance(row, dict):
                    continue
                attrs = (row.get("attributes") or {})
                slug = str(attrs.get("slug") or "").strip()
                title = str(attrs.get("title") or "").strip()
                post_date = str(attrs.get("date") or "").strip()

                if not slug or not title:
                    continue

                post_day = parse_ymd(post_date)
                if post_day is None or post_day < cutoff:
                    continue
                if post_day > max_date:
                    continue

                # preview_image has nested sizes; prefer 420px for thumbnails.
                preview = attrs.get("preview_image") or {}
                image_url = (
                    (preview.get("preview_420") or {}).get("url")
                    or (preview.get("preview_320") or {}).get("url")
                    or (preview.get("preview") or {}).get("url")
                    or preview.get("url")
                    or None
                )

                post_url = urljoin(base_url, f"{journal_path}/{slug}")
                items.append(
                    FontNewsItem(
                        source_id=source_id,
                        source_name=source_name,
                        title=title,
                        url=post_url,
                        published_at=post_date,
                        image_url=image_url,
                        raw={"slug": slug, "post_date": post_date},
                    )
                )

            if len(rows) < page_size:
                break
            page += 1

        return items
