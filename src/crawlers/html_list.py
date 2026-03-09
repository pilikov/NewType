from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import requests
from bs4 import BeautifulSoup, Tag

from src.crawlers.shared.text import unique_strings
from src.models import FontRelease
from src.utils import absolutize


@dataclass
class HtmlListCrawler:
    source_config: dict[str, Any]
    release_callback: Any = None

    def set_release_callback(self, callback: Any) -> None:
        self.release_callback = callback

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontRelease]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = self.source_config.get("base_url", "")

        crawl_cfg = self.source_config["crawl"]
        list_url = crawl_cfg["list_url"]
        item_selector = crawl_cfg["item_selector"]
        field_rules = crawl_cfg.get("fields", {})

        response = session.get(list_url, timeout=timeout)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        items = soup.select(item_selector)

        releases: list[FontRelease] = []
        seen_local: set[str] = set()

        for item in items:
            name = self._extract_first(item, field_rules.get("name", []), base_url)
            source_url = self._extract_first(item, field_rules.get("source_url", []), base_url)
            image_url = self._extract_first(item, field_rules.get("image_url", []), base_url)

            if not name and source_url:
                name = source_url.rsplit("/", 1)[-1].replace("-", " ").strip().title()

            if not name:
                continue

            release = FontRelease(
                source_id=source_id,
                source_name=source_name,
                source_url=source_url,
                name=name,
                styles=list(self.source_config.get("normalization", {}).get("default_styles", [])),
                authors=list(self.source_config.get("normalization", {}).get("default_authors", [])),
                scripts=list(self.source_config.get("normalization", {}).get("default_scripts", [])),
                image_url=image_url,
                woff_url=None,
                specimen_pdf_url=None,
                raw={"item_html": str(item)[:1200]},
            )

            if release.source_url:
                self._enrich_from_detail_page(
                    release=release,
                    session=session,
                    base_url=base_url,
                    timeout=timeout,
                )

            if release.release_id in seen_local:
                continue
            seen_local.add(release.release_id)
            releases.append(release)
            if self.release_callback:
                self.release_callback(release)

        return releases

    def _extract_first(self, root: Tag, rules: list[str], base_url: str) -> str | None:
        for rule in rules:
            value = self._extract_by_rule(root, rule)
            if not value:
                continue
            value = value.strip()
            if not value:
                continue
            if rule.endswith("::attr(href)") or rule == "self::attr(href)" or "url" in rule:
                return absolutize(base_url, value)
            if value.startswith("http") or value.startswith("/"):
                return absolutize(base_url, value)
            return value
        return None

    def _extract_by_rule(self, root: Tag, rule: str) -> str | None:
        if rule.startswith("self::attr(") and rule.endswith(")"):
            attr = rule[len("self::attr(") : -1]
            return root.get(attr)

        if "::attr(" in rule and rule.endswith(")"):
            selector, attr_part = rule.split("::attr(", 1)
            attr = attr_part[:-1]
            el = root.select_one(selector)
            if not el:
                return None
            return el.get(attr)

        el = root.select_one(rule)
        if not el:
            return None
        return el.get_text(" ", strip=True)

    def _enrich_from_detail_page(
        self,
        release: FontRelease,
        session: requests.Session,
        base_url: str,
        timeout: int,
    ) -> None:
        try:
            r = session.get(release.source_url, timeout=timeout)
            r.raise_for_status()
        except requests.RequestException:
            return

        soup = BeautifulSoup(r.text, "html.parser")

        if not release.image_url:
            og_img = soup.select_one("meta[property='og:image']")
            if og_img and og_img.get("content"):
                release.image_url = absolutize(base_url, og_img.get("content"))

        if not release.release_date:
            meta_date = soup.select_one(
                "meta[property='article:published_time'], meta[name='date'], meta[itemprop='datePublished']"
            )
            if meta_date and meta_date.get("content"):
                release.release_date = meta_date.get("content").strip()
            else:
                time_el = soup.select_one("time[datetime]")
                if time_el and time_el.get("datetime"):
                    release.release_date = time_el.get("datetime").strip()

        if not release.authors:
            author_values: list[str] = []
            meta_author = soup.select_one("meta[name='author'], meta[property='article:author']")
            if meta_author and meta_author.get("content"):
                author_values.append(meta_author.get("content").strip())
            for el in soup.select("[rel='author'], [class*='author'], [data-author]"):
                text = el.get_text(" ", strip=True)
                if text:
                    author_values.append(text)
            release.authors = _unique(author_values)

        detail_html = soup.get_text(" ", strip=True).lower()

        if not release.scripts:
            scripts_vocab = [
                "latin",
                "cyrillic",
                "greek",
                "arabic",
                "hebrew",
                "devanagari",
                "thai",
                "hangul",
                "hiragana",
                "katakana",
                "han",
                "georgian",
                "armenian",
            ]
            found_scripts = [s.title() for s in scripts_vocab if re.search(rf"\\b{s}\\b", detail_html)]
            release.scripts = _unique(found_scripts)

        if not release.styles:
            styles = []
            style_hint = soup.select_one("[class*='style'], [class*='weight']")
            if style_hint:
                styles.extend(
                    [
                        part.strip().title()
                        for part in re.split(r"[,/|]", style_hint.get_text(" ", strip=True))
                        if part.strip()
                    ]
                )
            release.styles = unique_strings(styles)

        if not release.specimen_pdf_url:
            pdf_link = soup.select_one("a[href$='.pdf'], a[href*='specimen']")
            if pdf_link and pdf_link.get("href"):
                release.specimen_pdf_url = absolutize(base_url, pdf_link.get("href"))

        if not release.woff_url:
            woff_link = soup.select_one("a[href$='.woff'], a[href$='.woff2']")
            if woff_link and woff_link.get("href"):
                release.woff_url = absolutize(base_url, woff_link.get("href"))

        release.raw["detail_page_enriched"] = True
