from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.crawlers.shared.dates import parse_mon_dd_yyyy, parse_ymd
from src.crawlers.shared.text import unique_strings
from src.models import FontRelease


@dataclass
class MyFontsWhatsNewCrawler:
    source_config: dict[str, Any]
    release_callback: Any = None

    def set_release_callback(self, callback: Any) -> None:
        self.release_callback = callback

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontRelease]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = self.source_config.get("base_url", "https://www.myfonts.com")
        crawl_cfg = self.source_config.get("crawl", {})

        start_date = parse_ymd(crawl_cfg.get("start_date"))
        end_date = parse_ymd(crawl_cfg.get("end_date")) or start_date
        if not start_date:
            # Default daily mode: only today's debut.
            today = date.today()
            start_date = today
            end_date = today

        max_pages = int(crawl_cfg.get("max_pages", 30))

        releases: list[FontRelease] = []
        seen_urls: set[str] = set()
        seen_source_urls: set[str] = set()  # по collection_url или product url
        seen_family_keys: set[str] = set()  # когда collection не найден — дедуп по нормализованному имени семьи

        for page in range(1, max_pages + 1):
            page_url = f"{base_url}/collections/whats-new?page={page}"
            response = session.get(page_url, timeout=timeout)
            if response.status_code == 429:
                raise RuntimeError("MyFonts blocked request with HTTP 429 on What's New")
            response.raise_for_status()

            font_urls = self._extract_font_urls(response.text, base_url)
            if not font_urls:
                break

            stop_due_to_older_date = False
            for font_url in font_urls:
                if font_url in seen_urls:
                    continue
                seen_urls.add(font_url)

                detail = self._fetch_font_detail(session, font_url, base_url, timeout)
                if not detail:
                    continue

                debut = detail.get("debut_date")
                if not debut:
                    continue

                if debut < start_date:
                    stop_due_to_older_date = True
                    break
                if debut > end_date:
                    continue

                source_url = detail.get("source_url") or font_url
                if source_url in seen_source_urls:
                    continue
                # Если collection не нашли, один пакет + несколько стилей дают один релиз на семью
                if not detail.get("collection_url"):
                    family_key = self._family_key_from_name(detail.get("name") or self._name_from_url(font_url))
                    if family_key and family_key in seen_family_keys:
                        continue
                    if family_key:
                        seen_family_keys.add(family_key)
                seen_source_urls.add(source_url)

                raw_payload = {
                    "myfonts_debut_raw": detail.get("debut_raw"),
                    "myfonts_debut_date": debut.isoformat(),  # для сайта: группировка по неделям по raw.myfonts_debut_date
                    "product_url": font_url,
                    "collection_url": detail.get("collection_url"),
                    "is_package_product": detail.get("is_package_product", False),
                }
                release = FontRelease(
                    source_id=source_id,
                    source_name=source_name,
                    source_url=source_url,
                    name=detail.get("name") or self._name_from_url(font_url),
                    styles=[],
                    authors=detail.get("authors") or [],
                    scripts=detail.get("scripts") or [],
                    release_date=debut.isoformat(),
                    image_url=detail.get("image_url"),
                    woff_url=detail.get("woff_url"),
                    specimen_pdf_url=detail.get("specimen_pdf_url"),
                    raw=raw_payload,
                )
                releases.append(release)
                if self.release_callback:
                    self.release_callback(release)

            if stop_due_to_older_date:
                break

        return releases

    def _extract_font_urls(self, html: str, base_url: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        urls: list[str] = []

        for a in soup.select("a[href*='/collections/'][href*='-font-']"):
            href = (a.get("href") or "").strip().strip("'")
            if not href:
                continue
            urls.append(urljoin(base_url, href))

        # Fallback for escaped URLs inside inline JS payloads.
        for path in re.findall(r"/collections/[a-z0-9\-]+-font-[a-z0-9\-]+", html, flags=re.IGNORECASE):
            urls.append(urljoin(base_url, path))

        uniq: list[str] = []
        seen: set[str] = set()
        for url in urls:
            key = url.lower().rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            uniq.append(url.rstrip("/"))
        return uniq

    def _family_key_from_name(self, name: str) -> str:
        """Нормализуем название в ключ семьи для дедупа, когда collection_url не найден."""
        if not name or not name.strip():
            return ""
        key = name.strip().lower()
        for suffix in (
            " complete family",
            " family package",
            " package",
            " bundle",
            " one",
            " two",
            " three",
            " four",
            " five",
            " six",
            " flaca",
            " fina",
            " thin",
            " light",
            " regular",
            " bold",
            " black",
        ):
            if key.endswith(suffix):
                key = key[: -len(suffix)].strip()
        return key or ""

    def _is_package_product(self, font_url: str, name: str) -> bool:
        url_lower = font_url.lower()
        name_lower = (name or "").lower()
        if "-package-" in url_lower or "bundle" in url_lower:
            return True
        if "package" in name_lower or "bundle" in name_lower:
            return True
        return False

    def _extract_collection_url(self, soup: BeautifulSoup, base_url: str) -> str | None:
        # Сначала ищем явную ссылку «Back To Family Page» на коллекцию семьи (не foundry)
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip().strip("'")
            if not href or "whats-new" in href:
                continue
            text = (a.get_text() or "").strip().lower()
            if "family page" not in text and "back to family" not in text:
                continue
            if "/collections/" in href and "foundry" not in href.lower():
                return urljoin(base_url, href)
        # Обычные ссылки на /collections/: семья обычно ...-font-...; исключаем foundry
        for a in soup.select("a[href*='/collections/']"):
            href = (a.get("href") or "").strip().strip("'")
            if "/collections/" not in href or "whats-new" in href or "foundry" in href.lower():
                continue
            return urljoin(base_url, href)
        return None

    def _fetch_collection_debut(
        self, session: requests.Session, collection_url: str, base_url: str, timeout: int
    ) -> tuple[date | None, str | None, str | None]:
        """Возвращает (debut_date, image_url, name) со страницы семьи (collection)."""
        try:
            response = session.get(collection_url, timeout=timeout)
            if response.status_code == 429:
                return None, None, None
            response.raise_for_status()
        except requests.RequestException:
            return None, None, None
        html = response.text
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)
        match = re.search(
            r"MyFonts\s+debut\s*:\s*([A-Za-z]{3}\s+\d{1,2},\s+\d{4})",
            text,
            flags=re.IGNORECASE,
        )
        if not match:
            match = re.search(
                r"MyFonts(?:\s|&nbsp;)+debut\s*:\s*([A-Za-z]{3}\s+\d{1,2},\s+\d{4})",
                html,
                re.IGNORECASE,
            )
        debut_date = parse_mon_dd_yyyy(match.group(1)) if match else None
        image_url = None
        og = soup.select_one("meta[property='og:image']")
        if og and og.get("content"):
            image_url = og.get("content").strip()
        name = None
        og_title = soup.select_one("meta[property='og:title']")
        if og_title and og_title.get("content"):
            raw = (og_title.get("content") or "").strip()
            name = re.sub(r"\s*-\s*Font from.*$", "", raw).strip()
        return debut_date, image_url, name

    def _fetch_font_detail(
        self, session: requests.Session, font_url: str, base_url: str, timeout: int
    ) -> dict[str, Any] | None:
        try:
            response = session.get(font_url, timeout=timeout)
            if response.status_code == 429:
                return None
            response.raise_for_status()
        except requests.RequestException:
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        text = soup.get_text(" ", strip=True)

        debut_match = re.search(
            r"MyFonts\s+debut\s*:\s*([A-Za-z]{3}\s+\d{1,2},\s+\d{4})",
            text,
            flags=re.IGNORECASE,
        )
        product_debut = parse_mon_dd_yyyy(debut_match.group(1)) if debut_match else None

        name = None
        og_title = soup.select_one("meta[property='og:title']")
        if og_title and og_title.get("content"):
            raw = og_title.get("content").strip()
            name = re.sub(r"\s*-\s*Font from.*$", "", raw).strip()
        if not name:
            h1 = soup.select_one("h1")
            if h1:
                name = h1.get_text(" ", strip=True)

        authors: list[str] = []
        publisher = re.search(r"Publisher\s*:\s*([^\n]+?)\s+(?:Foundry|Design Owner|MyFonts debut)", text)
        if publisher:
            maybe = publisher.group(1).strip()
            if maybe:
                authors.append(maybe)

        scripts: list[str] = []
        lower = text.lower()
        for token, label in [
            ("latin", "Latin"),
            ("cyrillic", "Cyrillic"),
            ("greek", "Greek"),
            ("arabic", "Arabic"),
            ("hebrew", "Hebrew"),
        ]:
            if re.search(rf"\\b{token}\\b", lower):
                scripts.append(label)

        image_url = None
        og_image = soup.select_one("meta[property='og:image']")
        if og_image and og_image.get("content"):
            image_url = og_image.get("content").strip()

        specimen_pdf_url = None
        woff_url = None
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            low = href.lower()
            if not specimen_pdf_url and low.endswith(".pdf"):
                specimen_pdf_url = href
            if not woff_url and (low.endswith(".woff") or low.endswith(".woff2")):
                woff_url = href

        collection_url = self._extract_collection_url(soup, base_url)
        debut_date = product_debut
        source_url = font_url
        is_package = self._is_package_product(font_url, name or "")

        if collection_url:
            family_debut, family_image, family_name = self._fetch_collection_debut(
                session, collection_url, base_url, timeout
            )
            if family_debut is not None:
                debut_date = family_debut
                source_url = collection_url
                if family_image:
                    image_url = family_image
                if family_name:
                    name = family_name

        return {
            "name": name,
            "authors": unique_strings(authors),
            "scripts": unique_strings(scripts),
            "debut_raw": debut_match.group(1) if debut_match else None,
            "debut_date": debut_date,
            "image_url": image_url,
            "specimen_pdf_url": specimen_pdf_url,
            "woff_url": woff_url,
            "source_url": source_url,
            "collection_url": collection_url,
            "is_package_product": is_package,
        }

    def _name_from_url(self, url: str) -> str:
        slug = url.rstrip("/").rsplit("/", 1)[-1]
        slug = re.sub(r"-font-.*$", "", slug)
        return slug.replace("-", " ").title().strip() or "Unknown"
