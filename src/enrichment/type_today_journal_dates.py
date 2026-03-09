from __future__ import annotations

import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests

from src.crawlers.shared.dates import parse_ymd, parse_iso_day
from src.crawlers.shared.next_data import extract_next_initial_state
from src.models import FontRelease
from src.utils import dump_json, load_json


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _extract_font_slugs_from_html(html: str, base_url: str) -> list[str]:
    slugs: list[str] = []
    for href in re.findall(r'href="([^"]+)"', html):
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.netloc not in {"type.today", "www.type.today", "tomorrow.type.today"}:
            continue
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) != 2:
            continue
        if parts[0] not in {"ru", "en"}:
            continue
        slug = parts[1].strip()
        if not slug:
            continue
        if slug in {"about", "license", "faq", "rules", "journal", "cart", "collection", "designer", "profile"}:
            continue
        slugs.append(slug)
    # Stable order, unique
    seen: set[str] = set()
    out: list[str] = []
    for slug in slugs:
        if slug in seen:
            continue
        seen.add(slug)
        out.append(slug)
    return out


def _extract_journal_post_slugs_from_html(html: str, base_url: str) -> list[str]:
    slugs: list[str] = []
    for href in re.findall(r'href="([^"]+)"', html):
        abs_url = urljoin(base_url, href)
        parsed = urlparse(abs_url)
        if parsed.netloc not in {"type.today", "www.type.today"}:
            continue
        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) != 3:
            continue
        if parts[0] not in {"ru", "en"} or parts[1] != "journal":
            continue
        slug = parts[2].strip()
        if slug:
            slugs.append(slug)
    seen: set[str] = set()
    out: list[str] = []
    for slug in slugs:
        if slug in seen:
            continue
        seen.add(slug)
        out.append(slug)
    return out


def _release_slug(release: FontRelease) -> str | None:
    raw_slug = str(release.raw.get("slug") or "").strip()
    if raw_slug:
        return raw_slug
    if not release.source_url:
        return None
    parsed = urlparse(release.source_url)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0] in {"ru", "en"}:
        return parts[1]
    return None


@dataclass
class TypeTodayJournalDateEnrichmentResult:
    journal_posts_scanned: int = 0
    journal_posts_processed: int = 0
    fallback_font_pages_processed: int = 0
    fallback_links_checked: int = 0
    slugs_with_journal_dates: int = 0
    all_releases_updated: int = 0
    new_releases_updated: int = 0


