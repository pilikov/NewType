"""Print Magazine news crawler. Uses WordPress REST API with category filter."""

from __future__ import annotations

import html as html_mod
import re
from datetime import datetime
from typing import Any

import requests

from src.crawlers.news.date_filter import filter_items_by_date_window
from src.models import FontNewsItem


class PrintMagNewsCrawler:
    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontNewsItem]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = str(
            self.source_config.get("base_url", "https://www.printmag.com")
        ).rstrip("/")
        crawl_cfg = self.source_config.get("crawl", {})
        per_page = int(crawl_cfg.get("per_page", 100))
        max_pages = int(crawl_cfg.get("max_pages", 10))
        categories = str(crawl_cfg.get("categories", "40"))  # 40 = Typography

        api_url = f"{base_url}/wp-json/wp/v2/posts"
        items: list[FontNewsItem] = []
        page = 1

        while page <= max_pages:
            params: dict[str, Any] = {
                "per_page": per_page,
                "page": page,
                "_embed": "",
            }
            if categories:
                params["categories"] = categories

            try:
                r = session.get(api_url, params=params, timeout=timeout)
                if r.status_code == 400:
                    break
                r.raise_for_status()
                posts = r.json()
            except requests.RequestException:
                break

            if not isinstance(posts, list) or not posts:
                break

            for post in posts:
                if not isinstance(post, dict):
                    continue

                raw_title = (post.get("title") or {}).get("rendered", "").strip()
                title = html_mod.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()
                link = (post.get("link") or "").strip()
                date_str = (post.get("date") or "").strip()

                if not title or not link:
                    continue

                published_at = None
                if date_str:
                    try:
                        dt = datetime.fromisoformat(date_str)
                        published_at = dt.strftime("%Y-%m-%d")
                    except (ValueError, TypeError):
                        pass

                image_url = _extract_featured_image(post)

                items.append(
                    FontNewsItem(
                        source_id=source_id,
                        source_name=source_name,
                        title=title,
                        url=link,
                        published_at=published_at,
                        image_url=image_url,
                        raw={},
                    )
                )

            if len(posts) < per_page:
                break
            page += 1

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


def _extract_featured_image(post: dict) -> str | None:
    """Extract featured image URL from WP _embedded data."""
    embedded = post.get("_embedded") or {}
    media_list = embedded.get("wp:featuredmedia") or []
    if not media_list or not isinstance(media_list, list):
        return None
    media = media_list[0]
    if not isinstance(media, dict):
        return None
    sizes = (media.get("media_details") or {}).get("sizes") or {}
    for size_key in ("medium_large", "medium", "full"):
        size = sizes.get(size_key)
        if isinstance(size, dict) and size.get("source_url"):
            return size["source_url"]
    return media.get("source_url")
