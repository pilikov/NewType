from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests

from src.models import FontRelease


@dataclass
class TypeTodayNextCrawler:
    source_config: dict[str, Any]
    release_callback: Any = None

    def set_release_callback(self, callback: Any) -> None:
        self.release_callback = callback

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontRelease]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = self.source_config.get("base_url", "https://type.today")
        entry_url = self.source_config.get("crawl", {}).get("entry_url", "/en")

        page = session.get(urljoin(base_url, entry_url), timeout=timeout)
        page.raise_for_status()

        state = self._extract_initial_state(page.text)
        fonts = state.get("fonts", {}).get("models", {})
        authors_map = state.get("authors", {}).get("models", {})

        releases: list[FontRelease] = []
        for slug, model in fonts.items():
            attrs = model.get("attributes") or {}
            title = (attrs.get("title") or "").strip()
            if not title:
                continue

            styles = self._extract_styles(model)
            authors = self._extract_authors(model, attrs, authors_map)
            scripts = self._extract_scripts(attrs)
            image_url = self._extract_image_url(attrs)
            specimen_pdf_url = self._extract_specimen_pdf(attrs)
            woff_url = self._extract_woff(model)
            year = attrs.get("year")

            release = FontRelease(
                source_id=source_id,
                source_name=source_name,
                source_url=urljoin(base_url, f"/en/{slug}"),
                name=title,
                styles=styles,
                authors=authors,
                scripts=scripts,
                release_date=f"{year}-01-01" if year else None,
                image_url=image_url,
                woff_url=woff_url,
                specimen_pdf_url=specimen_pdf_url,
                raw={
                    "slug": slug,
                    "year": year,
                    "new_badge": attrs.get("new_badge"),
                    "font_collection_priority": attrs.get("font_collection_priority"),
                },
            )
            releases.append(release)
            if self.release_callback:
                self.release_callback(release)

        return releases

    def _extract_initial_state(self, html: str) -> dict[str, Any]:
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not match:
            return {}

        payload = json.loads(match.group(1))
        return payload.get("props", {}).get("initialState", {})

    def _extract_styles(self, model: dict[str, Any]) -> list[str]:
        styles: list[str] = []
        for style in model.get("font_styles") or []:
            attrs = style.get("attributes") or {}
            title = (attrs.get("title") or "").strip()
            if title:
                styles.append(title)
        return _unique(styles)

    def _extract_authors(
        self,
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
            inline_clean = re.sub(r"\s+", " ", inline)
            result.extend(self._split_author_phrase(inline_clean))

        return _unique(result)

    def _split_author_phrase(self, text: str) -> list[str]:
        # Heuristic fallback for plain-text author strings like
        # "Ilya Ruderman and Yury Ostromentsky".
        parts = re.split(r"\band\b|,|&", text)
        candidates = [p.strip(" .") for p in parts if p.strip()]
        return [p for p in candidates if len(p.split()) <= 4]

    def _extract_scripts(self, attrs: dict[str, Any]) -> list[str]:
        value = str(attrs.get("language_titles") or "").lower()
        scripts: list[str] = []
        if "cyr" in value or "russian" in value or "ukrainian" in value:
            scripts.append("Cyrillic")
        if "latin" in value or "english" in value or "german" in value or "french" in value:
            scripts.append("Latin")
        if "greek" in value:
            scripts.append("Greek")
        if "arab" in value:
            scripts.append("Arabic")
        if "hebrew" in value:
            scripts.append("Hebrew")
        return _unique(scripts)

    def _extract_image_url(self, attrs: dict[str, Any]) -> str | None:
        share_image = attrs.get("share_image")
        if isinstance(share_image, dict) and share_image.get("url"):
            return share_image.get("url")
        return None

    def _extract_specimen_pdf(self, attrs: dict[str, Any]) -> str | None:
        specimen = attrs.get("specimen")
        if isinstance(specimen, dict) and specimen.get("url"):
            return specimen.get("url")
        return None

    def _extract_woff(self, model: dict[str, Any]) -> str | None:
        for style in model.get("font_styles") or []:
            attrs = style.get("attributes") or {}
            for key in ("public_file", "public_file_without_encoding"):
                maybe = attrs.get(key)
                if isinstance(maybe, str) and maybe.lower().endswith((".woff", ".woff2")):
                    return maybe
        return None


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out
