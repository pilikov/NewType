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
        seen_family_keys: set[str] = set()  # один релиз на семью: по collection_url (норм.) или family_key из имени/slug

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

                # Исключаем: bundles; products без ссылки на семью; product с семьёй, но релиз семьи в другую дату
                if detail.get("is_package_product"):
                    continue
                is_product_page = "/products/" in font_url.lower()
                if is_product_page and not detail.get("collection_url"):
                    continue
                family_debut = detail.get("family_debut")
                product_debut = detail.get("product_debut")
                if (
                    is_product_page
                    and detail.get("collection_url")
                    and family_debut is not None
                    and product_debut is not None
                    and product_debut != family_debut
                ):
                    continue

                family_key = self._canonical_family_key(
                    collection_url=detail.get("collection_url"),
                    product_url=font_url,
                    name=detail.get("name") or self._name_from_url(font_url),
                    base_url=base_url,
                )
                if not family_key or family_key in seen_family_keys:
                    continue
                seen_family_keys.add(family_key)

                source_url = detail.get("source_url") or font_url
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
        for a in soup.select("a[href*='/products/']"):
            href = (a.get("href") or "").strip().strip("'")
            if not href or "whats-new" in href.lower():
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

    def _normalize_collection_url(self, url: str) -> str:
        """Один ключ на коллекцию: без trailing slash, lowercase path."""
        if not url or not url.strip():
            return ""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url.strip())
            path = (parsed.path or "").rstrip("/").lower()
            return f"{parsed.scheme or 'https'}://{parsed.netloc or ''}{path}" if path else ""
        except Exception:
            return url.strip().lower().rstrip("/").split("?")[0].rstrip("/")

    def _canonical_family_key(
        self,
        collection_url: str | None,
        product_url: str,
        name: str,
        base_url: str,
    ) -> str | None:
        """Ключ семьи для дедупа: один релиз на семью. collection_url (норм.) или имя/slug."""
        if collection_url:
            norm = self._normalize_collection_url(collection_url)
            if norm:
                return f"url:{norm}"
        key_from_name = self._family_key_from_name(name)
        if key_from_name:
            return f"name:{key_from_name}"
        key_from_slug = self._family_key_from_product_slug(product_url)
        if key_from_slug:
            return f"name:{key_from_slug}"
        return None

    def _family_key_from_product_slug(self, product_url: str) -> str:
        """Из slug продукта (calavera-complete-family-package-1118786) вытащить базовое имя семьи."""
        if not product_url or "/products/" not in product_url:
            return ""
        try:
            parts = product_url.rstrip("/").split("/products/")
            if len(parts) < 2:
                return ""
            slug = parts[-1].split("?")[0].lower()
            for suffix in ("-package", "-bundle", "-family"):
                if slug.endswith(suffix):
                    slug = slug[: -len(suffix)].strip("-")
            id_match = re.search(r"-(\d+)$", slug)
            if id_match:
                slug = slug[: id_match.start()].strip("-")
            if not slug:
                return ""
            words = slug.replace("-", " ").split()
            seen: set[str] = set()
            out: list[str] = []
            for w in words:
                if w in seen:
                    break
                seen.add(w)
                out.append(w)
            base = " ".join(out).strip() if out else ""
            return self._family_key_from_name(base) if base else ""
        except Exception:
            return ""

    def _family_key_from_name(self, name: str) -> str:
        """Нормализуем название в ключ семьи для дедупа, когда collection_url не найден."""
        if not name or not name.strip():
            return ""
        key = name.strip().lower()
        if " + " in key:
            key = key.split(" + ")[0].strip()
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
            " rough italic",
            " liner",
            " chalk",
            " chalky",
            " italic",
            " semibold",
            " extralight",
            " condensed",
            " extended",
            " narrow",
            " wide",
            " rounded",
            " stencil",
            " display",
            " text",
            " caption",
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

    def _is_subcollection_url(self, url: str) -> bool:
        """URL коллекции — под-набор (Upright, Slanted, Pack), не основная семья."""
        u = (url or "").lower()
        return any(x in u for x in ("/upright", "upright-", "/slanted", "slanted-", "pack-of-", "-pack-"))

    def _is_subcollection_link(self, href: str, link_text: str) -> bool:
        """Ссылка на под-набор (Upright, Slanted, Pack of N fonts), не на основную семью."""
        href_lower = href.lower()
        text_lower = (link_text or "").lower()
        if "upright" in href_lower or "upright" in text_lower:
            return True
        if "slanted" in href_lower or "slanted" in text_lower:
            return True
        if "pack-of" in href_lower or "pack of" in text_lower:
            return True
        if re.search(r"\b\d+\s*fonts?\b", text_lower):
            return True
        return False

    def _extract_collection_url(self, soup: BeautifulSoup, base_url: str) -> str | None:
        # 1) Явная ссылка «Back To Family Page» — только если href валидный (/collections/...)
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip().strip("'")
            if not href or "whats-new" in href or "foundry" in href.lower():
                continue
            text = (a.get_text() or "").strip().lower()
            if "family page" not in text and "back to family" not in text:
                continue
            if "/collections/" in href:
                return urljoin(base_url, href)
        # 2) Любая /collections/ с -font- в path, кроме под-наборов (не угадываем URL — страница может быть «no longer available»)
        main_family_url: str | None = None
        for a in soup.select("a[href*='/collections/']"):
            href = (a.get("href") or "").strip().strip("'")
            if "/collections/" not in href or "whats-new" in href or "foundry" in href.lower():
                continue
            if "-font-" not in href:
                continue
            if self._is_subcollection_link(href, a.get_text() or ""):
                continue
            full = urljoin(base_url, href)
            if main_family_url is None:
                main_family_url = full
        return main_family_url

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

        url_lower = font_url.lower()
        is_collection_page = (
            "/collections/" in url_lower and "-font-" in url_lower and "whats-new" not in url_lower
        )
        is_subcollection = self._is_subcollection_url(font_url)

        if is_collection_page and not is_subcollection:
            collection_url = urljoin(base_url, font_url.rstrip("/"))
            debut_date = product_debut
            source_url = font_url
        else:
            collection_url = self._extract_collection_url(soup, base_url)
            if is_collection_page and not collection_url:
                collection_url = urljoin(base_url, font_url.rstrip("/"))
            debut_date = product_debut
            source_url = font_url
        family_debut: date | None = None
        if collection_url:
            current_norm = self._normalize_collection_url(font_url)
            target_norm = self._normalize_collection_url(collection_url)
            if current_norm != target_norm:
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
        is_package = self._is_package_product(font_url, name or "")

        return {
            "name": name,
            "authors": unique_strings(authors),
            "scripts": unique_strings(scripts),
            "debut_raw": debut_match.group(1) if debut_match else None,
            "debut_date": debut_date,
            "product_debut": product_debut,
            "family_debut": family_debut,
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
