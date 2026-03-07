from __future__ import annotations

from datetime import date, datetime, timedelta
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.models import FontRelease

_SCRIPT_HINTS = {
    "latin": "Latin",
    "cyrillic": "Cyrillic",
    "greek": "Greek",
    "arabic": "Arabic",
    "hebrew": "Hebrew",
    "devanagari": "Devanagari",
    "thai": "Thai",
    "hangul": "Hangul",
    "japanese": "Japanese",
    "chinese": "Chinese",
    "korean": "Korean",
}


@dataclass
class MyFontsApiCrawler:
    source_config: dict[str, Any]
    release_callback: Any = None

    def set_release_callback(self, callback: Any) -> None:
        self.release_callback = callback

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontRelease]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = self.source_config.get("base_url", "https://www.myfonts.com")

        crawl_cfg = self.source_config.get("crawl", {})
        endpoint = crawl_cfg.get("products_endpoint", "/products.json")
        page_size = int(crawl_cfg.get("page_size", 250))
        max_pages = int(crawl_cfg.get("max_pages", 3))
        target_debut_date = crawl_cfg.get("target_debut_date")
        start_date = _parse_ymd_date(crawl_cfg.get("start_date"))
        end_date = _parse_ymd_date(crawl_cfg.get("end_date"))
        lookback_days = int(crawl_cfg.get("debut_lookback_days", 3))
        max_debut_checks = int(crawl_cfg.get("max_debut_checks", 80))
        enable_debut_enrichment = bool(crawl_cfg.get("enable_debut_enrichment", True))
        api_request_delay = float(crawl_cfg.get("api_request_delay_seconds", 0.25))
        detail_request_delay = float(crawl_cfg.get("detail_request_delay_seconds", 0.2))
        request_logging = bool(crawl_cfg.get("request_logging", True))

        self._req_no = 0
        self._first_429: tuple[int, str, float] | None = None
        self._log_path = self._init_log_file(request_logging)
        self._log(f"=== MyFonts crawl start source={source_id} ===")
        self._log(
            "config "
            f"max_pages={max_pages} page_size={page_size} start_date={start_date} end_date={end_date} "
            f"api_delay={api_request_delay}s detail_delay={detail_request_delay}s"
        )

        debut_filter = _parse_ymd_date(target_debut_date) if target_debut_date else None
        if debut_filter:
            start_date = debut_filter
            end_date = debut_filter
            max_debut_checks = 100000
        elif start_date or end_date:
            max_debut_checks = 100000
        cutoff = start_date or (date.today() - timedelta(days=lookback_days))
        filter_cutoff = (start_date - timedelta(days=2)) if start_date else None
        debut_checks_done = 0
        family_enrichment_cache: dict[str, tuple[str | None, str | None, str | None]] = {}

        releases: list[FontRelease] = []
        seen_urls: set[str] = set()

        for page in range(1, max_pages + 1):
            url = urljoin(base_url, endpoint)
            response = self._get_with_backoff(
                session=session,
                url=url,
                params={"limit": page_size, "page": page},
                timeout=timeout,
                delay_seconds=api_request_delay,
            )
            if response is None:
                if page == 1:
                    self._log("fatal: products.json unavailable on first page (likely blocked/rate-limited)")
                    raise RuntimeError("MyFonts API unavailable (rate-limited or blocked) on first page")
                break
            payload = response.json()

            products = payload.get("products", [])
            if not products:
                break

            oldest_in_page: date | None = None
            for product in products:
                source_url = urljoin(base_url, f"/products/{product.get('handle', '').strip('/')}")
                if source_url in seen_urls:
                    continue
                seen_urls.add(source_url)

                name = (product.get("title") or "").strip()
                if not name:
                    continue

                scripts = self._extract_scripts(product)
                image_url = self._extract_image_url(product)
                specimen_pdf_url, woff_url = self._extract_asset_urls(product)
                release_date = (product.get("published_at") or product.get("created_at") or None)
                published_dt = _parse_iso_datetime(release_date)
                published_day = published_dt.date() if published_dt else None
                if published_day:
                    oldest_in_page = published_day if oldest_in_page is None else min(oldest_in_page, published_day)
                if end_date and published_day and published_day > (end_date + timedelta(days=2)):
                    continue
                if start_date and published_day and published_day < (start_date - timedelta(days=2)):
                    continue

                collection_url = None
                debut_date_iso = None
                promo_image_url = None
                debut_day = None
                family_id = self._extract_family_id(product)
                if family_id and family_id in family_enrichment_cache:
                    collection_url, debut_date_iso, promo_image_url = family_enrichment_cache[family_id]
                    debut_day = _parse_ymd_date(debut_date_iso)
                    if promo_image_url:
                        image_url = promo_image_url
                elif enable_debut_enrichment and debut_checks_done < max_debut_checks:
                    collection_url, debut_date_iso, promo_image_url = self._extract_debut_from_product_page(
                        session=session,
                        product_url=source_url,
                        base_url=base_url,
                        timeout=timeout,
                        detail_request_delay=detail_request_delay,
                    )
                    debut_checks_done += 1
                    debut_day = _parse_ymd_date(debut_date_iso)
                    if promo_image_url:
                        image_url = promo_image_url
                    if family_id:
                        family_enrichment_cache[family_id] = (collection_url, debut_date_iso, promo_image_url)

                effective_release_date = debut_date_iso or release_date
                effective_day = debut_day or published_day
                if start_date and effective_day and effective_day < start_date:
                    continue
                if end_date and effective_day and effective_day > end_date:
                    continue
                if debut_filter and debut_date_iso != debut_filter.isoformat():
                    continue

                release = FontRelease(
                    source_id=source_id,
                    source_name=source_name,
                    source_url=collection_url or source_url,
                    name=name,
                    styles=[],
                    authors=[(product.get("vendor") or "").strip()] if product.get("vendor") else [],
                    scripts=scripts,
                    release_date=effective_release_date,
                    image_url=image_url,
                    woff_url=woff_url,
                    specimen_pdf_url=specimen_pdf_url,
                    raw={
                        "id": product.get("id"),
                        "handle": product.get("handle"),
                        "tags": product.get("tags"),
                        "updated_at": product.get("updated_at"),
                        "product_url": source_url,
                        "collection_url": collection_url,
                        "myfonts_debut_date": debut_date_iso,
                    },
                )
                releases.append(release)
                if self.release_callback:
                    self.release_callback(release)

            if len(products) < page_size:
                break
            if not debut_filter and oldest_in_page and oldest_in_page < cutoff:
                break
            if filter_cutoff and oldest_in_page and oldest_in_page < filter_cutoff:
                break

        self._log(
            f"summary releases={len(releases)} first_429={self._first_429} "
            f"log_file={self._log_path if self._log_path else 'disabled'}"
        )
        self._log("=== MyFonts crawl end ===")
        return releases

    def _extract_scripts(self, product: dict[str, Any]) -> list[str]:
        tags = product.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        normalized_tags = " ".join(str(t).lower() for t in tags)
        body = str(product.get("body_html") or "").lower()

        found: list[str] = []
        for needle, label in _SCRIPT_HINTS.items():
            if needle in normalized_tags or re.search(rf"\b{needle}\b", body):
                found.append(label)
        return sorted(set(found))

    def _extract_image_url(self, product: dict[str, Any]) -> str | None:
        images = product.get("images") or []
        if images and isinstance(images[0], dict):
            return images[0].get("src")

        for variant in product.get("variants") or []:
            featured = variant.get("featured_image") if isinstance(variant, dict) else None
            if isinstance(featured, dict) and featured.get("src"):
                return featured.get("src")
        return None

    def _extract_asset_urls(self, product: dict[str, Any]) -> tuple[str | None, str | None]:
        body = str(product.get("body_html") or "")
        links = re.findall(r'href=["\']([^"\']+)["\']', body, flags=re.IGNORECASE)

        pdf_url = None
        woff_url = None
        for link in links:
            lower = link.lower()
            if not pdf_url and lower.endswith(".pdf"):
                pdf_url = link
            if not woff_url and (lower.endswith(".woff") or lower.endswith(".woff2")):
                woff_url = link
        return pdf_url, woff_url

    def _extract_family_id(self, product: dict[str, Any]) -> str | None:
        tags = product.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        for tag in tags:
            value = str(tag).strip()
            if value.startswith("pim:familyId:"):
                return value.split(":", 2)[-1]
        return None

    def _extract_debut_from_product_page(
        self,
        session: requests.Session,
        product_url: str,
        base_url: str,
        timeout: int,
        detail_request_delay: float,
    ) -> tuple[str | None, str | None, str | None]:
        try:
            page = self._get_with_backoff(
                session=session,
                url=product_url,
                timeout=timeout,
                delay_seconds=detail_request_delay,
            )
            if page is None:
                return None, None, None
        except requests.RequestException:
            return None, None, None

        soup = BeautifulSoup(page.text, "html.parser")

        collection_url = None
        for a in soup.select("a[href*='/collections/']"):
            href = (a.get("href") or "").strip().strip("'")
            if "/collections/" not in href:
                continue
            if "-font-" not in href:
                continue
            collection_url = urljoin(base_url, href)
            break

        if not collection_url:
            return None, None, None

        try:
            collection_page = self._get_with_backoff(
                session=session,
                url=collection_url,
                timeout=timeout,
                delay_seconds=detail_request_delay,
            )
            if collection_page is None:
                return collection_url, None, None
        except requests.RequestException:
            return collection_url, None, None

        collection_html = collection_page.text
        collection_soup = BeautifulSoup(collection_html, "html.parser")
        promo_image_url = self._extract_promo_image_url(collection_soup, base_url)
        text = collection_soup.get_text(" ", strip=True)
        match = re.search(r"MyFonts\s+debut\s*:\s*([A-Za-z]{3}\s+\d{1,2},\s+\d{4})", text, re.IGNORECASE)
        if not match:
            # Fallback for cases where the label is present in scripts/HTML but not in plain extracted text.
            match = re.search(
                r"MyFonts(?:\s|&nbsp;)+debut\s*:\s*([A-Za-z]{3}\s+\d{1,2},\s+\d{4})",
                collection_html,
                re.IGNORECASE,
            )
        if (not match) or (not promo_image_url):
            retry_match, retry_image = self._retry_collection_parse_once(
                session=session,
                collection_url=collection_url,
                base_url=base_url,
                timeout=timeout,
                detail_request_delay=detail_request_delay,
            )
            if not match and retry_match:
                match = retry_match
            if not promo_image_url and retry_image:
                promo_image_url = retry_image
        if not match:
            return collection_url, None, promo_image_url

        parsed = _parse_mon_dd_yyyy(match.group(1))
        return collection_url, parsed.isoformat() if parsed else None, promo_image_url

    def _extract_promo_image_url(self, soup: BeautifulSoup, base_url: str) -> str | None:
        def pick_from_srcset(srcset: str | None) -> str | None:
            if not srcset:
                return None
            for chunk in srcset.split(","):
                candidate = chunk.strip().split(" ", 1)[0].strip()
                if "/images/pim/" in candidate:
                    return urljoin(base_url, candidate)
            return None

        for node in soup.select("img[src],img[data-src],img[srcset],source[srcset]"):
            src = (
                (node.get("src") or "").strip()
                or (node.get("data-src") or "").strip()
            )
            if "/images/pim/" in src:
                return urljoin(base_url, src)
            from_srcset = pick_from_srcset((node.get("srcset") or "").strip())
            if from_srcset:
                return from_srcset
            from_data_srcset = pick_from_srcset((node.get("data-srcset") or "").strip())
            if from_data_srcset:
                return from_data_srcset

        return None

    def _retry_collection_parse_once(
        self,
        session: requests.Session,
        collection_url: str,
        base_url: str,
        timeout: int,
        detail_request_delay: float,
    ) -> tuple[re.Match[str] | None, str | None]:
        try:
            retry_page = self._get_with_backoff(
                session=session,
                url=collection_url,
                timeout=timeout,
                delay_seconds=max(0.1, detail_request_delay),
            )
            if retry_page is None:
                return None, None
        except requests.RequestException:
            return None, None

        retry_html = retry_page.text
        retry_soup = BeautifulSoup(retry_html, "html.parser")
        retry_image = self._extract_promo_image_url(retry_soup, base_url)
        retry_text = retry_soup.get_text(" ", strip=True)
        retry_match = re.search(
            r"MyFonts\s+debut\s*:\s*([A-Za-z]{3}\s+\d{1,2},\s+\d{4})",
            retry_text,
            re.IGNORECASE,
        )
        if not retry_match:
            retry_match = re.search(
                r"MyFonts(?:\s|&nbsp;)+debut\s*:\s*([A-Za-z]{3}\s+\d{1,2},\s+\d{4})",
                retry_html,
                re.IGNORECASE,
            )
        return retry_match, retry_image

    def _get_with_backoff(
        self,
        session: requests.Session,
        url: str,
        timeout: int,
        params: dict[str, Any] | None = None,
        delay_seconds: float = 1.5,
    ) -> requests.Response | None:
        retries = 6
        for attempt in range(retries):
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            self._req_no += 1
            req_id = self._req_no
            t0 = time.time()
            response = session.get(url, params=params, timeout=timeout)
            elapsed = time.time() - t0
            self._log(f"#{req_id} attempt={attempt+1}/{retries} status={response.status_code} {elapsed:.3f}s url={response.url}")
            if response.status_code != 429:
                response.raise_for_status()
                return response
            if self._first_429 is None:
                self._first_429 = (req_id, response.url, elapsed)
                self._log(f"first_429 req={req_id} url={response.url}")
            time.sleep(2.0 + attempt * 3.0)
        self._log(f"max_retries_exhausted url={url}")
        return None

    def _init_log_file(self, enabled: bool) -> str | None:
        if not enabled:
            return None
        now = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = Path("state") / f"myfonts_run_{now}.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    def _log(self, message: str) -> None:
        if not self._log_path:
            return
        stamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {message}\n")


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _parse_mon_dd_yyyy(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%b %d, %Y").date()
    except ValueError:
        return None


def _parse_ymd_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
