from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.crawlers.shared.dates import parse_ymd
from src.models import FontRelease

_SOCIAL_DOMAINS = {
    "facebook.com",
    "www.facebook.com",
    "instagram.com",
    "www.instagram.com",
    "twitter.com",
    "www.twitter.com",
    "x.com",
    "www.x.com",
    "linkedin.com",
    "www.linkedin.com",
    "youtube.com",
    "www.youtube.com",
    "vimeo.com",
    "www.vimeo.com",
}
_GENERIC_TOKENS = {
    "about",
    "type",
    "types",
    "font",
    "fonts",
    "foundry",
    "studio",
    "the",
}


@dataclass
class TypeNetworkPublicFamiliesCrawler:
    source_config: dict[str, Any]
    release_callback: Any = None

    def set_release_callback(self, callback: Any) -> None:
        self.release_callback = callback

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontRelease]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = self.source_config.get("base_url", "https://store.typenetwork.com")

        crawl_cfg = self.source_config.get("crawl", {})
        api_base_url = crawl_cfg.get("api_base_url", "https://api.typenetwork.com")
        families_endpoint = crawl_cfg.get("families_endpoint", "/api/1/public/families/")
        foundries_endpoint = crawl_cfg.get("foundries_endpoint", "/api/1/foundries/")
        page_size = int(crawl_cfg.get("page_size", 200))
        max_pages = int(crawl_cfg.get("max_pages", 20))
        ordering = (crawl_cfg.get("ordering", "-released") or "").strip()
        lookback_days = int(crawl_cfg.get("lookback_days", 60))
        disable_date_cutoff = bool(crawl_cfg.get("disable_date_cutoff", False))
        enable_image_enrichment = bool(crawl_cfg.get("enable_image_enrichment", True))
        image_enrichment_limit = int(crawl_cfg.get("image_enrichment_limit", 12))
        image_site_page_limit = int(crawl_cfg.get("image_site_page_limit", 6))
        script_id_map = _parse_script_id_map(crawl_cfg.get("script_id_map"))
        start_date = parse_ymd(crawl_cfg.get("start_date"))
        end_date = parse_ymd(crawl_cfg.get("end_date"))
        since_day = None if disable_date_cutoff else (start_date or (date.today() - timedelta(days=lookback_days)))

        foundry_names = self._load_foundry_names(
            session=session,
            api_base_url=api_base_url,
            endpoint=foundries_endpoint,
            timeout=timeout,
        )

        releases: list[FontRelease] = []
        foundry_site_cache: dict[str, str | None] = {}
        image_enriched = 0
        next_url = urljoin(api_base_url, families_endpoint)
        page_idx = 0
        params: dict[str, Any] | None = {"page_size": page_size}
        if ordering:
            params["ordering"] = ordering

        while next_url and (max_pages <= 0 or page_idx < max_pages):
            response = session.get(next_url, params=params, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
            families = payload.get("results", [])

            if not families:
                break

            should_stop = False
            for family in families:
                released_raw = (
                    str(family.get("released") or family.get("uploaded") or "").strip() or None
                )
                released_day = _parse_iso_day(released_raw)

                if end_date and released_day and released_day > end_date:
                    continue
                if since_day and released_day and released_day < since_day:
                    should_stop = True
                    break

                family_name = (family.get("name") or "").strip()
                if not family_name:
                    continue

                source_url = _build_family_url(
                    base_url=base_url,
                    catalog_url=family.get("catalog_url"),
                    ee_subdomain=family.get("ee_subdomain"),
                    slug=family.get("slug"),
                )

                authors = _extract_foundry_names(family, foundry_names)
                image_url = None
                image_meta: dict[str, Any] = {}

                if enable_image_enrichment and (image_enrichment_limit <= 0 or image_enriched < image_enrichment_limit):
                    foundry_name = authors[0] if authors else ""
                    image_url, image_meta = self._discover_promo_image_for_family(
                        session=session,
                        family_name=family_name,
                        family_slug=str(family.get("slug") or "").strip(),
                        foundry_name=foundry_name,
                        foundry_site_cache=foundry_site_cache,
                        timeout=timeout,
                        site_page_limit=image_site_page_limit,
                    )
                    if image_url:
                        image_enriched += 1

                release = FontRelease(
                        source_id=source_id,
                        source_name=source_name,
                        source_url=source_url,
                        name=family_name,
                        styles=[],
                        authors=authors,
                        scripts=_extract_script_labels(family.get("supported_scripts"), script_id_map),
                        release_date=released_raw,
                        image_url=image_url,
                        woff_url=None,
                        specimen_pdf_url=None,
                        raw={
                            "release_identity": f"typenetwork-family:{family.get('id')}",
                            "family_id": family.get("id"),
                            "family_slug": family.get("slug"),
                            "catalog_url": family.get("catalog_url"),
                            "released": family.get("released"),
                            "uploaded": family.get("uploaded"),
                            "foundry_ids": family.get("foundry"),
                            "supported_scripts": family.get("supported_scripts"),
                            "supported_languages": family.get("supported_languages"),
                            "variable": family.get("variable"),
                            "image_enrichment": image_meta,
                        },
                    )
                releases.append(release)
                if self.release_callback:
                    self.release_callback(release)

            if should_stop:
                break

            next_url = payload.get("next")
            params = None
            page_idx += 1

        return releases

    def _load_foundry_names(
        self,
        session: requests.Session,
        api_base_url: str,
        endpoint: str,
        timeout: int,
    ) -> dict[int, str]:
        out: dict[int, str] = {}
        next_url = urljoin(api_base_url, endpoint)
        params: dict[str, Any] | None = {"page_size": 250}
        pages = 0

        while next_url and pages < 10:
            try:
                response = session.get(next_url, params=params, timeout=timeout)
                response.raise_for_status()
            except requests.RequestException:
                break

            payload = response.json()
            for row in payload.get("results", []):
                foundry_id = row.get("id")
                foundry_name = (row.get("name") or "").strip()
                if isinstance(foundry_id, int) and foundry_name:
                    out[foundry_id] = foundry_name

            next_url = payload.get("next")
            params = None
            pages += 1

        return out

    def _discover_promo_image_for_family(
        self,
        session: requests.Session,
        family_name: str,
        family_slug: str,
        foundry_name: str,
        foundry_site_cache: dict[str, str | None],
        timeout: int,
        site_page_limit: int,
    ) -> tuple[str | None, dict[str, Any]]:
        if not foundry_name:
            return None, {"status": "no_foundry_name"}

        foundry_site = foundry_site_cache.get(foundry_name)
        if foundry_name not in foundry_site_cache:
            foundry_site = self._resolve_foundry_site_url(
                session=session,
                foundry_name=foundry_name,
                timeout=timeout,
            )
            foundry_site_cache[foundry_name] = foundry_site

        if not foundry_site:
            return None, {"status": "foundry_site_not_found", "foundry_name": foundry_name}

        image_url, image_page = self._find_font_promo_image_on_foundry_site(
            session=session,
            foundry_site_url=foundry_site,
            family_name=family_name,
            family_slug=family_slug,
            timeout=timeout,
            site_page_limit=site_page_limit,
        )
        if not image_url:
            return (
                None,
                {
                    "status": "promo_not_found",
                    "foundry_name": foundry_name,
                    "foundry_site_url": foundry_site,
                },
            )

        return (
            image_url,
            {
                "status": "ok",
                "foundry_name": foundry_name,
                "foundry_site_url": foundry_site,
                "image_page_url": image_page,
            },
        )

    def _resolve_foundry_site_url(
        self,
        session: requests.Session,
        foundry_name: str,
        timeout: int,
    ) -> str | None:
        slug = foundry_name.replace(" ", "-")
        slug_norm = _slugify(foundry_name)
        candidates = [
            f"https://typenetwork.com/type-foundries/{slug}",
            f"https://typenetwork.com/type-foundries/{slug_norm}",
        ]

        seen: set[str] = set()
        for page_url in candidates:
            if page_url in seen:
                continue
            seen.add(page_url)
            try:
                r = session.get(page_url, timeout=timeout)
                if r.status_code >= 400:
                    continue
            except requests.RequestException:
                continue

            site_url = _extract_foundry_site_from_html(r.text, page_url)
            if site_url:
                return site_url

        return None

    def _find_font_promo_image_on_foundry_site(
        self,
        session: requests.Session,
        foundry_site_url: str,
        family_name: str,
        family_slug: str,
        timeout: int,
        site_page_limit: int,
    ) -> tuple[str | None, str | None]:
        tokens = _family_tokens(family_name, family_slug)
        if not tokens:
            return None, None

        try:
            home = session.get(foundry_site_url, timeout=timeout)
            home.raise_for_status()
        except requests.RequestException:
            return None, None

        home_soup = BeautifulSoup(home.text, "html.parser")
        candidates = _candidate_pages_from_foundry_home(home_soup, foundry_site_url, tokens)

        if not candidates:
            sitemap_candidates = _candidate_pages_from_sitemap(
                session=session,
                foundry_site_url=foundry_site_url,
                tokens=tokens,
                timeout=timeout,
            )
            candidates = sitemap_candidates

        checked = 0
        for page_url in candidates:
            if site_page_limit > 0 and checked >= site_page_limit:
                break
            checked += 1
            try:
                r = session.get(page_url, timeout=timeout)
                r.raise_for_status()
            except requests.RequestException:
                continue

            image_url = _extract_best_image_from_page(r.text, page_url, tokens)
            if image_url:
                return image_url, page_url

        return None, None


def _build_family_url(
    base_url: str,
    catalog_url: Any,
    ee_subdomain: Any,
    slug: Any,
) -> str | None:
    catalog = str(catalog_url or "").strip()
    if catalog:
        return urljoin(base_url, catalog)

    foundry = str(ee_subdomain or "").strip()
    family_slug = str(slug or "").strip()
    if foundry and family_slug:
        return urljoin(base_url, f"/foundry/{foundry}/fonts/{family_slug}")
    return None


def _extract_foundry_names(family: dict[str, Any], foundry_names: dict[int, str]) -> list[str]:
    out: list[str] = []

    foundry_ids = family.get("foundry") or []
    for foundry_id in foundry_ids:
        if not isinstance(foundry_id, int):
            continue
        name = foundry_names.get(foundry_id)
        if name:
            out.append(name)

    if not out:
        fallback = str(family.get("ee_subdomain") or "").strip()
        if fallback:
            out.append(fallback)

    return sorted(set(out))


def _parse_iso_day(value: str | None) -> date | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None

    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        pass

    return parse_ymd(value[:10])


def _slugify(value: str) -> str:
    raw = value.strip().lower()
    raw = raw.replace("&", " and ")
    raw = re.sub(r"[^a-z0-9]+", "-", raw)
    raw = re.sub(r"-{2,}", "-", raw).strip("-")
    return raw


def _extract_foundry_site_from_html(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    scored: list[tuple[int, str]] = []

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme not in {"http", "https"}:
            continue
        host = (parsed.netloc or "").lower()
        if not host:
            continue
        if "typenetwork.com" in host:
            continue
        if host in _SOCIAL_DOMAINS:
            continue
        if any(s in host for s in ("facebook.", "instagram.", "twitter.", "linkedin.", "youtube.")):
            continue

        text = a.get_text(" ", strip=True).lower()
        score = 0
        if "website" in text or "visit" in text or "site" in text:
            score += 3
        if parsed.path in {"", "/"}:
            score += 2
        if "mailto:" in href:
            continue
        scored.append((score, full))

    if not scored:
        return None
    scored.sort(key=lambda x: x[0], reverse=True)
    return scored[0][1]


def _family_tokens(family_name: str, family_slug: str) -> list[str]:
    tokens: set[str] = set()
    slug = _slugify(family_slug or family_name)
    if slug:
        tokens.update([p for p in slug.split("-") if len(p) >= 3 and p not in _GENERIC_TOKENS])
        tokens.add(slug)

    for part in re.split(r"[^a-z0-9]+", family_name.lower()):
        if len(part) >= 3 and part not in _GENERIC_TOKENS:
            tokens.add(part)

    return sorted(tokens, key=len, reverse=True)


def _candidate_pages_from_foundry_home(
    soup: BeautifulSoup,
    base_url: str,
    tokens: list[str],
) -> list[str]:
    out: list[str] = []
    base_host = (urlparse(base_url).netloc or "").lower()

    for a in soup.select("a[href]"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme not in {"http", "https"}:
            continue
        if (parsed.netloc or "").lower() != base_host:
            continue
        if any(x in parsed.path.lower() for x in ("/cart", "/checkout", "/account", "/login")):
            continue

        anchor_text = a.get_text(" ", strip=True).lower()
        path_query = f"{parsed.path}?{parsed.query}".lower()
        if any(tok in path_query for tok in tokens) or any(tok in anchor_text for tok in tokens):
            out.append(full)

    if not out:
        return []
    return _unique_urls(out)[:24]


def _candidate_pages_from_sitemap(
    session: requests.Session,
    foundry_site_url: str,
    tokens: list[str],
    timeout: int,
) -> list[str]:
    sitemap_url = urljoin(foundry_site_url, "/sitemap.xml")
    try:
        r = session.get(sitemap_url, timeout=timeout)
        r.raise_for_status()
    except requests.RequestException:
        return []

    urls = re.findall(r"<loc>(.*?)</loc>", r.text, flags=re.IGNORECASE)
    scored: list[tuple[int, str]] = []
    for u in urls:
        parsed = urlparse(u)
        low = f"{parsed.path}?{parsed.query}".lower()
        score = 0
        for tok in tokens:
            if tok in low:
                score += 1
        if score > 0:
            scored.append((score, u))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [u for _, u in scored[:24]]


def _extract_best_image_from_page(html: str, page_url: str, tokens: list[str]) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[int, str]] = []

    for selector in ("meta[property='og:image']", "meta[name='twitter:image']"):
        node = soup.select_one(selector)
        if not node:
            continue
        content = (node.get("content") or "").strip()
        if not content:
            continue
        full = urljoin(page_url, content)
        score = 3 + _token_score(full, tokens)
        candidates.append((score, full))

    for img in soup.select("img[src]"):
        src = (img.get("src") or "").strip()
        if not src:
            continue
        full = urljoin(page_url, src)
        alt = (img.get("alt") or "").strip().lower()
        score = _token_score(full, tokens) + _token_score(alt, tokens)
        if score <= 0:
            continue
        candidates.append((score, full))

    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _token_score(text: str, tokens: list[str]) -> int:
    parsed = urlparse(text)
    low = f"{parsed.path}?{parsed.query}".lower() if parsed.scheme else text.lower()
    score = 0
    for tok in tokens:
        if tok in low:
            score += 1
    return score


def _unique_urls(urls: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


def _parse_script_id_map(raw_map: Any) -> dict[int, str]:
    out: dict[int, str] = {}
    if not isinstance(raw_map, dict):
        return out

    for key, value in raw_map.items():
        try:
            script_id = int(str(key).strip())
        except (TypeError, ValueError):
            continue
        label = str(value or "").strip()
        if not label:
            continue
        out[script_id] = label
    return out


def _extract_script_labels(raw_ids: Any, id_to_label: dict[int, str]) -> list[str]:
    if not isinstance(raw_ids, list):
        return []

    out: list[str] = []
    for value in raw_ids:
        try:
            script_id = int(value)
        except (TypeError, ValueError):
            continue
        label = id_to_label.get(script_id) or f"Unknown ({script_id})"
        out.append(label)
    return sorted(set(out))
