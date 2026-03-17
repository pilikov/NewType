#!/usr/bin/env python3
"""
Патч: заменить битые collection_url на product_url в боевых данных MyFonts.

Битые URL (404 или foundry вместо коллекции):
- the-sisters-bundle-font-context
- second-circle-font-foundry
- sans-serif-bundle-by-cuchi-font-cuchi-qué-tipo
- mega-bundle-handwriting-fonts-letterhanna-font-letterhanna-studio
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DATA = ROOT / "web" / "data" / "myfonts"

BAD_SLUGS = [
    "the-sisters-bundle-font-context",
    "second-circle-font-foundry",
    "sans-serif-bundle-by-cuchi-font-cuchi-qué-tipo",
    "sans-serif-bundle-by-cuchi-font-cuchi-qu%C3%A9-tipo",  # URL-encoded
    "mega-bundle-handwriting-fonts-letterhanna-font-letterhanna-studio",
]


def is_bad_collection_url(url: str | None) -> bool:
    if not url or "/collections/" not in url:
        return False
    slug = url.split("/collections/")[-1].split("?")[0].rstrip("/")
    slug_decoded = urllib.parse.unquote(slug).lower()
    for bad in BAD_SLUGS:
        if slug_decoded == bad.lower() or slug_decoded.startswith(bad.lower() + "/"):
            return True
    if slug_decoded.endswith("-font-foundry"):
        return True
    return False


def patch_release(r: dict) -> bool:
    """Вернуть True если патч применён."""
    raw = r.get("raw") or {}
    collection_url = raw.get("collection_url") or r.get("source_url")
    if not is_bad_collection_url(collection_url):
        return False
    product_url = raw.get("product_url")
    if not product_url:
        return False
    r["source_url"] = product_url
    raw["collection_url"] = None
    r["raw"] = raw
    return True


def patch_file(path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        return 0
    count = 0
    for r in data:
        if patch_release(r):
            count += 1
    if count > 0:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return count


def main() -> None:
    patched = 0
    for f in WEB_DATA.rglob("*.json"):
        if "_reports" in str(f) or "whatsnew" in f.name:
            continue
        if f.name in ("all_releases.json", "new_releases.json"):
            n = patch_file(f)
            if n:
                print(f"  {f.relative_to(ROOT)}: {n} releases")
                patched += n
    print(f"Total patched: {patched}")


if __name__ == "__main__":
    main()
