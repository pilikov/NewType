from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.crawlers.shared.dates import parse_ymd
from src.crawlers.shared.next_data import extract_next_initial_state
from src.crawlers.shared.text import normalize_spaces, unique_strings
from src.models import FontRelease


@dataclass
class TypeTodayJournalCrawler:
    source_config: dict[str, Any]
    release_callback: Any = None

    def set_release_callback(self, callback: Any) -> None:
        self.release_callback = callback

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontRelease]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = self.source_config.get("base_url", "https://type.today")
        crawl_cfg = self.source_config.get("crawl", {})

        journal_url = urljoin(base_url, crawl_cfg.get("journal_url", "/ru/journal"))
        new_prefix = (crawl_cfg.get("new_post_prefix", "Новый шрифт:") or "").strip().lower()
        start_date = parse_ymd(crawl_cfg.get("start_date"))
        end_date = parse_ymd(crawl_cfg.get("end_date"))

        html = session.get(journal_url, timeout=timeout)
        html.raise_for_status()
        state = extract_next_initial_state(html.text)

        posts_state = state.get("posts", {})
        post_models = posts_state.get("models", {})
        post_ids = posts_state.get("list", [])

        releases: list[FontRelease] = []
        seen_sources: set[str] = set()

        for post_id in post_ids:
            post = post_models.get(post_id) or {}
            attrs = post.get("attributes") or {}

            title = (attrs.get("title") or "").strip()
            title_norm = normalize_spaces(title).lower()
            if not title_norm.startswith(new_prefix):
                continue

            post_date = (attrs.get("date") or "").strip() or None
            post_day = parse_ymd(post_date)
            if start_date and post_day and post_day < start_date:
                continue
            if end_date and post_day and post_day > end_date:
                continue

            post_slug = (attrs.get("slug") or post_id or "").strip()
            if not post_slug:
                continue
            post_url = urljoin(base_url, f"/ru/journal/{post_slug}")
            # Для постов «Новый шрифт» slug поста = slug шрифта (API)
            font_url = urljoin(base_url, f"/ru/{post_slug}")
            detail = self._fetch_font_detail(session, font_url, timeout)
            if not detail:
                continue

            source_url = detail["source_url"]
            if source_url in seen_sources:
                continue
            seen_sources.add(source_url)

            release = FontRelease(
                source_id=source_id,
                source_name=source_name,
                source_url=source_url,
                name=detail["name"],
                styles=detail["styles"],
                authors=detail["authors"],
                scripts=detail["scripts"],
                release_date=post_date,
                image_url=detail["image_url"],
                woff_url=detail["woff_url"],
                specimen_pdf_url=detail["specimen_pdf_url"],
                raw={
                    "journal_post_url": post_url,
                    "journal_post_title": title,
                    "journal_post_date": post_date,
                    "journal_post_slug": post_slug,
                    "journal_link_url": font_url,
                },
            )
            releases.append(release)
            if self.release_callback:
                self.release_callback(release)

        return releases

    def _fetch_font_detail(
        self,
        session: requests.Session,
        font_url: str,
        timeout: int,
    ) -> dict[str, Any] | None:
        try:
            r = session.get(font_url, timeout=timeout)
            r.raise_for_status()
        except requests.RequestException:
            return None

        state = extract_next_initial_state(r.text)
        fonts = state.get("fonts", {}).get("models", {})
        authors_map = state.get("authors", {}).get("models", {})
        soup = BeautifulSoup(r.text, "html.parser")

        slug = _extract_typeface_slug_from_url(font_url)
        model = fonts.get(slug)
        if not model:
            return None

        attrs = model.get("attributes") or {}
        name = (attrs.get("title") or slug.replace("_", " ").replace("-", " ").title()).strip()
        styles = _extract_styles(model)
        authors = _extract_authors(model, attrs, authors_map)
        authors = unique_strings(authors + _extract_authors_from_header_html(soup))
        scripts = _extract_scripts(attrs)

        image_url = None
        share_image = attrs.get("share_image")
        if isinstance(share_image, dict) and share_image.get("url"):
            image_url = share_image.get("url")

        specimen_pdf_url = None
        specimen = attrs.get("specimen")
        if isinstance(specimen, dict) and specimen.get("url"):
            specimen_pdf_url = specimen.get("url")

        woff_url = _extract_woff(model)

        return {
            "source_url": font_url.rstrip("/"),
            "name": name,
            "styles": styles,
            "authors": authors,
            "scripts": scripts,
            "image_url": image_url,
            "specimen_pdf_url": specimen_pdf_url,
            "woff_url": woff_url,
        }

