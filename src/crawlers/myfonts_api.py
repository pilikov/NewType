from __future__ import annotations

import json
from datetime import date, datetime, timedelta
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

from src.crawlers.shared.dates import parse_iso_datetime, parse_mon_dd_yyyy, parse_ymd
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
_SCRIPT_ORDER = [
    "Latin",
    "Cyrillic",
    "Greek",
    "Arabic",
    "Hebrew",
    "Devanagari",
    "Thai",
    "Japanese",
    "Korean",
    "Chinese",
]
_LANGUAGE_TO_SCRIPT = {
    "arabic": "Arabic",
    "persian": "Arabic",
    "urdu": "Arabic",
    "pashto": "Arabic",
    "kurdish": "Arabic",
    "uyghur": "Arabic",
    "uighur": "Arabic",
    "sindhi": "Arabic",
    "greek": "Greek",
    "hebrew": "Hebrew",
    "yiddish": "Hebrew",
    "russian": "Cyrillic",
    "ukrainian": "Cyrillic",
    "belarusian": "Cyrillic",
    "bulgarian": "Cyrillic",
    "serbian": "Cyrillic",
    "macedonian": "Cyrillic",
    "kazakh": "Cyrillic",
    "kyrgyz": "Cyrillic",
    "tajik": "Cyrillic",
    "mongolian": "Cyrillic",
    "hindi": "Devanagari",
    "marathi": "Devanagari",
    "nepali": "Devanagari",
    "sanskrit": "Devanagari",
    "thai": "Thai",
    "japanese": "Japanese",
    "korean": "Korean",
    "chinese": "Chinese",
    "mandarin": "Chinese",
    "cantonese": "Chinese",
}
_LANGUAGE_TO_SCRIPT_STRONG = {
    "arabic": "Arabic",
    "persian": "Arabic",
    "urdu": "Arabic",
    "pashto": "Arabic",
    "uyghur": "Arabic",
    "uighur": "Arabic",
    "sindhi": "Arabic",
    "greek": "Greek",
    "hebrew": "Hebrew",
    "yiddish": "Hebrew",
    "russian": "Cyrillic",
    "ukrainian": "Cyrillic",
    "belarusian": "Cyrillic",
    "bulgarian": "Cyrillic",
    "macedonian": "Cyrillic",
    "kazakh": "Cyrillic",
    "kyrgyz": "Cyrillic",
    "tajik": "Cyrillic",
    "mongolian": "Cyrillic",
    "hindi": "Devanagari",
    "marathi": "Devanagari",
    "nepali": "Devanagari",
    "sanskrit": "Devanagari",
    "thai": "Thai",
    "japanese": "Japanese",
    "korean": "Korean",
    "chinese": "Chinese",
    "mandarin": "Chinese",
    "cantonese": "Chinese",
}
_SUCCESS_PROFILE_PATH = Path("state") / "myfonts_success_profile.json"
_CHECKPOINT_PATH = Path("state") / "myfonts_crawl_checkpoint.json"


@dataclass
class _CrawlerResponse:
    status_code: int
    url: str
    text: str

    def json(self) -> dict[str, Any]:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code} for {self.url}")


class _PlaywrightHttpClient:
    def __init__(
        self,
        *,
        user_agent: str,
        accept_language: str,
        headless: bool,
        storage_state_path: str | None,
    ) -> None:
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=headless)
        context_args: dict[str, Any] = {
            "user_agent": user_agent,
            "locale": "en-US",
            "extra_http_headers": {"Accept-Language": accept_language},
        }
        if storage_state_path and Path(storage_state_path).exists():
            context_args["storage_state"] = storage_state_path
        self._context = self._browser.new_context(**context_args)
        self._page = self._context.new_page()

    def close(self) -> None:
        self._context.close()
        self._browser.close()
        self._pw.stop()

    def get(self, *, url: str, params: dict[str, Any] | None, timeout: int) -> _CrawlerResponse:
        full_url = _merge_url_params(url, params)
        response = self._page.goto(full_url, wait_until="domcontentloaded", timeout=timeout * 1000)
        if "tab=techSpecs" in full_url:
            try:
                self._page.wait_for_load_state("networkidle", timeout=min(timeout * 1000, 3000))
            except Exception:
                pass
        if response is None:
            return _CrawlerResponse(status_code=599, url=full_url, text="")
        body = ""
        if not body:
            try:
                body = self._page.content()
            except Exception:
                body = ""
        if not body:
            try:
                body = response.text()
            except Exception:
                body = ""
        return _CrawlerResponse(status_code=response.status, url=response.url, text=body)


