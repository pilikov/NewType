"""Monotype news crawler.

Uses the Drupal Views AJAX endpoint to fetch all news items from the
newsroom (view: news_events_listing).  This returns ~192 articles with
ISO datetime — far more than the 40 visible on the static HTML page.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.crawlers.news.date_filter import filter_items_by_date_window
from src.models import FontNewsItem

log = logging.getLogger(__name__)

# Drupal Views AJAX contract — discovered from drupalSettings on the page.
_VIEWS_AJAX_PATH = "/views/ajax"
_VIEW_NAME = "news_events_listing"
_VIEW_DISPLAY_ID = "news_events_listing"
_VIEW_PATH = "/node/2861"
_VIEW_DOM_ID = (
    "5c956c1798084a4e499e0fdf1e52c8796f6e53ebeccfe3af8492dd842ed3cf39"
)

_ALLOWED_PATH_PREFIXES = (
    "/company/thought-leadership/",
    "/company/press-release/",
    "/company/spotlights/",
    "/company/news/",
)


class MonotypeNewsCrawler:
    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def crawl(self, session: requests.Session, timeout: int = 30) -> list[FontNewsItem]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = str(
            self.source_config.get("base_url", "https://www.monotype.com")
        )

        html = self._fetch_views_ajax(session, base_url, timeout)
        if not html:
            # Fallback: try the static page if AJAX failed.
            html = self._fetch_static(session, base_url, timeout)
        if not html:
            return []

        items = self._parse_items(html, source_id, source_name, base_url)

        # Apply optional date window (injected by daily-override logic).
        crawl_cfg = self.source_config.get("crawl", {})
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

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _fetch_views_ajax(
        self,
        session: requests.Session,
        base_url: str,
        timeout: int,
    ) -> str | None:
        """POST to Drupal Views AJAX and return the inserted HTML."""
        url = base_url.rstrip("/") + _VIEWS_AJAX_PATH
        payload = {
            "view_name": _VIEW_NAME,
            "view_display_id": _VIEW_DISPLAY_ID,
            "view_args": "",
            "view_path": _VIEW_PATH,
            "view_dom_id": _VIEW_DOM_ID,
            "pager_element": "0",
            "page": "0",
            "_wrapper_format": "drupal_ajax",
        }
        try:
            r = session.post(url, data=payload, timeout=timeout)
            r.raise_for_status()
        except requests.RequestException as exc:
            log.warning("Monotype Views AJAX failed: %s", exc)
            return None

        try:
            commands = r.json()
        except (json.JSONDecodeError, ValueError):
            log.warning("Monotype Views AJAX returned non-JSON")
            return None

        # The response is a list of AJAX commands.  We need the big
        # "insert / replaceWith" that carries the rendered HTML.
        for cmd in commands:
            if (
                cmd.get("command") == "insert"
                and cmd.get("method") == "replaceWith"
                and cmd.get("data")
            ):
                return cmd["data"]

        log.warning("Monotype Views AJAX: no insert command found")
        return None

    def _fetch_static(
        self,
        session: requests.Session,
        base_url: str,
        timeout: int,
    ) -> str | None:
        """Fallback: GET the static news-press page."""
        news_url = str(
            self.source_config.get("news_url")
            or self.source_config.get("crawl", {}).get("news_url")
            or base_url.rstrip("/") + "/company/news-press"
        )
        try:
            r = session.get(news_url, timeout=timeout)
            r.raise_for_status()
            return r.text
        except requests.RequestException as exc:
            log.warning("Monotype static fallback failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_items(
        html: str,
        source_id: str,
        source_name: str,
        base_url: str,
    ) -> list[FontNewsItem]:
        soup = BeautifulSoup(html, "html.parser")
        items: list[FontNewsItem] = []
        seen_urls: set[str] = set()

        for row in soup.find_all("div", class_="news-and-event-item"):
            title_el = row.find("div", class_="news-and-event-title")
            if not title_el:
                continue
            a = title_el.find("a", href=True)
            if not a:
                continue

            href = a.get("href", "").strip()
            if not href or "/company/news-press" in href:
                continue
            if not any(p in href for p in _ALLOWED_PATH_PREFIXES):
                continue

            full_url = urljoin(base_url, href)
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)

            title = (a.get_text() or "").strip()
            if not title or len(title) < 5:
                continue

            published_at = _extract_datetime(row)

            # Derive category from URL path, e.g. "press-release".
            category = ""
            for prefix in _ALLOWED_PATH_PREFIXES:
                if prefix in href:
                    category = prefix.strip("/").split("/")[-1]
                    break

            items.append(
                FontNewsItem(
                    source_id=source_id,
                    source_name=source_name,
                    title=title,
                    url=full_url,
                    published_at=published_at,
                    raw={"category": category} if category else {},
                )
            )

        return items


def _extract_datetime(row: Any) -> str | None:
    """Try <time datetime> first, fall back to date div text."""
    time_el = row.find("time", attrs={"datetime": True})
    if time_el:
        dt_str = time_el.get("datetime", "")
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                return dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass

    date_el = row.find("div", class_="news-and-event-date")
    if date_el:
        text = date_el.get_text(strip=True)
        if text:
            for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
                try:
                    return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
                except ValueError:
                    continue
    return None
