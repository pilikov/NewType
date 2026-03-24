from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import requests

from src.crawlers.shared.text import unique_strings
from src.models import FontRelease

logger = logging.getLogger(__name__)


@dataclass
class IltTypesenseCrawler:
    source_config: dict[str, Any]
    release_callback: Any = None

    def set_release_callback(self, callback: Any) -> None:
        self.release_callback = callback

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontRelease]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = self.source_config.get("base_url", "https://fonts.ilovetypography.com")

        crawl_cfg = self.source_config.get("crawl", {})
        api_host = crawl_cfg.get("api_host", "https://ikgq6me4n0p3u2bvp-1.a1.typesense.net")
        api_key = crawl_cfg.get("api_key", "")
        collection = crawl_cfg.get("collection", "prod_FONTS")
        per_page = int(crawl_cfg.get("per_page", 250))
        max_pages = int(crawl_cfg.get("max_pages", 10))
        request_delay = float(crawl_cfg.get("request_delay_seconds", 0.3))

        search_url = f"{api_host.rstrip('/')}/collections/{collection}/documents/search"
        headers = {"X-TYPESENSE-API-KEY": api_key}

        releases: list[FontRelease] = []
        seen_local: set[str] = set()
        page = 1

        while page <= max_pages:
            params: dict[str, Any] = {
                "q": "*",
                "per_page": per_page,
                "page": page,
            }

            logger.info("ILT Typesense: fetching page %d (per_page=%d)", page, per_page)
            resp = session.get(search_url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            payload = resp.json()

            hits = payload.get("hits", [])
            found = payload.get("found", 0)

            if not hits:
                logger.info("ILT Typesense: no more hits on page %d, stopping", page)
                break

            for hit in hits:
                doc = hit.get("document")
                if not isinstance(doc, dict):
                    continue

                title = str(doc.get("title") or "").strip()
                if not title:
                    continue

                doc_id = str(doc.get("id") or "").strip()
                slug = str(doc.get("slug") or "").strip()
                url_path = str(doc.get("url") or "").strip()

                source_url = (
                    f"{base_url.rstrip('/')}{url_path}" if url_path else None
                )

                release_date = str(doc.get("releaseDate") or "").strip() or None

                foundry = str(doc.get("foundry") or "").strip()
                designer = str(doc.get("designer") or "").strip()
                authors = unique_strings([a for a in [foundry, designer] if a])

                styles = doc.get("styles") or []
                if not isinstance(styles, list):
                    styles = []
                styles = unique_strings([str(s).strip() for s in styles if str(s).strip()])

                scripts = doc.get("script") or []
                if not isinstance(scripts, list):
                    scripts = []
                scripts = unique_strings([str(s).strip() for s in scripts if str(s).strip()])

                images = doc.get("images") or []
                image_url = None
                if isinstance(images, list):
                    for img in images:
                        if isinstance(img, str) and img.strip():
                            image_url = img.strip()
                            break

                webfonts = doc.get("webfonts") or []
                woff_url = None
                if isinstance(webfonts, list):
                    for wf in webfonts:
                        if isinstance(wf, str) and wf.strip():
                            woff_url = wf.strip()
                            break

                release = FontRelease(
                    source_id=source_id,
                    source_name=source_name,
                    source_url=source_url,
                    name=title,
                    styles=styles,
                    authors=authors,
                    scripts=scripts,
                    release_date=release_date,
                    image_url=image_url,
                    woff_url=woff_url,
                    specimen_pdf_url=None,
                    raw={
                        "release_identity": f"ilt:{doc_id}",
                        "typesense_id": doc_id,
                        "slug": slug,
                        "foundry": foundry,
                        "designer": designer,
                        "description": str(doc.get("description") or "").strip(),
                        "categories": doc.get("categories") or [],
                        "otfeatures": doc.get("otfeatures") or [],
                        "cedars": doc.get("cedars") or {},
                        "price": doc.get("price"),
                        "fromPrice": doc.get("fromPrice"),
                        "onPromotion": doc.get("onPromotion"),
                        "hasDemoFonts": doc.get("hasDemoFonts"),
                        "hasFreeFonts": doc.get("hasFreeFonts"),
                        "enabled": doc.get("enabled"),
                        "api_source": search_url,
                    },
                )

                if release.release_id in seen_local:
                    continue

                seen_local.add(release.release_id)
                releases.append(release)

                if self.release_callback:
                    self.release_callback(release)

            logger.info(
                "ILT Typesense: page %d yielded %d hits, total collected %d / %d found",
                page, len(hits), len(releases), found,
            )

            fetched_so_far = page * per_page
            if fetched_so_far >= found:
                logger.info("ILT Typesense: all %d documents fetched, stopping", found)
                break

            page += 1
            if page <= max_pages and request_delay > 0:
                time.sleep(request_delay)

        logger.info("ILT Typesense: finished with %d releases", len(releases))
        return releases
