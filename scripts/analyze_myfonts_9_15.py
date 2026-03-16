#!/usr/bin/env python3
"""Анализ MyFonts: релизы 9–15 марта — сырые данные vs что попадает на сайт."""

from __future__ import annotations

import json
from pathlib import Path

DATA = Path("web/data/myfonts")
BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "web" / "data" / "myfonts"


def has_family_link(r: dict) -> bool:
    raw = r.get("raw") or {}
    c = raw.get("collection_url")
    if c and isinstance(c, str) and c.startswith("http"):
        return True
    url = (r.get("source_url") or "").lower()
    return "/collections/" in url and "whats-new" not in url


def get_debut(r: dict):
    raw = r.get("raw") or {}
    d = raw.get("myfonts_debut_date") or r.get("release_date")
    if not d or len(str(d)) < 10:
        return None
    return str(d)[:10]


def main() -> None:
    # 1. MyFonts API: сколько релизов 9–15 марта (приблизительно — по products.json мы не знаем точно)
    print("=" * 60)
    print("1. MyFonts на сайте: ориентир — ~100–200 новых в неделю (типично)")
    print("   Точный подсчёт требует запроса к MyFonts API.")
    print()

    # 2. Сырые данные
    print("2. СЫРЫЕ ДАННЫЕ (web/data/myfonts)")
    print("-" * 40)

    all_files = list(DATA.rglob("all_releases.json"))
    total_raw = 0
    by_file = {}

    for fp in sorted(all_files):
        rel = str(fp.relative_to(DATA))
        data = json.loads(fp.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            continue
        total_raw += len(data)
        # Только myfonts
        mf = [r for r in data if r.get("source_id") == "myfonts"]
        by_file[rel] = {"total": len(data), "myfonts": len(mf)}
        print(f"  {rel}: {len(mf)} myfonts (всего {len(data)})")

    print(f"\n  ИТОГО в all_releases.json: {total_raw} записей")
    print()

    # 3. Логика сайта: latestDay + daySupplement + merge + hasMyfontsFamilyLink
    latest_day = "2026-03-12"
    latest_period_end = "2026-03-08"
    day_path = DATA / latest_day / "all_releases.json"

    if not day_path.exists():
        print(f"3. Нет {day_path}")
        return

    day_raw = json.loads(day_path.read_text(encoding="utf-8"))
    day_mf = [r for r in day_raw if r.get("source_id") == "myfonts"]

    day_supplement = [
        r
        for r in day_mf
        if (get_debut(r) or "") > latest_period_end
    ]

    with_family = [r for r in day_supplement if has_family_link(r)]

    # Дедуп по family (упрощённо — по collection_url/source_url)
    by_family: dict[str, dict] = {}
    for r in with_family:
        raw = r.get("raw") or {}
        c = raw.get("collection_url") or r.get("source_url") or ""
        key = (c or "").lower().replace("/", "").rstrip("/") or r.get("release_id", "")
        if key and key not in by_family:
            by_family[key] = r

    # Релизы 9–15 марта
    week_9_15 = [
        r
        for r in by_family.values()
        if get_debut(r) and "2026-03-09" <= get_debut(r) <= "2026-03-15"
    ]

    print("3. ЛОГИКА САЙТА (loadSourceReleases myfonts)")
    print("-" * 40)
    print(f"  latestDay: {latest_day}")
    print(f"  latestPeriodEnd: {latest_period_end}")
    print(f"  dayRaw (myfonts): {len(day_mf)}")
    print(f"  daySupplement (debut > {latest_period_end}): {len(day_supplement)}")
    print(f"  с hasMyfontsFamilyLink: {len(with_family)}")
    print(f"  после дедупа по семье: {len(by_family)}")
    print(f"  в диапазоне 9–15 марта: {len(week_9_15)}")
    print()

    # 4. Причина 73
    print("4. ПОЧЕМУ 73 НА САЙТЕ?")
    print("-" * 40)
    print("  Сайт показывает недели из data_coverage.json.")
    print("  effectiveWeeks = merge(loadCoverageWeeks, buildWeeksFromReleases)")
    print("  buildWeekGroups фильтрует: только недели с releaseCount > 0")
    print("  Для недели 9–15 марта: релизы с debut в [2026-03-09, 2026-03-15]")
    print()
    print("  Возможные причины малого числа:")
    print("  - daySupplement отсекает релизы без myfonts_debut_date (используется release_date)")
    print("  - hasMyfontsFamilyLink отсекает product-only (collection_url=null)")
    print("  - data_coverage.json может не включать неделю 9–15")
    print("  - Периоды не покрывают 9–15 (только daySupplement)")
    print()

    # Детали: сколько без family link
    without_family = [r for r in day_supplement if not has_family_link(r)]
    no_debut = [r for r in day_mf if not get_debut(r)]
    debut_before_9 = [r for r in day_mf if get_debut(r) and get_debut(r) <= "2026-03-08"]

    print("5. ДЕТАЛИ")
    print("-" * 40)
    print(f"  day_mf без debut/release_date: {len(no_debut)}")
    print(f"  day_mf с debut <= 2026-03-08: {len(debut_before_9)}")
    print(f"  day_supplement без family link: {len(without_family)}")
    if without_family[:5]:
        print("  Примеры без family link:")
        for r in without_family[:5]:
            print(f"    - {r.get('name')} (debut={get_debut(r)}, collection_url={(r.get('raw') or {}).get('collection_url')})")


if __name__ == "__main__":
    main()