def _extract_typeface_slug_from_url(font_url: str) -> str:
    parsed = urlparse(font_url)
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2:
        return parts[1]
    return ""


def _extract_styles(model: dict[str, Any]) -> list[str]:
    styles: list[str] = []
    for style in model.get("font_styles") or []:
        attrs = style.get("attributes") or {}
        title = (attrs.get("title") or "").strip()
        if title:
            styles.append(title)
    return unique_strings(styles)


def _extract_authors(
    model: dict[str, Any],
    attrs: dict[str, Any],
    authors_map: dict[str, Any],
) -> list[str]:
    result: list[str] = []

    for rel in model.get("relationships", {}).get("authors", {}).get("data") or []:
        author = authors_map.get(rel.get("id") or "", {})
        author_attrs = author.get("attributes") or {}
        full_name = (author_attrs.get("full_name") or "").strip()
        subtitle = (author_attrs.get("subtitle") or "").strip()
        if full_name:
            result.append(full_name)
        elif subtitle:
            result.append(subtitle)

    inline = (attrs.get("inline_authors") or "").strip()
    if inline:
        inline_clean = normalize_spaces(inline)
        parts = re.split(r"\band\b|,|&", inline_clean)
        for part in parts:
            candidate = part.strip(" .")
            if candidate and len(candidate.split()) <= 5:
                result.append(candidate)

    return unique_strings(result)


def _extract_authors_from_header_html(soup: BeautifulSoup) -> list[str]:
    container = soup.select_one(".entity__header__content p")
    if not container:
        return []

    text = normalize_spaces(container.get_text(" ", strip=True))
    if not text:
        return []

    parts = re.split(r",|\\band\\b|\\bи\\b|&", text, flags=re.IGNORECASE)
    authors = [part.strip(" .") for part in parts if part.strip()]
    return unique_strings(authors)


def _extract_scripts(attrs: dict[str, Any]) -> list[str]:
    value = str(attrs.get("language_titles") or "").lower()
    scripts: list[str] = []
    if (
        "cyr" in value
        or "russian" in value
        or "ukrainian" in value
        or "рус" in value
        or "украин" in value
        or "белорус" in value
        or "казах" in value
        or "серб" in value
        or "болгар" in value
    ):
        scripts.append("Cyrillic")
    if (
        "latin" in value
        or "english" in value
        or "german" in value
        or "french" in value
        or "англий" in value
        or "немец" in value
        or "француз" in value
        or "испан" in value
        or "итальян" in value
    ):
        scripts.append("Latin")
    if "greek" in value:
        scripts.append("Greek")
    if "arab" in value:
        scripts.append("Arabic")
    if "hebrew" in value:
        scripts.append("Hebrew")
    return unique_strings(scripts)


def _extract_woff(model: dict[str, Any]) -> str | None:
    for style in model.get("font_styles") or []:
        attrs = style.get("attributes") or {}
        for key in ("public_file", "public_file_without_encoding"):
            maybe = attrs.get(key)
            if isinstance(maybe, dict):
                maybe = maybe.get("url")
            if isinstance(maybe, str) and maybe.lower().endswith((".woff", ".woff2")):
                return maybe
    return None
