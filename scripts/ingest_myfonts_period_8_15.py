#!/usr/bin/env python3
"""
Залить недостающие коллекции 8–15 марта на сайт.

1. Загружает данные из whatsnew_2026-03-08_2026-03-15.json
2. Дедуплицирует по семье (один релиз на collection_url)
3. Обогащает: имя семьи из URL, image/authors со страницы коллекции
4. Записывает в web/data/myfonts/periods/2026-03-08_2026-03-15/
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "web" / "data" / "myfonts" / "_reports" / "whatsnew_2026-03-08_2026-03-15.json"
OUTPUT_DIR = ROOT / "web" / "data" / "myfonts" / "periods" / "2026-03-08_2026-03-15"
BASE_URL = "https://www.myfonts.com"


def slug_to_family_name(url: str) -> str:
    """tellur-sans-font-monovo -> Tellur Sans"""
    if not url or "/collections/" not in url:
        return ""
    m = re.search(r"/collections/([^/]+)/?", url)
    if not m:
        return ""
    slug = m.group(1)
    if "-font-" in slug:
        slug = slug.split("-font-", 1)[0]
    parts = slug.split("-")
    return " ".join(p.capitalize() for p in parts if p)


def is_package_name(name: str) -> bool:
    n = (name or "").lower()
    if n in {"small family", "complete family", "upright", "slanted", "bundle"}:
        return True
    if " complete family" in n or " family package" in n or " package" in n:
        return True
    return False


def fetch_collection_enrichment(url: str, session: requests.Session, timeout: int = 15) -> dict:
    """Fetch collection page, extract name, image, authors."""
    try:
        r = session.get(url, timeout=timeout)
        r.raise_for_status()
    except Exception:
        return {}
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    out = {}
    # og:title -> "Tellur Sans Font | Webfont & Desktop | MyFonts" -> "Tellur Sans"
    og_title = soup.select_one("meta[property='og:title']")
    if og_title and og_title.get("content"):
        raw = (og_title.get("content") or "").strip()
        name = re.sub(r"\s*-\s*Font from.*$", "", raw, flags=re.I).strip()
        name = re.sub(r"\s*\|\s*.*$", "", name).strip()
        if name:
            out["name"] = name
    # og:image
    og_img = soup.select_one("meta[property='og:image']")
    if og_img and og_img.get("content"):
        out["image_url"] = (og_img.get("content") or "").strip()
    # Publisher: Monovo
    pub = re.search(r"Publisher\s*:\s*([^\n]+?)\s+(?:Foundry|Design Owner|MyFonts debut)", text)
    if pub:
        out["authors"] = [pub.group(1).strip()]
    return out


def main() -> None:
    if not INPUT.exists():
        print(f"Missing {INPUT}")
        return
    data = json.loads(INPUT.read_text(encoding="utf-8"))
    print(f"Loaded {len(data)} releases")

    # Дедуп по collection_url
    by_family: dict[str, dict] = {}
    for r in data:
        raw = r.get("raw") or {}
        c = raw.get("collection_url") or r.get("source_url") or ""
        if not c or "/collections/" not in c:
            continue
        key = c.lower().rstrip("/").split("?")[0]
        existing = by_family.get(key)
        # Предпочитаем: с tech_specs_scripts, с myfonts_debut_date, не package name
        def score(x):
            s = 0
            if (x.get("raw") or {}).get("tech_specs_scripts"):
                s += 10
            if (x.get("raw") or {}).get("myfonts_debut_date"):
                s += 5
            if not is_package_name(x.get("name") or ""):
                s += 20
            return s
        if not existing or score(r) > score(existing):
            by_family[key] = r
    print(f"Unique families: {len(by_family)}")

    # Обогащение
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; TypeParser/1.0)"})
    releases = []
    for i, (key, r) in enumerate(by_family.items()):
        raw = r.get("raw") or {}
        source_url = raw.get("collection_url") or r.get("source_url") or ""
        # Имя семьи: из slug коллекции (tellur-sans-font-monovo -> Tellur Sans)
        name = slug_to_family_name(source_url)
        release_date = (raw.get("myfonts_debut_date") or r.get("release_date") or "")[:10]
        scripts = raw.get("tech_specs_scripts") or []
        image_url = None
        authors = []

        # Fetch enrichment: image, authors; имя с коллекции если лучше
        enrich = fetch_collection_enrichment(source_url, session)
        if enrich.get("name") and not is_package_name(enrich["name"]) and "-font-" not in (enrich["name"] or "").lower():
            name = enrich["name"] or name
        if not name:
            name = r.get("name") or "Unknown"
        if enrich.get("image_url"):
            image_url = enrich["image_url"]
        if enrich.get("authors"):
            authors = enrich["authors"]

        release = {
            "source_id": "myfonts",
            "source_name": "MyFonts",
            "source_url": source_url.rstrip("/"),
            "name": name or slug_to_family_name(source_url) or "Unknown",
            "styles": [],
            "authors": authors,
            "scripts": scripts,
            "script_status": "ok" if scripts else "unknown",
            "release_date": release_date,
            "image_url": image_url,
            "woff_url": None,
            "specimen_pdf_url": None,
            "discovered_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "raw": dict(raw),
            "release_id": r.get("release_id") or f"myfonts:{source_url}",
        }
        raw = release["raw"]
        raw["collection_url"] = source_url.rstrip("/")
        raw["myfonts_debut_date"] = release_date or raw.get("myfonts_debut_date")
        raw["product_url"] = raw.get("product_url") or source_url
        release["raw"] = raw
        releases.append(release)

        if (i + 1) % 50 == 0:
            print(f"  Enriched {i + 1}/{len(by_family)}")
        time.sleep(0.4)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "all_releases.json"
    out_path.write_text(json.dumps(releases, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "new_releases.json").write_text(json.dumps(releases, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(releases)} releases to {out_path}")


if __name__ == "__main__":
    main()
