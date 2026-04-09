#!/usr/bin/env python3
"""
Обогащение записей Fontstand из уже сохранённого all_releases.json:
1) Скрипты (письменности) через API фильтров — маркерные языки (English→Latin, Russian→Cyrillic и т.д.).
2) Опционально: загрузка страницы семейства — Designers и категория из описания.
Запуск без полного пересбора каталога.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import requests

# project root
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.crawlers.fontstand_catalog import (
    SCRIPT_MARKER_LANGUAGE_IDS,
    _enrich_from_family_page,
    _fetch_filtered_slugs,
)
from src.crawlers.shared.text import unique_strings
from src.storage.json_adapter import JsonStorageAdapter
from src.models import FontRelease


def slug_from_release(release: FontRelease) -> str | None:
    link = (release.raw.get("link") or "").strip()
    if link:
        slug = link.replace("fonts/", "").strip().rstrip("/")
        if slug:
            return slug
    url = (release.source_url or "").strip()
    if url and "/fonts/" in url:
        return url.rstrip("/").split("/fonts/")[-1].strip("/") or None
    return None


def enrich_scripts_from_filter_api(
    session: requests.Session,
    fontstand_releases: list[FontRelease],
    base_url: str,
    page_size: int,
    delay: float,
    timeout: int,
) -> dict[str, list[str]]:
    """
    Для каждого маркерного языка запрашивает GET FilterV2, собирает slug'и,
    возвращает slug -> list[script_name]. Обновляет release.scripts у переданных релизов.
    """
    referer = f"{base_url.rstrip('/')}/fonts/"
    filter_url = f"{base_url.rstrip('/')}/fonts/FilterV2"
    script_map: dict[str, list[str]] = {}
    slug_set = {slug_from_release(r) for r in fontstand_releases}
    slug_set.discard(None)
    # Считаем фильтр не сработавшим, если вернулось не меньше slug'ов, чем у нас в файле (полный каталог)
    threshold = len(slug_set)

    for script_name, lang_id in SCRIPT_MARKER_LANGUAGE_IDS.items():
        slugs = _fetch_filtered_slugs(
            session, filter_url, f"languages[{lang_id}]", lang_id, page_size, delay, timeout, referer
        )
        if len(slugs) < threshold:
            for slug in slugs:
                script_map.setdefault(slug, []).append(script_name)

    for slug in script_map:
        script_map[slug] = unique_strings(script_map[slug])

    for release in fontstand_releases:
        slug = slug_from_release(release)
        if slug and slug in script_map:
            release.scripts = list(script_map[slug])

    return script_map


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrich Fontstand all_releases.json: scripts (filter API) + optional detail (family pages)"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="Path to all_releases.json (default: data/fontstand/<latest date>/all_releases.json)",
    )
    parser.add_argument("--no-scripts", action="store_true", help="Skip script enrichment via filter API")
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Max releases to enrich from family pages (0 = only scripts; 500 = scripts + detail for first 500)",
    )
    parser.add_argument("--delay", type=float, default=0.5, help="Delay between requests in seconds (default 0.5)")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout (default 20)")
    parser.add_argument("--dry-run", action="store_true", help="Do not save, only print progress")
    args = parser.parse_args()

    if args.input:
        input_path = Path(args.input)
    else:
        data_dir = ROOT / "data" / "fontstand"
        if not data_dir.is_dir():
            print(f"[error] no data dir {data_dir}")
            sys.exit(1)
        dates = sorted(d.name for d in data_dir.iterdir() if d.is_dir() and d.name not in ("periods",))
        if not dates:
            print("[error] no date dirs in data/fontstand")
            sys.exit(1)
        input_path = data_dir / dates[-1] / "all_releases.json"

    if not input_path.is_file():
        print(f"[error] file not found: {input_path}")
        sys.exit(1)

    storage = JsonStorageAdapter(ROOT / "data")
    all_releases = storage.load_releases(input_path)
    if not all_releases:
        print("[error] no releases loaded")
        sys.exit(1)

    fontstand_releases: list[FontRelease] = [
        r for r in all_releases
        if (r.source_id or "").lower() == "fontstand" and slug_from_release(r) is not None
    ]
    total_fs = len(fontstand_releases)
    print(f"[start] fontstand releases in file: {total_fs} | input: {input_path}")

    base_url = "https://fontstand.com"
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "Referer": f"{base_url}/fonts/",
        "X-Requested-With": "XMLHttpRequest",
        "Accept": "application/json",
    })

    start = time.monotonic()

    # 1) Обогащение скриптами через API фильтров (маркерные языки)
    if not args.no_scripts:
        print("[scripts] fetching filter API for 12 marker languages...")
        script_map = enrich_scripts_from_filter_api(
            session, fontstand_releases, base_url, page_size=64, delay=args.delay, timeout=args.timeout
        )
        with_scripts = sum(1 for r in fontstand_releases if r.scripts)
        print(f"[scripts] done: {with_scripts}/{total_fs} releases have scripts in {time.monotonic() - start:.1f}s")
    else:
        print("[scripts] skipped (--no-scripts)")

    # 2) Опционально: обогащение со страницы семейства (designers, category)
    if args.limit > 0:
        to_detail = fontstand_releases[: args.limit]
        detail_count = 0
        for i, release in enumerate(to_detail):
            if args.delay > 0 and i > 0:
                time.sleep(args.delay)
            slug = slug_from_release(release)
            if not slug:
                continue
            designers, scripts_page, category_hint = _enrich_from_family_page(
                session, slug, base_url, args.timeout
            )
            if designers:
                release.authors = unique_strings(list(release.authors) + designers)
                detail_count += 1
            if scripts_page:
                release.scripts = unique_strings(list(release.scripts) + scripts_page)
            if category_hint:
                cats = list(release.raw.get("categories") or [])
                if category_hint not in cats:
                    cats.append(category_hint)
                release.raw["categories"] = cats
            if (i + 1) % 50 == 0 or (i + 1) == len(to_detail):
                print(f"[detail] {i + 1}/{len(to_detail)} enriched={detail_count}")
        print(f"[detail] done: {detail_count} with designers/category")
    else:
        print("[detail] skipped (--limit 0)")

    if not args.dry_run:
        storage.write_releases(input_path, all_releases)
        print(f"[saved] {input_path}")
    else:
        print("[dry-run] not saving")

    print(f"[done] total {time.monotonic() - start:.1f}s")


if __name__ == "__main__":
    main()
