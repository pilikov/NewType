from __future__ import annotations

from bs4 import BeautifulSoup


def meta_content(soup: BeautifulSoup, key: str) -> str | None:
    node = soup.select_one(f"meta[property='{key}'], meta[name='{key}']")
    if node and node.get("content"):
        return node.get("content").strip()
    return None