def enrich_type_today_release_dates(
    source_cfg: dict[str, Any],
    all_releases: list[FontRelease],
    new_releases: list[FontRelease],
    state_root: Path,
    session: requests.Session,
    timeout: int = 20,
) -> TypeTodayJournalDateEnrichmentResult:
    result = TypeTodayJournalDateEnrichmentResult()

    base_url = str(source_cfg.get("base_url") or "https://type.today")
    crawl_cfg = source_cfg.get("crawl", {})
    api_base = str(crawl_cfg.get("api_base_url") or base_url)
    posts_endpoint = str(crawl_cfg.get("posts_endpoint") or "/api/v1/posts")
    post_detail_template = str(crawl_cfg.get("post_detail_endpoint_template") or "/api/v1/posts/{slug}")
    journal_url = urljoin(base_url, str(crawl_cfg.get("journal_url") or "/ru/journal"))
    new_post_prefix = _normalize_space(str(crawl_cfg.get("new_post_prefix") or "Новый шрифт:")).lower()
    posts_page_size = int(crawl_cfg.get("journal_posts_page_size", 100))
    max_post_pages = int(crawl_cfg.get("journal_posts_max_pages", 0))

    state_path = state_root / "type_today_journal_release_dates.json"
    state_payload = load_json(state_path, default={})
    processed_posts = state_payload.get("processed_posts") if isinstance(state_payload, dict) else {}
    slug_dates = state_payload.get("slug_dates") if isinstance(state_payload, dict) else {}
    font_page_cache = state_payload.get("font_page_cache") if isinstance(state_payload, dict) else {}
    if not isinstance(processed_posts, dict):
        processed_posts = {}
    if not isinstance(slug_dates, dict):
        slug_dates = {}
    if not isinstance(font_page_cache, dict):
        font_page_cache = {}

    def upsert_slug_date(font_slug: str, post_slug: str, post_url: str, post_date: str, source: str) -> None:
        post_day = parse_ymd(post_date)
        if not post_day:
            return
        current = slug_dates.get(font_slug) if isinstance(slug_dates.get(font_slug), dict) else None
        current_day = parse_ymd(str((current or {}).get("release_date") or ""))
        if current_day is None or post_day < current_day:
            slug_dates[font_slug] = {
                "release_date": post_date,
                "post_slug": post_slug,
                "post_url": post_url,
                "source": source,
            }

    def get_post_detail(post_slug: str, post_meta: dict[str, Any] | None) -> dict[str, Any] | None:
        meta_title = _normalize_space(str((post_meta or {}).get("title") or ""))
        meta_date = str((post_meta or {}).get("date") or "").strip()
        signature = f"{meta_date}|{meta_title}"
        cached = processed_posts.get(post_slug) if isinstance(processed_posts.get(post_slug), dict) else None
        if (
            cached
            and str(cached.get("signature") or "") == signature
            and isinstance(cached.get("font_slugs"), list)
        ):
            return cached

        post_api_url = urljoin(api_base, post_detail_template.format(slug=post_slug))
        try:
            response = session.get(post_api_url, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            return cached if isinstance(cached, dict) else None

        data = payload.get("data") if isinstance(payload, dict) else {}
        attrs = data.get("attributes") if isinstance(data, dict) else {}
        title = _normalize_space(str((attrs or {}).get("title") or meta_title))
        date = str((attrs or {}).get("date") or meta_date).strip()
        body_html = str((attrs or {}).get("body") or "")
        font_slugs = _extract_font_slugs_from_html(body_html, base_url)
        item = {
            "signature": f"{date}|{title}",
            "title": title,
            "date": date,
            "post_url": urljoin(base_url, f"/ru/journal/{post_slug}"),
            "font_slugs": font_slugs,
            "is_new_font_post": title.lower().startswith(new_post_prefix),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        processed_posts[post_slug] = item
        result.journal_posts_processed += 1
        return item

    # Pass 1: full journal traversal via posts API pagination ("show more" equivalent)
    posts_api_url = urljoin(api_base, posts_endpoint)
    posts_by_slug: dict[str, dict[str, Any]] = {}
    page = 1
    while True:
        if max_post_pages > 0 and page > max_post_pages:
            break
        payload: dict[str, Any] | None = None
        for attempt in range(3):
            try:
                response = session.get(
                    posts_api_url,
                    params={
                        "page[size]": posts_page_size,
                        "page[number]": page,
                        "fields[posts]": "slug,title,date",
                    },
                    timeout=timeout,
                )
                response.raise_for_status()
                raw_payload = response.json()
                payload = raw_payload if isinstance(raw_payload, dict) else {}
                break
            except requests.RequestException:
                if attempt >= 2:
                    payload = None
                    break
                time.sleep(0.5 * (attempt + 1))
        if payload is None:
            break
        rows = payload.get("data") if isinstance(payload, dict) else []
        if not isinstance(rows, list) or not rows:
            break
        for row in rows:
            attrs = (row or {}).get("attributes") if isinstance(row, dict) else {}
            slug = str((attrs or {}).get("slug") or "").strip()
            title = _normalize_space(str((attrs or {}).get("title") or ""))
            date = str((attrs or {}).get("date") or "").strip()
            if not slug:
                continue
            posts_by_slug[slug] = {"slug": slug, "title": title, "date": date}
        if len(rows) < posts_page_size:
            break
        page += 1

    # Fallback if posts API is unavailable in this run.
    if not posts_by_slug:
        try:
            r = session.get(journal_url, timeout=timeout)
            r.raise_for_status()
            state = extract_next_initial_state(r.text)
            post_models = (state.get("posts") or {}).get("models") or {}
            post_ids = (state.get("posts") or {}).get("list") or []
            for pid in post_ids:
                attrs = (post_models.get(pid) or {}).get("attributes") or {}
                slug = str(attrs.get("slug") or pid or "").strip()
                title = _normalize_space(str(attrs.get("title") or ""))
                date = str(attrs.get("date") or "").strip()
                if slug:
                    posts_by_slug[slug] = {"slug": slug, "title": title, "date": date}
        except requests.RequestException:
            pass

    for post_slug, meta in posts_by_slug.items():
        title = _normalize_space(str(meta.get("title") or ""))
        if not title or not title.lower().startswith(new_post_prefix):
            continue
        result.journal_posts_scanned += 1
        detail = get_post_detail(post_slug, meta)
        if not detail:
            continue
        post_date = str(detail.get("date") or "").strip()
        post_url = str(detail.get("post_url") or urljoin(base_url, f"/ru/journal/{post_slug}"))
        for font_slug in [str(item).strip() for item in detail.get("font_slugs") or [] if str(item).strip()]:
            upsert_slug_date(
                font_slug=font_slug,
                post_slug=post_slug,
                post_url=post_url,
                post_date=post_date,
                source="journal_posts_api",
            )

    # Pass 2: fallback from font page links -> journal post -> date
    slugs_in_releases = [slug for slug in (_release_slug(r) for r in all_releases) if slug]
    for font_slug in slugs_in_releases:
        if isinstance(slug_dates.get(font_slug), dict):
            continue
        cached_font_page = font_page_cache.get(font_slug) if isinstance(font_page_cache.get(font_slug), dict) else None
        journal_post_slugs: list[str]
        if cached_font_page and isinstance(cached_font_page.get("journal_post_slugs"), list):
            journal_post_slugs = [str(item).strip() for item in cached_font_page.get("journal_post_slugs", []) if str(item).strip()]
        else:
            font_url = urljoin(base_url, f"/ru/{font_slug}")
            try:
                page_response = session.get(font_url, timeout=timeout)
                page_response.raise_for_status()
                html = page_response.text
            except requests.RequestException:
                continue
            journal_post_slugs = _extract_journal_post_slugs_from_html(html, base_url)
            font_page_cache[font_slug] = {
                "font_url": font_url,
                "journal_post_slugs": journal_post_slugs,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            result.fallback_font_pages_processed += 1
        if not journal_post_slugs:
            continue

        candidates: list[tuple[str, str, str]] = []
        for post_slug in journal_post_slugs:
            result.fallback_links_checked += 1
            meta = posts_by_slug.get(post_slug, {"slug": post_slug, "title": "", "date": ""})
            title = _normalize_space(str(meta.get("title") or ""))
            if title and not title.lower().startswith(new_post_prefix):
                continue
            detail = get_post_detail(post_slug, meta)
            if not detail:
                continue
            if not bool(detail.get("is_new_font_post")):
                continue
            post_date = str(detail.get("date") or "").strip()
            post_url = str(detail.get("post_url") or urljoin(base_url, f"/ru/journal/{post_slug}"))
            post_font_slugs = {str(item).strip() for item in detail.get("font_slugs") or [] if str(item).strip()}
            if font_slug in post_font_slugs and parse_ymd(post_date):
                candidates.append((post_date, post_slug, post_url))

        if not candidates:
            continue
        candidates.sort(key=lambda item: parse_ymd(item[0]) or parse_iso_day("9999-12-31"))
        best_date, best_post_slug, best_post_url = candidates[0]
        upsert_slug_date(
            font_slug=font_slug,
            post_slug=best_post_slug,
            post_url=best_post_url,
            post_date=best_date,
            source="font_page_journal_link",
        )

    result.slugs_with_journal_dates = len(slug_dates)

    def is_placeholder_year_date(release: FontRelease) -> bool:
        if not release.release_date:
            return False
        year = str(release.raw.get("year") or "").strip()
        return bool(year) and release.release_date == f"{year}-01-01"

    def apply_rows(rows: list[FontRelease]) -> int:
        updated = 0
        for release in rows:
            slug = _release_slug(release)
            if not slug:
                continue
            mapped = slug_dates.get(slug) if isinstance(slug_dates.get(slug), dict) else None
            if not mapped:
                continue
            mapped_date = str(mapped.get("release_date") or "").strip()
            if not mapped_date:
                continue
            if release.release_date == mapped_date and str(release.raw.get("tt_release_date_source") or "").startswith("journal"):
                continue
            if release.release_date and not is_placeholder_year_date(release):
                # Keep already precise dates if they are not placeholder year dates.
                continue

            if release.release_date != mapped_date and release.release_date and "tt_release_date_previous" not in release.raw:
                release.raw["tt_release_date_previous"] = release.release_date
            release.release_date = mapped_date
            release.raw["tt_release_date_source"] = str(mapped.get("source") or "journal_new_font_post")
            release.raw["tt_release_date_post_slug"] = mapped.get("post_slug")
            release.raw["tt_release_date_post_url"] = mapped.get("post_url")
            updated += 1
        return updated

    result.all_releases_updated = apply_rows(all_releases)
    result.new_releases_updated = apply_rows(new_releases)

    dump_json(
        state_path,
        {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "journal_url": journal_url,
            "posts_api_url": posts_api_url,
            "processed_posts": processed_posts,
            "slug_dates": slug_dates,
            "font_page_cache": font_page_cache,
        },
    )

    return result
