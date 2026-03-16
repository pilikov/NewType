#!/usr/bin/env python3
"""
Отдельный парсинг MyFonts за 8–15 марта (products.json API).
Считает коллекции, сохраняет в reports/, сравнивает с нашими данными.

Примечание: whats-new — SPA, контент грузится через JS, requests получает пустую оболочку.
Поэтому используем products.json API (серверный, работает).
"""

from __future__ import annotations

import json
from pathlib import Path

import requests

from src.crawlers.myfonts_api import MyFontsApiCrawler
from src.utils import load_json

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "web" / "data" / "myfonts" / "_reports"
CONFIG = load_json(ROOT / "config" / "sources.json", default={})
if not CONFIG.get("sources"):
    CONFIG = load_json(ROOT / "web" / "config" / "sources.json", default={})
SOURCES = CONFIG.get("sources", [])
MYFONTS_CFG = next((s for s in SOURCES if s.get("id") == "myfonts"), {})


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)

    crawl_cfg = dict(MYFONTS_CFG.get("crawl", {}))
    crawl_cfg["start_date"] = "2026-03-08"
    crawl_cfg["end_date"] = "2026-03-15"
    crawl_cfg["max_pages"] = 15
    crawl_cfg["max_debut_checks"] = 800
    crawl_cfg["max_tech_specs_checks"] = 200
    crawl_cfg["force_fresh_run"] = True

    cfg = dict(MYFONTS_CFG)
    cfg["crawl"] = crawl_cfg

    crawler = MyFontsApiCrawler(source_config=cfg)
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (compatible; TypeParser/1.0)"})

    print("Crawling MyFonts products.json 2026-03-08 .. 2026-03-15 ...")
    releases = crawler.crawl(session=session, timeout=25)
    print(f"Found {len(releases)} collections")

    by_date: dict[str, list] = {}
    for r in releases:
        d = (r.raw or {}).get("myfonts_debut_date") or r.release_date or ""
        d = str(d)[:10] if d else "unknown"
        by_date.setdefault(d, []).append(r)

    for d in sorted(by_date.keys()):
        print(f"  {d}: {len(by_date[d])}")

    # Сохраняем
    rows = [
        {
            "release_id": r.release_id,
            "name": r.name,
            "source_url": r.source_url,
            "release_date": r.release_date,
            "raw": r.raw,
        }
        for r in releases
    ]
    out_path = OUTPUT / "whatsnew_2026-03-08_2026-03-15.json"
    out_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved to {out_path}")

    # Tellur Sans?
    tellur = [r for r in releases if "tellur" in (r.name or "").lower()]
    if tellur:
        print(f"\nTellur Sans in whats-new: {tellur[0].source_url}")
    else:
        print("\nTellur Sans NOT in whats-new crawl")

    # Сравнение с нашими данными
    our_path = ROOT / "web" / "data" / "myfonts" / "2026-03-12" / "all_releases.json"
    if our_path.exists():
        our_data = json.loads(our_path.read_text(encoding="utf-8"))
        our_urls = set()
        for r in our_data:
            if r.get("source_id") != "myfonts":
                continue
            raw = r.get("raw") or {}
            c = raw.get("collection_url") or r.get("source_url") or ""
            if c and "/collections/" in c:
                our_urls.add(c.lower().rstrip("/").split("?")[0])
        whatsnew_urls = {r.source_url.lower().rstrip("/").split("?")[0] for r in releases if r.source_url}
        missing = whatsnew_urls - our_urls
        extra = our_urls - whatsnew_urls
        print(f"\nСравнение с 2026-03-12/all_releases:")
        print(f"  В whats-new, нет у нас: {len(missing)}")
        print(f"  У нас, нет в whats-new: {len(extra)}")
        if missing:
            missing_path = OUTPUT / "whatsnew_missing_in_ours.json"
            missing_path.write_text(
                json.dumps(sorted(missing), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"  Missing list: {missing_path}")
            for u in sorted(missing)[:15]:
                print(f"    - {u}")


if __name__ == "__main__":
    main()
