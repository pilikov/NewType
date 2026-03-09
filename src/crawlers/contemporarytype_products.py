from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import requests

from src.crawlers.shared.text import unique_strings
from src.models import FontRelease


@dataclass
class ContemporaryTypeProductsCrawler:
    source_config: dict[str, Any]
    release_callback: Any = None

    def set_release_callback(self, callback: Any) -> None:
        self.release_callback = callback

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontRelease]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = self.source_config.get("base_url", "https://contemporarytype.com")

        crawl_cfg = self.source_config.get("crawl", {})
        api_base_url = crawl_cfg.get("api_base_url", "https://backend.contemporarytype.com")
        products_endpoint = crawl_cfg.get("products_endpoint", "/api_front/products")
        products_url = urljoin(api_base_url.rstrip("/") + "/", products_endpoint.lstrip("/"))
        detail_endpoint_template = str(
            crawl_cfg.get("detail_endpoint_template", "/api_front/product/{slug}?with-bundles")
        )
        enable_detail_enrichment = bool(crawl_cfg.get("enable_detail_enrichment", True))
        detail_fetch_limit = int(crawl_cfg.get("detail_fetch_limit", 30))
        detail_timeout = int(crawl_cfg.get("detail_timeout", timeout))

        response = session.get(products_url, timeout=timeout)
        response.raise_for_status()
        payload = response.json()

        rows = payload.get("products", [])
        if not isinstance(rows, list):
            return []

        releases: list[FontRelease] = []
        seen_local: set[str] = set()

        for row in rows:
            if not isinstance(row, dict):
                continue

            product = row.get("Product") if isinstance(row.get("Product"), dict) else {}
            brand = row.get("Brand") if isinstance(row.get("Brand"), dict) else {}
            variants = row.get("Variant") if isinstance(row.get("Variant"), list) else []
            images = row.get("Image") if isinstance(row.get("Image"), list) else []

            slug = str(product.get("slug") or "").strip()
            title = str(product.get("title") or "").strip()
            source_url = str(product.get("url") or "").strip() or (
                urljoin(base_url.rstrip("/") + "/", f"fonts/{slug}") if slug else None
            )

            if not title:
                continue

            approved_date = str(product.get("approved_date") or "").strip()
            created = str(product.get("created") or "").strip()
            release_date = approved_date or (created.split(" ", 1)[0] if created else None)

            styles = self._extract_styles(variants)
            authors = unique_strings([str(brand.get("title") or "").strip()])
            supported_languages = self._extract_languages(product)
            image_url = self._extract_image_url(images)
            specimen_pdf_url = self._optional_url(product.get("download_pdf"))
            detail_enrichment: dict[str, Any] = {"used": False}

            need_detail = enable_detail_enrichment and (
                (not image_url) or (not supported_languages) or (not specimen_pdf_url)
            )
            if need_detail and detail_fetch_limit > 0 and slug:
                detail = self._fetch_product_detail(
                    session=session,
                    api_base_url=api_base_url,
                    endpoint_template=detail_endpoint_template,
                    slug=slug,
                    timeout=detail_timeout,
                )
                detail_fetch_limit -= 1
                detail_enrichment = {"used": True, "ok": bool(detail)}
                if detail:
                    detail_product = detail.get("Product") if isinstance(detail.get("Product"), dict) else {}
                    detail_images = detail.get("Image") if isinstance(detail.get("Image"), list) else []
                    if not image_url:
                        image_url = self._extract_image_url(detail_images)
                    if not supported_languages:
                        supported_languages = self._extract_languages(detail_product)
                    if not specimen_pdf_url:
                        specimen_pdf_url = self._optional_url(detail_product.get("download_pdf"))

            scripts = self._scripts_from_languages(supported_languages)

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
                woff_url=None,
                specimen_pdf_url=specimen_pdf_url,
                raw={
                    "release_identity": f"contemporarytype-product:{product.get('id')}",
                    "product": product,
                    "brand": brand,
                    "supported_languages": supported_languages,
                    "language_source": "product.languages" if supported_languages else "none",
                    "variant_count": len(variants),
                    "license_count": len(row.get("License") or []),
                    "detail_enrichment": detail_enrichment,
                    "api_source": products_url,
                },
            )

            if release.release_id in seen_local:
                continue

            seen_local.add(release.release_id)
            releases.append(release)

            if self.release_callback:
                self.release_callback(release)

        return releases

    def _extract_styles(self, variants: list[Any]) -> list[str]:
        styles: list[str] = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            title = str(variant.get("title") or "").strip()
            if title:
                styles.append(title)
        return unique_strings(styles)

    def _extract_languages(self, product: dict[str, Any]) -> list[str]:
        languages = product.get("languages")
        if not isinstance(languages, list):
            return []
        return unique_strings([str(x or "").strip().lower() for x in languages if str(x or "").strip()])

    def _scripts_from_languages(self, languages: list[str]) -> list[str]:
        hints = " ".join([str(x or "").lower() for x in languages])
        scripts: list[str] = []
        if any(token in hints for token in ("latin", "english", "french", "german", "spanish", "portuguese")):
            scripts.append("Latin")
        if any(token in hints for token in ("cyrillic", "russian", "ukrainian", "bulgarian", "serbian")):
            scripts.append("Cyrillic")
        if "greek" in hints:
            scripts.append("Greek")
        if "arabic" in hints:
            scripts.append("Arabic")
        if "hebrew" in hints:
            scripts.append("Hebrew")
        return unique_strings(scripts)

    def _extract_image_url(self, images: list[Any]) -> str | None:
        for image in images:
            if not isinstance(image, dict):
                continue
            candidate = self._optional_url(image.get("file"))
            if candidate:
                return candidate
        return None

    def _fetch_product_detail(
        self,
        session: requests.Session,
        api_base_url: str,
        endpoint_template: str,
        slug: str,
        timeout: int,
    ) -> dict[str, Any] | None:
        endpoint = endpoint_template.format(slug=slug)
        detail_url = urljoin(api_base_url.rstrip("/") + "/", endpoint.lstrip("/"))
        try:
            response = session.get(detail_url, timeout=timeout)
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            return None
        except ValueError:
            return None

        product = payload.get("product")
        if isinstance(product, dict):
            return product
        return None

    def _optional_url(self, value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        value = value.strip()
        if not value:
            return None
        if value.startswith("http://") or value.startswith("https://"):
            return value
        return None
