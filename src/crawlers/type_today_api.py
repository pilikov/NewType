from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode, urljoin

import requests

from src.crawlers.shared.text import unique_strings
from src.models import FontRelease


def _api_join(base_url: str, endpoint: str) -> str:
    clean = endpoint if endpoint.startswith("/") else f"/{endpoint}"
    return urljoin(base_url, clean)


def _split_author_phrase(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"\band\b|,|&|\\bи\\b", text, flags=re.IGNORECASE)
    return [p.strip(" .\n\t") for p in parts if p.strip(" .\n\t")]


def _extract_script_hints(language_titles: str | None) -> list[str]:
    value = (language_titles or "").lower()
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
        or "portuguese" in value
    ):
        scripts.append("Latin")
    if "greek" in value:
        scripts.append("Greek")
    if "arab" in value:
        scripts.append("Arabic")
    if "hebrew" in value:
        scripts.append("Hebrew")
    if "armenian" in value:
        scripts.append("Armenian")
    if "georgian" in value:
        scripts.append("Georgian")
    return unique_strings(scripts)


@dataclass
class TypeTodayApiCrawler:
    source_config: dict[str, Any]
    release_callback: Any = None

    def set_release_callback(self, callback: Any) -> None:
        self.release_callback = callback

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontRelease]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = self.source_config.get("base_url", "https://type.today")
        crawl_cfg = self.source_config.get("crawl", {})

        api_base = crawl_cfg.get("api_base_url", base_url)
        fonts_endpoint = crawl_cfg.get("fonts_endpoint", "/api/v1/fonts")
        font_detail_template = crawl_cfg.get("font_detail_endpoint_template", "/api/v1/fonts/{slug}")
        authors_endpoint = crawl_cfg.get("authors_endpoint", "/api/v1/authors")
        author_detail_template = crawl_cfg.get("author_detail_endpoint_template", "/api/v1/authors/{slug}")
        detail_include = crawl_cfg.get("font_detail_include", "font_styles,custom_font_styles,font_tabs")
        page_size = int(crawl_cfg.get("page_size", 100))
        max_pages = int(crawl_cfg.get("max_pages", 0))
        request_delay_seconds = float(crawl_cfg.get("request_delay_seconds", 0.0))
        use_author_mapping = bool(crawl_cfg.get("use_author_mapping", True))
        include_full_raw = bool(crawl_cfg.get("include_full_raw", True))

        fonts = self._fetch_all_fonts(
            session=session,
            timeout=timeout,
            api_base=api_base,
            fonts_endpoint=fonts_endpoint,
            page_size=page_size,
            max_pages=max_pages,
            request_delay_seconds=request_delay_seconds,
        )
        font_authors = (
            self._build_font_authors_map(
                session=session,
                timeout=timeout,
                api_base=api_base,
                authors_endpoint=authors_endpoint,
                author_detail_template=author_detail_template,
                page_size=page_size,
                max_pages=max_pages,
                request_delay_seconds=request_delay_seconds,
            )
            if use_author_mapping
            else {}
        )

        releases: list[FontRelease] = []
        for item in fonts:
            item_attrs = item.get("attributes") or {}
            slug = str(item_attrs.get("slug") or "").strip()
            title = str(item_attrs.get("title") or "").strip()
            if not slug or not title:
                continue

            detail_url = _api_join(api_base, font_detail_template.format(slug=slug))
            detail_params = {"include": detail_include} if detail_include else {}
            detail_error: str | None = None
            try:
                detail_payload = self._get_json(
                    session=session,
                    url=detail_url,
                    timeout=timeout,
                    params=detail_params,
                )
            except requests.RequestException as exc:
                detail_payload = {}
                detail_error = str(exc)
            if request_delay_seconds > 0:
                time.sleep(request_delay_seconds)

            detail_data = (detail_payload.get("data") or {}) if isinstance(detail_payload, dict) else {}
            detail_attrs = (detail_data.get("attributes") or {}) if isinstance(detail_data, dict) else {}
            if not detail_attrs:
                detail_attrs = item_attrs
            included_rows = (
                detail_payload.get("included") if isinstance(detail_payload, dict) and isinstance(detail_payload.get("included"), list) else []
            )

            styles = self._extract_styles(included_rows)
            authors = unique_strings(font_authors.get(slug, []) + _split_author_phrase(str(detail_attrs.get("inline_authors") or "")))
            scripts = _extract_script_hints(str(detail_attrs.get("language_titles") or ""))
            year = detail_attrs.get("year")

            share_image = detail_attrs.get("share_image")
            image_url = share_image.get("url") if isinstance(share_image, dict) else None
            specimen = detail_attrs.get("specimen")
            specimen_pdf_url = specimen.get("url") if isinstance(specimen, dict) else None
            woff_url = self._extract_woff(included_rows)

            raw_payload: dict[str, Any] = {
                "slug": slug,
                "year": year,
                "new_badge": detail_attrs.get("new_badge"),
                "language_titles": detail_attrs.get("language_titles"),
                "inline_authors": detail_attrs.get("inline_authors"),
                "authors_from_author_api": font_authors.get(slug, []),
                "font_api_url": detail_url + (f"?{urlencode(detail_params)}" if detail_params else ""),
            }
            if detail_error:
                raw_payload["font_detail_error"] = detail_error
            if include_full_raw:
                raw_payload["font_list_item"] = item
                raw_payload["font_detail"] = detail_data
                raw_payload["font_included"] = included_rows

            release = FontRelease(
                source_id=source_id,
                source_name=source_name,
                source_url=urljoin(base_url, f"/ru/{slug}"),
                name=title,
                styles=styles,
                authors=authors,
                scripts=scripts,
                release_date=f"{year}-01-01" if year else None,
                image_url=image_url,
                woff_url=woff_url,
                specimen_pdf_url=specimen_pdf_url,
                raw=raw_payload,
            )
            releases.append(release)
            if self.release_callback:
                self.release_callback(release)

        return releases

    def _fetch_all_fonts(
        self,
        session: requests.Session,
        timeout: int,
        api_base: str,
        fonts_endpoint: str,
        page_size: int,
        max_pages: int,
        request_delay_seconds: float,
    ) -> list[dict[str, Any]]:
        url = _api_join(api_base, fonts_endpoint)
        out: list[dict[str, Any]] = []
        page = 1
        total_count: int | None = None
        while True:
            if max_pages > 0 and page > max_pages:
                break
            payload = self._get_json(
                session=session,
                url=url,
                timeout=timeout,
                params={"page[size]": page_size, "page[number]": page},
            )
            rows = payload.get("data") if isinstance(payload, dict) else []
            if not isinstance(rows, list) or not rows:
                break
            out.extend([row for row in rows if isinstance(row, dict)])
            meta = payload.get("meta") if isinstance(payload, dict) else {}
            if isinstance(meta, dict) and isinstance(meta.get("record_count"), int):
                total_count = int(meta["record_count"])
            if request_delay_seconds > 0:
                time.sleep(request_delay_seconds)
            if len(rows) < page_size:
                break
            if total_count is not None and len(out) >= total_count:
                break
            page += 1
        return out

    def _build_font_authors_map(
        self,
        session: requests.Session,
        timeout: int,
        api_base: str,
        authors_endpoint: str,
        author_detail_template: str,
        page_size: int,
        max_pages: int,
        request_delay_seconds: float,
    ) -> dict[str, list[str]]:
        authors_url = _api_join(api_base, authors_endpoint)
        author_slugs: list[str] = []
        page = 1
        total_count: int | None = None
        while True:
            if max_pages > 0 and page > max_pages:
                break
            payload = self._get_json(
                session=session,
                url=authors_url,
                timeout=timeout,
                params={
                    "page[size]": page_size,
                    "page[number]": page,
                    "fields[authors]": "slug,full_name,last_name",
                },
            )
            rows = payload.get("data") if isinstance(payload, dict) else []
            if not isinstance(rows, list) or not rows:
                break
            for row in rows:
                attrs = (row or {}).get("attributes") if isinstance(row, dict) else {}
                if not isinstance(attrs, dict):
                    continue
                slug = str(attrs.get("slug") or "").strip()
                if slug:
                    author_slugs.append(slug)
            meta = payload.get("meta") if isinstance(payload, dict) else {}
            if isinstance(meta, dict) and isinstance(meta.get("record_count"), int):
                total_count = int(meta["record_count"])
            if request_delay_seconds > 0:
                time.sleep(request_delay_seconds)
            if len(rows) < page_size:
                break
            if total_count is not None and len(author_slugs) >= total_count:
                break
            page += 1

        font_authors: dict[str, list[str]] = {}
        for author_slug in unique_strings(author_slugs):
            detail_url = _api_join(api_base, author_detail_template.format(slug=author_slug))
            try:
                payload = self._get_json(
                    session=session,
                    url=detail_url,
                    timeout=timeout,
                    params={"include": "fonts", "fields[fonts]": "slug", "fields[authors]": "slug,full_name,last_name"},
                )
            except requests.RequestException:
                continue
            if request_delay_seconds > 0:
                time.sleep(request_delay_seconds)

            data = payload.get("data") if isinstance(payload, dict) else {}
            attrs = data.get("attributes") if isinstance(data, dict) else {}
            author_name = str((attrs or {}).get("full_name") or (attrs or {}).get("last_name") or author_slug).strip()
            if not author_name:
                continue

            for row in payload.get("included") or []:
                if not isinstance(row, dict):
                    continue
                if row.get("type") != "fonts":
                    continue
                row_attrs = row.get("attributes") or {}
                font_slug = str(row_attrs.get("slug") or "").strip()
                if not font_slug:
                    continue
                font_authors.setdefault(font_slug, []).append(author_name)

        return {slug: unique_strings(names) for slug, names in font_authors.items()}

    def _extract_styles(self, included_rows: list[dict[str, Any]]) -> list[str]:
        styles: list[str] = []
        for row in included_rows:
            if row.get("type") != "font_styles":
                continue
            attrs = row.get("attributes") or {}
            title = str(attrs.get("title") or "").strip()
            if title:
                styles.append(title)
        return unique_strings(styles)

    def _extract_woff(self, included_rows: list[dict[str, Any]]) -> str | None:
        for row in included_rows:
            if row.get("type") != "font_styles":
                continue
            attrs = row.get("attributes") or {}
            for key in ("public_file", "public_file_without_encoding"):
                candidate = attrs.get(key)
                if isinstance(candidate, dict):
                    candidate = candidate.get("url")
                if isinstance(candidate, str) and candidate.lower().endswith((".woff", ".woff2")):
                    return candidate
        return None

    def _get_json(
        self,
        session: requests.Session,
        url: str,
        timeout: int,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        response = session.get(url, params=params or {}, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
