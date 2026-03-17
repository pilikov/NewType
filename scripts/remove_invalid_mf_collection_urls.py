#!/usr/bin/env python3
"""
Удалить collection_url для релизов, где ссылка ведёт на 404.
Использует product_url как source_url если collection_url невалиден.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
MF_BASE = ROOT / "web" / "data" / "myfonts"

# Известные 404 от derive (handle+vendor → неверный slug)
KNOWN_404_PREFIXES = [
    "font-awesome-bundles-font-",
    "the-sisters-bundle-font-",
    "sans-serif-bundle-by-cuchi-font-",
    "semibold-emeritus-",
]


def is_known_404(url: str) -> bool:
    url_lower = url.lower()
    return any(p in url_lower for p in KNOWN_404_PREFIXES)


def validate_url(url: str, session: requests.Session, timeout: int = 8) -> bool:
    try:
        r = session.head(url, timeout=timeout, allow_redirects=True)
        return 200 <= r.status_code < 400
    except Exception:
        return False


def main() -> None:
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; TypeParser/1.0)"})
    total_fixed = 0
    for json_path in sorted(MF_BASE.rglob("all_releases.json")):
        if "_reports" in str(json_path):
            continue
        arr = json.loads(json_path.read_text(encoding="utf-8"))
        changed = False
        for r in arr:
            if r.get("source_id") != "myfonts":
                continue
            raw = r.get("raw") or {}
            c = raw.get("collection_url")
            if not c or "/collections/" not in c:
                continue
            if is_known_404(c) or not validate_url(c, session):
                # 404 — убираем collection_url, используем product_url
                product_url = raw.get("product_url") or r.get("source_url")
                if product_url and "/products/" in product_url:
                    raw["collection_url"] = None
                    r["source_url"] = product_url
                    r["raw"] = raw
                    changed = True
                    total_fixed += 1
                    print(f"  404: {c[:70]}... -> product_url")
            time.sleep(0.05)
        if changed:
            json_path.write_text(json.dumps(arr, ensure_ascii=False, indent=2), encoding="utf-8")
            new_path = json_path.parent / "new_releases.json"
            if new_path.exists():
                new_arr = json.loads(new_path.read_text(encoding="utf-8"))
                for r in new_arr:
                    if r.get("source_id") != "myfonts":
                        continue
                    raw = r.get("raw") or {}
                    c = raw.get("collection_url")
                    if not c or "/collections/" not in c:
                        continue
                    if is_known_404(c) or not validate_url(c, session):
                        product_url = raw.get("product_url") or r.get("source_url")
                        if product_url and "/products/" in product_url:
                            raw["collection_url"] = None
                            r["source_url"] = product_url
                            r["raw"] = raw
                new_path.write_text(json.dumps(new_arr, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  Fixed {json_path.relative_to(MF_BASE)}")
    print(f"Total fixed (404 -> product_url): {total_fixed}")


if __name__ == "__main__":
    main()