def _merge_url_params(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    split = urlsplit(url)
    base_pairs = parse_qsl(split.query, keep_blank_values=True)
    for key, value in params.items():
        base_pairs.append((str(key), str(value)))
    query = urlencode(base_pairs)
    return urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment))


@dataclass
class MyFontsApiCrawler:
    source_config: dict[str, Any]
    release_callback: Any = None
    _language_script_signal_mode: str = "balanced"

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
        start_date = parse_ymd(crawl_cfg.get("start_date"))
        end_date = parse_ymd(crawl_cfg.get("end_date"))
        lookback_days = int(crawl_cfg.get("debut_lookback_days", 3))
        max_debut_checks = int(crawl_cfg.get("max_debut_checks", 80))
        enable_debut_enrichment = bool(crawl_cfg.get("enable_debut_enrichment", True))
        enable_tech_specs_script_enrichment = bool(crawl_cfg.get("enable_tech_specs_script_enrichment", True))
        max_tech_specs_checks = int(crawl_cfg.get("max_tech_specs_checks", 40))
        api_request_delay = float(crawl_cfg.get("api_request_delay_seconds", 0.25))
        detail_request_delay = float(crawl_cfg.get("detail_request_delay_seconds", 0.2))
        reuse_last_success_profile = bool(crawl_cfg.get("reuse_last_success_profile", True))
        request_logging = bool(crawl_cfg.get("request_logging", True))
        always_enrich_packages = bool(crawl_cfg.get("always_enrich_packages", True))
        browser_mode = bool(crawl_cfg.get("browser_mode", False))
        browser_headless = bool(crawl_cfg.get("browser_headless", True))
        browser_storage_state_path = str(crawl_cfg.get("browser_storage_state_path", "")).strip() or None
        force_fresh_run = bool(crawl_cfg.get("force_fresh_run", False))
        start_page_override = int(crawl_cfg.get("start_page_override", 0) or 0)
        language_script_signal_mode = str(crawl_cfg.get("language_script_signal_mode", "balanced")).strip().lower()
        if language_script_signal_mode not in {"balanced", "strong"}:
            language_script_signal_mode = "balanced"
        self._language_script_signal_mode = language_script_signal_mode

        if reuse_last_success_profile:
            profile = self._load_success_profile()
            if profile:
                api_request_delay = float(profile.get("api_request_delay_seconds", api_request_delay))
                detail_request_delay = float(profile.get("detail_request_delay_seconds", detail_request_delay))
                max_debut_checks = int(profile.get("max_debut_checks", max_debut_checks))
                max_tech_specs_checks = int(profile.get("max_tech_specs_checks", max_tech_specs_checks))

        self._req_no = 0
        self._first_429: tuple[int, str, float] | None = None
        self._log_path = self._init_log_file(request_logging)
        checkpoint_signature = self._build_checkpoint_signature(
            page_size=page_size,
            start_date=start_date.isoformat() if start_date else None,
            end_date=end_date.isoformat() if end_date else None,
            target_debut_date=target_debut_date,
            enable_debut_enrichment=enable_debut_enrichment,
            enable_tech_specs_script_enrichment=enable_tech_specs_script_enrichment,
            language_script_signal_mode=self._language_script_signal_mode,
        )
        checkpoint = self._load_or_create_checkpoint(
            signature=checkpoint_signature,
            max_pages=max_pages,
            force_fresh_run=force_fresh_run,
        )
        start_page = int(checkpoint.get("next_page") or 1)
        if start_page_override > 1:
            start_page = start_page_override
        if start_page < 1:
            start_page = 1
        self._log(f"=== MyFonts crawl start source={source_id} ===")
        self._log(
            "config "
            f"max_pages={max_pages} page_size={page_size} start_date={start_date} end_date={end_date} "
            f"api_delay={api_request_delay}s detail_delay={detail_request_delay}s "
            f"max_debut_checks={max_debut_checks} max_tech_specs_checks={max_tech_specs_checks} "
            f"reuse_success_profile={reuse_last_success_profile} "
            f"always_enrich_packages={always_enrich_packages} "
            f"language_script_signal_mode={self._language_script_signal_mode} "
            f"force_fresh_run={force_fresh_run} start_page={start_page} "
            f"browser_mode={browser_mode} browser_headless={browser_headless} "
            f"browser_storage_state_path={browser_storage_state_path or '-'}"
        )

        self._browser_client: _PlaywrightHttpClient | None = None
        if browser_mode:
            try:
                self._browser_client = _PlaywrightHttpClient(
                    user_agent=str(session.headers.get("User-Agent", "")),
                    accept_language=str(session.headers.get("Accept-Language", "en-US,en;q=0.9")),
                    headless=browser_headless,
                    storage_state_path=browser_storage_state_path,
                )
                self._log("browser_client=ready transport=playwright")
            except Exception as exc:
                self._log(f"browser_client=failed transport=requests reason={exc}")

        debut_filter = parse_ymd(target_debut_date) if target_debut_date else None
        if debut_filter:
            start_date = debut_filter
            end_date = debut_filter
        # In date-range modes we rely on MyFonts debut (from detail pages), so published_at is only a weak proxy.
        # Do not prune candidates/pages early by published_at when debut enrichment is enabled.
        use_published_proxy_filters = not (
            enable_debut_enrichment and (debut_filter or start_date or end_date)
        )
        cutoff = start_date or (date.today() - timedelta(days=lookback_days))
        filter_cutoff = (start_date - timedelta(days=2)) if (start_date and use_published_proxy_filters) else None
        debut_checks_done = 0
        tech_specs_checks_done = 0
        family_enrichment_cache: dict[str, tuple[str | None, str | None, str | None, list[str], list[str]]] = {}

        releases: list[FontRelease] = []
        seen_urls: set[str] = set()

        try:
            exhausted_page_cap = True
            stop_reason = "max_pages"
            last_oldest_in_page: date | None = None
            for page in range(start_page, max_pages + 1):
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
                try:
                    payload = response.json()
                except Exception:
                    self._log(f"invalid_json status={response.status_code} url={response.url}")
                    if page == 1:
                        raise RuntimeError("MyFonts API returned non-JSON response on first page")
                    break

                products = payload.get("products", [])
                if not products:
                    exhausted_page_cap = False
                    stop_reason = "empty_page"
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
                    published_dt = parse_iso_datetime(release_date)
                    published_day = published_dt.date() if published_dt else None
                    if published_day:
                        oldest_in_page = published_day if oldest_in_page is None else min(oldest_in_page, published_day)
                    if use_published_proxy_filters:
                        if end_date and published_day and published_day > (end_date + timedelta(days=2)):
                            continue
                        if start_date and published_day and published_day < (start_date - timedelta(days=2)):
                            continue

                    collection_url = None
                    debut_date_iso = None
                    promo_image_url = None
                    tech_specs_scripts: list[str] = []
                    tech_specs_supported_languages: list[str] = []
                    debut_day = None
                    family_id = self._extract_family_id(product)
                    if family_id and family_id in family_enrichment_cache:
                        (
                            collection_url,
                            debut_date_iso,
                            promo_image_url,
                            tech_specs_scripts,
                            tech_specs_supported_languages,
                        ) = family_enrichment_cache[family_id]
                        debut_day = parse_ymd(debut_date_iso)
                        if promo_image_url:
                            image_url = promo_image_url
                        scripts = self._merge_script_labels(scripts, tech_specs_scripts)
                    elif enable_debut_enrichment and (
                        debut_checks_done < max_debut_checks
                        or (always_enrich_packages and self._is_package_product(product))
                    ):
                        allow_tech_specs_fetch = (
                            enable_tech_specs_script_enrichment
                            and tech_specs_checks_done < max_tech_specs_checks
                        )
                        (
                            collection_url,
                            debut_date_iso,
                            promo_image_url,
                            tech_specs_scripts,
                            tech_specs_supported_languages,
                        ) = self._extract_debut_from_product_page(
                            session=session,
                            product_url=source_url,
                            base_url=base_url,
                            timeout=timeout,
                            detail_request_delay=detail_request_delay,
                            fetch_tech_specs_scripts=allow_tech_specs_fetch,
                        )
                        if collection_url is None:
                            derived_url = self._derive_collection_url_from_product(
                                product, base_url
                            )
                            if derived_url:
                                (
                                    coll_url,
                                    debut_date_iso,
                                    promo_image_url,
                                    tech_specs_scripts,
                                    tech_specs_supported_languages,
                                ) = self._extract_debut_from_collection_url(
                                    session=session,
                                    collection_url=derived_url,
                                    base_url=base_url,
                                    timeout=timeout,
                                    detail_request_delay=detail_request_delay,
                                    fetch_tech_specs_scripts=allow_tech_specs_fetch,
                                )
                                collection_url = coll_url
                        debut_checks_done += 1
                        if allow_tech_specs_fetch:
                            tech_specs_checks_done += 1
                        debut_day = parse_ymd(debut_date_iso)
                        if promo_image_url:
                            image_url = promo_image_url
                        scripts = self._merge_script_labels(scripts, tech_specs_scripts)
                        if family_id and collection_url is not None:
                            family_enrichment_cache[family_id] = (
                                collection_url,
                                debut_date_iso,
                                promo_image_url,
                                tech_specs_scripts,
                                tech_specs_supported_languages,
                            )

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
                            "is_package_product": self._is_package_product(product),
                            "myfonts_debut_date": debut_date_iso,
                            "tech_specs_scripts": tech_specs_scripts,
                            "tech_specs_supported_languages": tech_specs_supported_languages,
                        },
                    )
                    releases.append(release)
                    if self.release_callback:
                        self.release_callback(release)

                self._save_checkpoint_progress(
                    checkpoint=checkpoint,
                    page=page,
                    max_pages=max_pages,
                    releases_count=len(releases),
                    oldest_in_page=oldest_in_page.isoformat() if oldest_in_page else None,
                )
                last_oldest_in_page = oldest_in_page

                if len(products) < page_size:
                    exhausted_page_cap = False
                    stop_reason = "short_page"
                    break
                if use_published_proxy_filters and not debut_filter and oldest_in_page and oldest_in_page < cutoff:
                    exhausted_page_cap = False
                    stop_reason = "cutoff_reached"
                    break
                if filter_cutoff and oldest_in_page and oldest_in_page < filter_cutoff:
                    exhausted_page_cap = False
                    stop_reason = "filter_cutoff_reached"
                    break
        finally:
            if self._browser_client is not None:
                self._browser_client.close()
                self._browser_client = None

        checkpoint_status = "capped" if exhausted_page_cap else "completed"
        self._finalize_checkpoint(
            checkpoint=checkpoint,
            status=checkpoint_status,
            stop_reason=stop_reason,
            max_pages=max_pages,
            releases_count=len(releases),
            oldest_in_page=last_oldest_in_page.isoformat() if last_oldest_in_page else None,
        )

        self._log(
            f"summary releases={len(releases)} first_429={self._first_429} "
            f"log_file={self._log_path if self._log_path else 'disabled'}"
        )
        if self._first_429 is None and releases:
            self._save_success_profile(
                {
                    "saved_at": datetime.utcnow().isoformat() + "Z",
                    "api_request_delay_seconds": api_request_delay,
                    "detail_request_delay_seconds": detail_request_delay,
                    "max_debut_checks": max_debut_checks,
                    "max_tech_specs_checks": max_tech_specs_checks,
                }
            )
            self._log(f"saved_success_profile path={_SUCCESS_PROFILE_PATH}")
        self._log("=== MyFonts crawl end ===")
        return releases

    def _extract_scripts(self, product: dict[str, Any]) -> list[str]:
        tags = product.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        normalized_tags = " ".join(str(t).lower() for t in tags)

        found: list[str] = []
        for needle, label in _SCRIPT_HINTS.items():
            if needle in normalized_tags:
                found.append(label)
        return _ordered_unique_scripts(found)

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

    def _is_package_product(self, product: dict[str, Any]) -> bool:
        handle = str(product.get("handle") or "").lower()
        title = str(product.get("title") or "").lower()
        if "-package-" in handle or "bundle" in handle:
            return True
        if "package" in title or "bundle" in title:
            return True
        return False

    def _derive_collection_url_from_product(
        self, product: dict[str, Any], base_url: str
    ) -> str | None:
        """Fallback: derive collection URL from handle+vendor when page fetch fails."""
        handle = str(product.get("handle") or "").strip().lower()
        vendor = str(product.get("vendor") or "").strip()
        if not handle or not vendor:
            return None
        # handle: munch-platter-complete-family-package-1119071 -> family slug: munch-platter
        family_slug = re.sub(
            r"-(?:complete-?family|family-?package|package|bundle)(?:-\d+)?$",
            "",
            handle,
            flags=re.IGNORECASE,
        ).strip("-")
        # MyFonts collection URLs используют только имя семьи, без -complete
        if family_slug.endswith("-complete"):
            family_slug = family_slug[:-9]
        if not family_slug:
            return None
        vendor_slug = re.sub(r"[^\w\s-]", "", vendor.lower()).strip()
        vendor_slug = re.sub(r"\s+", "-", vendor_slug).strip("-")
        if not vendor_slug:
            return None
        path = f"/collections/{family_slug}-font-{vendor_slug}"
        # Исключаем foundry-страницы (second-circle-font-foundry)
        if path.rstrip("/").lower().endswith("-font-foundry"):
            return None
        return urljoin(base_url, path)

    def _extract_debut_from_product_page(
        self,
        session: requests.Session,
        product_url: str,
        base_url: str,
        timeout: int,
        detail_request_delay: float,
        fetch_tech_specs_scripts: bool = False,
    ) -> tuple[str | None, str | None, str | None, list[str], list[str]]:
        try:
            page = self._get_with_backoff(
                session=session,
                url=product_url,
                timeout=timeout,
                delay_seconds=detail_request_delay,
            )
            if page is None:
                return None, None, None, [], []
        except requests.RequestException:
            return None, None, None, [], []

        soup = BeautifulSoup(page.text, "html.parser")

        collection_url = None
        for a in soup.select("a[href*='/collections/']"):
            href = (a.get("href") or "").strip().strip("'")
            if "/collections/" not in href:
                continue
            if "-font-" not in href:
                continue
            # Исключаем foundry-страницы (second-circle-font-foundry и т.п.)
            slug = href.split("/collections/")[-1].split("?")[0].rstrip("/").lower()
            if slug.endswith("-font-foundry"):
                continue
            collection_url = urljoin(base_url, href)
            break

        if not collection_url:
            return None, None, None, [], []

        collection_url_out, debut_iso, promo_img, scripts_list, langs = self._extract_debut_from_collection_url(
            session=session,
            collection_url=collection_url,
            base_url=base_url,
            timeout=timeout,
            detail_request_delay=detail_request_delay,
            fetch_tech_specs_scripts=fetch_tech_specs_scripts,
        )
        # 404 или невалидная страница (foundry): debut=None и promo=None → не используем
        out_url = None
        if collection_url_out is not None and (debut_iso is not None or promo_img is not None):
            out_url = collection_url_out
        return out_url, debut_iso, promo_img, scripts_list, langs

    def _extract_debut_from_collection_url(
        self,
        session: requests.Session,
        collection_url: str,
        base_url: str,
        timeout: int,
        detail_request_delay: float,
        fetch_tech_specs_scripts: bool = False,
    ) -> tuple[str | None, str | None, str | None, list[str], list[str]]:
        """Fetch collection page and extract debut date, image, scripts. Returns (collection_url, debut_iso, promo_image_url, tech_specs_scripts, tech_specs_supported_languages)."""
        try:
            collection_page = self._get_with_backoff(
                session=session,
                url=collection_url,
                timeout=timeout,
                delay_seconds=detail_request_delay,
            )
            if collection_page is None:
                return None, None, None, [], []
        except requests.RequestException:
            return None, None, None, [], []

        collection_html = collection_page.text
        collection_soup = BeautifulSoup(collection_html, "html.parser")
        promo_image_url = self._extract_promo_image_url(collection_soup, base_url)
        tech_specs_scripts = self._extract_scripts_from_text(collection_html)
        tech_specs_supported_languages: list[str] = []
        if fetch_tech_specs_scripts and not tech_specs_scripts:
            tech_specs_scripts, tech_specs_supported_languages = self._extract_scripts_from_tech_specs_tab(
                session=session,
                collection_url=collection_url,
                timeout=timeout,
                detail_request_delay=detail_request_delay,
            )
        text = collection_soup.get_text(" ", strip=True)
        match = re.search(r"MyFonts\s+debut\s*:\s*([A-Za-z]{3}\s+\d{1,2},\s+\d{4})", text, re.IGNORECASE)
        if not match:
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
            # Нет MyFonts debut — возможно foundry или битая страница
            return (None, None, None, [], []) if not promo_image_url else (
                collection_url, None, promo_image_url, tech_specs_scripts, tech_specs_supported_languages
            )

        parsed = parse_mon_dd_yyyy(match.group(1))
        return collection_url, parsed.isoformat() if parsed else None, promo_image_url, tech_specs_scripts, tech_specs_supported_languages

    def _extract_scripts_from_tech_specs_tab(
        self,
        session: requests.Session,
        collection_url: str,
        timeout: int,
        detail_request_delay: float,
    ) -> tuple[list[str], list[str]]:
        try:
            if self._first_429 is not None:
                return [], []
            page = self._get_with_backoff(
                session=session,
                url=collection_url,
                params={"tab": "techSpecs"},
                timeout=timeout,
                delay_seconds=max(0.1, detail_request_delay),
            )
            if page is None:
                return [], []
        except requests.RequestException:
            return [], []
        scripts = self._extract_scripts_from_text(page.text)
        if scripts:
            return scripts, []
        api_scripts, supported_languages = self._extract_scripts_from_tech_metadata_api(
            session=session,
            tech_specs_html=page.text,
            timeout=timeout,
            detail_request_delay=detail_request_delay,
        )
        return self._merge_script_labels(scripts, api_scripts), supported_languages

    def _extract_scripts_from_tech_metadata_api(
        self,
        session: requests.Session,
        tech_specs_html: str,
        timeout: int,
        detail_request_delay: float,
    ) -> tuple[list[str], list[str]]:
        md5_values = list(dict.fromkeys(re.findall(r"tech-documentation-([a-f0-9]{32})", tech_specs_html, flags=re.IGNORECASE)))
        if not md5_values:
            return [], []
        out: list[str] = []
        supported_languages_all: list[str] = []
        api_url = "https://services.myfonts.com/api/metadata/tech"
        connect_timeout = min(max(float(timeout) * 0.2, 2.0), 4.0)
        read_timeout = min(max(float(timeout) * 0.4, 4.0), 8.0)
        for md5 in md5_values[:2]:
            if detail_request_delay > 0:
                time.sleep(min(detail_request_delay, 0.5))
            try:
                response = session.post(
                    api_url,
                    json={"md5": md5},
                    timeout=(connect_timeout, read_timeout),
                    headers={"Content-Type": "application/json"},
                )
                if response.status_code >= 400:
                    continue
                payload = response.json() if response.text else {}
            except Exception:
                continue
            data = payload.get("data") if isinstance(payload, dict) else None
            if not isinstance(data, dict):
                continue
            supported_languages = str(data.get("supported_languages") or "").strip()
            if not supported_languages:
                continue
            tokens = _split_tokens(supported_languages)
            supported_languages_all.extend(tokens)
            out.extend(_map_languages_to_scripts(tokens, mode=self._language_script_signal_mode))
        return _ordered_unique_scripts(out), _ordered_unique_strings(supported_languages_all)

    def _extract_scripts_from_text(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        text = _normalize_spaces(soup.get_text(" ", strip=True))
        if not text:
            return []

        explicit_scripts = _extract_scripts_block(text)
        language_labels = _extract_supported_language_tokens(text)
        lang_scripts = _map_languages_to_scripts(language_labels, mode=self._language_script_signal_mode)

        combined = [*explicit_scripts, *lang_scripts]
        if language_labels and not lang_scripts:
            combined.append("Latin")
        return _ordered_unique_scripts(combined)

    def _merge_script_labels(self, base: list[str], extra: list[str]) -> list[str]:
        return _ordered_unique_scripts([*base, *extra])

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
    ) -> requests.Response | _CrawlerResponse | None:
        retries = 6
        for attempt in range(retries):
            if delay_seconds > 0:
                time.sleep(delay_seconds)
            self._req_no += 1
            req_id = self._req_no
            t0 = time.time()
            if self._browser_client is not None:
                response = self._browser_client.get(url=url, params=params, timeout=timeout)
            else:
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

    def _load_success_profile(self) -> dict[str, Any]:
        if not _SUCCESS_PROFILE_PATH.exists():
            return {}
        try:
            return json.loads(_SUCCESS_PROFILE_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_success_profile(self, payload: dict[str, Any]) -> None:
        _SUCCESS_PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SUCCESS_PROFILE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_checkpoint_signature(
        self,
        *,
        page_size: int,
        start_date: str | None,
        end_date: str | None,
        target_debut_date: str | None,
        enable_debut_enrichment: bool,
        enable_tech_specs_script_enrichment: bool,
        language_script_signal_mode: str,
    ) -> dict[str, Any]:
        return {
            "page_size": int(page_size),
            "start_date": start_date,
            "end_date": end_date,
            "target_debut_date": target_debut_date,
            "enable_debut_enrichment": bool(enable_debut_enrichment),
            "enable_tech_specs_script_enrichment": bool(enable_tech_specs_script_enrichment),
            "language_script_signal_mode": str(language_script_signal_mode or "balanced"),
        }

    def _load_or_create_checkpoint(
        self,
        *,
        signature: dict[str, Any],
        max_pages: int,
        force_fresh_run: bool,
    ) -> dict[str, Any]:
        existing = self._load_checkpoint()
        if (
            not force_fresh_run
            and existing.get("signature") == signature
            and existing.get("status") in {"in_progress", "capped"}
        ):
            next_page = int(existing.get("next_page") or 1)
            if 1 < next_page <= max_pages:
                existing["resumed_at"] = datetime.utcnow().isoformat() + "Z"
                existing["max_pages"] = int(max_pages)
                self._save_checkpoint(existing)
                self._log(
                    f"checkpoint resume next_page={next_page} prev_status={existing.get('status')} path={_CHECKPOINT_PATH}"
                )
                return existing

        checkpoint = {
            "source_id": self.source_config.get("id"),
            "status": "in_progress",
            "signature": signature,
            "started_at": datetime.utcnow().isoformat() + "Z",
            "last_page": 0,
            "next_page": 1,
            "max_pages": int(max_pages),
            "releases_count": 0,
            "oldest_in_page": None,
            "stop_reason": None,
        }
        self._save_checkpoint(checkpoint)
        self._log(f"checkpoint fresh next_page=1 path={_CHECKPOINT_PATH}")
        return checkpoint

    def _load_checkpoint(self) -> dict[str, Any]:
        if not _CHECKPOINT_PATH.exists():
            return {}
        try:
            payload = json.loads(_CHECKPOINT_PATH.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _save_checkpoint(self, payload: dict[str, Any]) -> None:
        _CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CHECKPOINT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _save_checkpoint_progress(
        self,
        *,
        checkpoint: dict[str, Any],
        page: int,
        max_pages: int,
        releases_count: int,
        oldest_in_page: str | None,
    ) -> None:
        checkpoint["status"] = "in_progress"
        checkpoint["last_page"] = int(page)
        checkpoint["next_page"] = min(int(page) + 1, int(max_pages) + 1)
        checkpoint["max_pages"] = int(max_pages)
        checkpoint["releases_count"] = int(releases_count)
        checkpoint["oldest_in_page"] = oldest_in_page
        checkpoint["updated_at"] = datetime.utcnow().isoformat() + "Z"
        self._save_checkpoint(checkpoint)

    def _finalize_checkpoint(
        self,
        *,
        checkpoint: dict[str, Any],
        status: str,
        stop_reason: str,
        max_pages: int,
        releases_count: int,
        oldest_in_page: str | None,
    ) -> None:
        checkpoint["status"] = status
        checkpoint["stop_reason"] = stop_reason
        checkpoint["max_pages"] = int(max_pages)
        checkpoint["releases_count"] = int(releases_count)
        checkpoint["oldest_in_page"] = oldest_in_page
        checkpoint["updated_at"] = datetime.utcnow().isoformat() + "Z"
        checkpoint["completed_at"] = datetime.utcnow().isoformat() + "Z"
        self._save_checkpoint(checkpoint)


def _normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _extract_block(text: str, label: str) -> str:
    pattern = (
        rf"{re.escape(label)}\s*:?\s*(.+?)"
        r"(?=(?:\s+(?:Supported Scripts|Supported Languages|OpenType Features|OpenType|Features|Styles|Weights|"
        r"Designer|Designers|Publisher|Foundry|MyFonts debut|Downloads))|$)"
    )
    match = re.search(pattern, text, flags=re.IGNORECASE)
    return (match.group(1) if match else "").strip()


def _split_tokens(value: str) -> list[str]:
    if not value:
        return []
    raw_parts = re.split(r",|;|•|\|", value)
    out: list[str] = []
    for part in raw_parts:
        token = part.strip(" .")
        if token:
            out.append(token)
    return out


def _extract_scripts_block(text: str) -> list[str]:
    block = _extract_block(text, "Supported Scripts")
    if not block:
        return []
    out: list[str] = []
    for token in _split_tokens(block):
        for script in _SCRIPT_ORDER:
            if token.lower() == script.lower():
                out.append(script)
                break
    return _ordered_unique_scripts(out)


def _extract_supported_language_tokens(text: str) -> list[str]:
    block = _extract_block(text, "Supported Languages")
    if not block:
        return []
    return _split_tokens(block)


def _map_languages_to_scripts(languages: list[str], mode: str = "balanced") -> list[str]:
    mapping = _LANGUAGE_TO_SCRIPT_STRONG if str(mode).lower() == "strong" else _LANGUAGE_TO_SCRIPT
    out: list[str] = []
    saw_unmapped = False
    for language in languages:
        key = language.strip().lower()
        mapped = mapping.get(key)
        if mapped:
            out.append(mapped)
        elif key:
            saw_unmapped = True
    # In MyFonts metadata, large "Supported Languages" lists are predominantly Latin-based.
    # Keep explicit script mappings, but add Latin when the language list is present and partially unmapped.
    if languages and saw_unmapped and not any(v.lower() == "latin" for v in out):
        out.append("Latin")
    return _ordered_unique_scripts(out)


def _ordered_unique_scripts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    canonical: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        # normalize to canonical labels from order table
        label = next((s for s in _SCRIPT_ORDER if s.lower() == normalized.lower()), normalized)
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        canonical.append(label)

    order_index = {name: idx for idx, name in enumerate(_SCRIPT_ORDER)}
    return sorted(canonical, key=lambda v: order_index.get(v, len(_SCRIPT_ORDER)))


def _ordered_unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out
