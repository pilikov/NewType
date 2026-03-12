"""
Fontstand incremental (daily) crawler.

Fetches only New Releases (RSS + loadMore) for a date range, matches to catalog slugs
via filteredfonts (first pages with sort=release-date), outputs releases with basic metadata.
Scripts/category/features enrichment skipped for speed; full run has them.
"""

from __future__ import annotations

import time
from datetime import date, datetime
from typing import Any

import requests

from src.crawlers.fontstand_catalog import (
    _extract_image_url,
    _fetch_filteredfonts_page,
    _fetch_new_releases_dates,
    _parse_foundry_title,
)
from src.crawlers.shared.text import unique_strings
from src.models import FontRelease


def _fetch_catalog_for_date_range(
    session: requests.Session,
    filteredfonts_url: str,
    page_size: int,
    delay: float,
    timeout: int,
    referer: str,
    max_pages: int,
    sort_release_date: bool = True,
) -> dict[tuple[str, str], tuple[str, dict[str, Any]]]:
    """
    Fetch first N pages of filteredfonts, optionally sorted by release date.
    Returns (name_normalized, foundry_normalized) -> (slug, item_data).
    """
    key_to_slug_item: dict[tuple[str, str], tuple[str, dict[str, Any]]] = {}
    extra = {"sort": "release-date"} if sort_release_date else {}
    start = 0
    for _ in range(max_pages):
        if delay > 0:
            time.sleep(delay)
        payload = _fetch_filteredfonts_page(
            session=session,
            url=filteredfonts_url,
            start=start,
            timeout=timeout,
            referer=referer,
            extra_params=extra if extra else None,
        )
        if not payload or not payload.get("Good"):
            break
        data = payload.get("Data") or []
        if not data:
            break
        for item in data:
            if not isinstance(item, dict):
                continue
            link = (item.get("Link") or "").strip()
            if not link or not link.startswith("fonts/"):
                continue
            slug = link.replace("fonts/", "").strip().rstrip("/")
            if not slug:
                continue
            title = (item.get("Title") or "").strip()
            if not title:
                continue
            authors, _ = _parse_foundry_title(str(item.get("FoundryTitle") or ""))
            foundry = (authors[0].lower() if authors else "")
            key = (title.lower(), foundry)
            key_to_slug_item[key] = (slug, item)
        if len(data) < page_size:
            break
        start += page_size
    return key_to_slug_item


class FontstandNewReleasesCrawler:
    """Incremental crawler: only New Releases in date range, matched to catalog slugs."""

    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config
        self.release_callback: Any = None

    def set_release_callback(self, callback: Any) -> None:
        self.release_callback = callback

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontRelease]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = self.source_config.get("base_url", "https://fontstand.com").rstrip("/")
        referer = f"{base_url}/fonts/"

        crawl_cfg = self.source_config.get("crawl", {})
        filteredfonts_url = crawl_cfg.get("filteredfonts_url", f"{base_url}/fonts/filteredfonts")
        page_size = int(crawl_cfg.get("page_size", 64))
        delay = float(crawl_cfg.get("request_delay_seconds", 0.5))
        rss_url = crawl_cfg.get("new_releases_rss_url", f"{base_url}/news/new-releases/rss")
        loadmore_url = crawl_cfg.get("new_releases_loadmore_url")
        start_date_str = crawl_cfg.get("start_date")
        end_date_str = crawl_cfg.get("end_date")
        max_catalog_pages = int(crawl_cfg.get("max_catalog_pages", 5))

        start_date = _parse_ymd(start_date_str) if start_date_str else None
        end_date = _parse_ymd(end_date_str) if end_date_str else None

        new_releases_all = _fetch_new_releases_dates(
            session=session,
            rss_url=rss_url,
            loadmore_url=loadmore_url,
            timeout=timeout,
        )
        if start_date is not None or end_date is not None:
            new_releases_filtered: dict[tuple[str, str], str] = {}
            for key, date_str in new_releases_all.items():
                d = _parse_ymd(date_str)
                if d is None:
                    continue
                if start_date is not None and d < start_date:
                    continue
                if end_date is not None and d > end_date:
                    continue
                new_releases_filtered[key] = date_str
            new_releases_dates = new_releases_filtered
        else:
            new_releases_dates = new_releases_all

        if not new_releases_dates:
            return []

        key_to_slug_item = _fetch_catalog_for_date_range(
            session=session,
            filteredfonts_url=filteredfonts_url,
            page_size=page_size,
            delay=delay,
            timeout=timeout,
            referer=referer,
            max_pages=max_catalog_pages,
            sort_release_date=True,
        )

        releases: list[FontRelease] = []
        seen_slugs: set[str] = set()

        for (name_norm, foundry_norm), release_date in new_releases_dates.items():
            pair = key_to_slug_item.get((name_norm, foundry_norm))
            if not pair:
                continue
            slug, item = pair
            if slug in seen_slugs:
                continue
            seen_slugs.add(slug)

            title = (item.get("Title") or "").strip() or name_norm
            authors, _ = _parse_foundry_title(str(item.get("FoundryTitle") or ""))
            image_url = _extract_image_url(str(item.get("Image") or ""), base_url)
            source_url = f"{base_url}/fonts/{slug}"

            release = FontRelease(
                source_id=source_id,
                source_name=source_name,
                source_url=source_url,
                name=title,
                styles=[],
                authors=unique_strings(authors),
                scripts=[],
                release_date=release_date,
                image_url=image_url,
                woff_url=None,
                specimen_pdf_url=None,
                raw={
                    "release_identity": f"fontstand:{slug}",
                    "link": f"fonts/{slug}",
                    "incremental": True,
                },
            )
            releases.append(release)
            if self.release_callback:
                self.release_callback(release)

        return releases


def _parse_ymd(s: str) -> date | None:
    if not s or not isinstance(s, str):
        return None
    s = s.strip()[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None
