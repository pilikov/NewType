from __future__ import annotations

import gzip
import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.models import FontRelease


@dataclass
class FutureFontsSitemapCrawler:
    source_config: dict[str, Any]
    release_callback: Any = None

    def set_release_callback(self, callback: Any) -> None:
        self.release_callback = callback

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontRelease]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = self.source_config.get("base_url", "https://www.futurefonts.com")

        sitemap_url = self._discover_sitemap_url(session, base_url, timeout)
        url_entries = self._load_sitemap_entries(session, sitemap_url, timeout)
        fetch_detail_limit = int(self.source_config.get("crawl", {}).get("fetch_detail_limit", 40))
        fetched_count = 0

        releases: list[FontRelease] = []
        for source_url, lastmod in url_entries:
            parsed = urlparse(source_url)
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) != 2:
                continue
            if parts[0] in {"fonts", "foundries", "blog", "journal-posts", "about", "team", "faq", "activity", "submissions"}:
                continue

            foundry_slug, font_slug = parts
            name = self._humanize_slug(font_slug)
            authors = [self._humanize_slug(foundry_slug)]
            normalized_url = urljoin(base_url, f"/{foundry_slug}/{font_slug}")

            image_url = None
            fetched_name = None
            fetched_authors: list[str] = []
            detail = None
            if fetched_count < fetch_detail_limit:
                detail = self._fetch_detail_metadata(session, normalized_url, timeout)
                fetched_count += 1
            if detail:
                fetched_name = detail.get("name")
                image_url = detail.get("image_url")
                fetched_authors = detail.get("authors") or []

            release = FontRelease(
                source_id=source_id,
                source_name=source_name,
                source_url=normalized_url,
                name=(fetched_name or name),
                styles=[],
                authors=(fetched_authors or authors),
                scripts=[],
                release_date=lastmod,
                image_url=image_url,
                woff_url=None,
                specimen_pdf_url=None,
                raw={
                    "foundry_slug": foundry_slug,
                    "font_slug": font_slug,
                    "sitemap_url": sitemap_url,
                },
            )
            releases.append(release)
            if self.release_callback:
                self.release_callback(release)

        return releases

    def _discover_sitemap_url(self, session: requests.Session, base_url: str, timeout: int) -> str:
        robots_url = urljoin(base_url, "/robots.txt")
        robots = session.get(robots_url, timeout=timeout)
        robots.raise_for_status()

        match = re.search(r"^Sitemap:\s*(\S+)\s*$", robots.text, flags=re.MULTILINE)
        if match:
            return match.group(1).strip()

        return urljoin(base_url, "/sitemap.xml")

    def _load_sitemap_entries(
        self,
        session: requests.Session,
        sitemap_url: str,
        timeout: int,
    ) -> list[tuple[str, str | None]]:
        response = session.get(sitemap_url, timeout=timeout)
        response.raise_for_status()

        content = response.content
        if sitemap_url.endswith(".gz") or response.headers.get("content-type", "").startswith("application/x-gzip"):
            content = gzip.decompress(content)

        root = ET.parse(io.BytesIO(content)).getroot()

        ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        entries: list[tuple[str, str | None]] = []
        for node in root.findall("s:url", ns):
            loc = node.findtext("s:loc", default="", namespaces=ns).strip()
            lastmod_raw = node.findtext("s:lastmod", default="", namespaces=ns).strip()
            if not loc:
                continue
            loc = loc.replace("http://", "https://")
            entries.append((loc, self._normalize_lastmod(lastmod_raw)))
        return entries

    def _normalize_lastmod(self, value: str) -> str | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value).isoformat()
        except ValueError:
            return value

    def _fetch_detail_metadata(
        self,
        session: requests.Session,
        source_url: str,
        timeout: int,
    ) -> dict[str, Any] | None:
        try:
            response = session.get(source_url, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException:
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        og_title = self._meta(soup, "og:title")
        og_image = self._meta(soup, "og:image")

        name = None
        authors: list[str] = []
        if og_title:
            # Example: "Kicker by Vectro - Future Fonts"
            match = re.match(r"\s*(.*?)\s+by\s+(.*?)\s+-\s+Future Fonts\s*$", og_title)
            if match:
                name = match.group(1).strip()
                authors = [match.group(2).strip()]
            else:
                name = og_title.replace("- Future Fonts", "").strip()

        return {
            "name": name,
            "authors": authors,
            "image_url": og_image,
        }

    def _meta(self, soup: BeautifulSoup, key: str) -> str | None:
        node = soup.select_one(f"meta[property='{key}'], meta[name='{key}']")
        if node and node.get("content"):
            return node.get("content").strip()
        return None

    def _humanize_slug(self, slug: str) -> str:
        return slug.replace("-", " ").strip().title()
