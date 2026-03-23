"""Future Fonts blog/news crawler. Parses blog, fetches article pages for dates."""

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


def _extract_blog_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Extract (title, url) from blog listing page."""
    soup = BeautifulSoup(html, "html.parser")
    results: list[tuple[str, str]] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href:
            continue
        full_url = urljoin(base_url, href)
        if "/blog/" not in full_url or full_url.rstrip("/") == urljoin(base_url, "/blog").rstrip("/"):
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        title = (a.get_text() or "").strip()
        if not title or len(title) < 3:
            continue
        if title.lower() in ("view full post", "read more", "...", "got it"):
            continue
        results.append((title, full_url))

    return results


class FutureFontsNewsCrawler:
    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontNewsItem]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = str(self.source_config.get("base_url", "https://www.futurefonts.com"))
        crawl_cfg = self.source_config.get("crawl", {})
        blog_url = urljoin(base_url, crawl_cfg.get("blog_url", "/blog"))

        items: list[FontNewsItem] = []

        try:
            r = session.get(blog_url, timeout=timeout)
            r.raise_for_status()
        except requests.RequestException:
            return items

        links = _extract_blog_links(r.text, base_url)
        date_fetch_limit = int(crawl_cfg.get("date_fetch_limit", 10))
        for i, (title, url) in enumerate(links[:15]):
            published_at = None
            image_url = None
            if i < date_fetch_limit:
                try:
                    ar = session.get(url, timeout=timeout)
                    ar.raise_for_status()
                    published_at = extract_published_at(ar.text, url)
                    image_url = extract_og_image(ar.text, url)
                except requests.RequestException:
                    pass
                time.sleep(0.3)

            items.append(
                FontNewsItem(
                    source_id=source_id,
                    source_name=source_name,
                    title=title,
                    url=url,
                    published_at=published_at,
                    image_url=image_url,
                    raw={"blog_url": blog_url},
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
