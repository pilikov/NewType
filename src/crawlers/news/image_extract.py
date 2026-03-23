"""Extract thumbnail/hero image from article HTML."""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup


def extract_og_image(html: str, page_url: str) -> str | None:
    """Return og:image (or twitter:image) URL from an HTML page, or None."""
    soup = BeautifulSoup(html, "html.parser")

    # 1. og:image — most reliable
    og = soup.find("meta", attrs={"property": "og:image"})
    if og and og.get("content", "").strip():
        return urljoin(page_url, og["content"].strip())

    # 2. twitter:image fallback
    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content", "").strip():
        return urljoin(page_url, tw["content"].strip())

    return None
