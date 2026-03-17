#!/usr/bin/env python3
"""
Собрать период 2026-03-08_2026-03-15 из day data (all_releases.json по дням).
Только релизы с проверенным collection_url (без derive — даёт 404).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MF_BASE = ROOT / "web" / "data" / "myfonts"
OUTPUT_DIR = MF_BASE / "periods" / "2026-03-08_2026-03-15"
DAYS = ["2026-03-08", "2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13", "2026-03-14", "2026-03-15", "2026-03-16", "2026-03-17"]


def main() -> None:
    by_family: dict[str, dict] = {}
    for day in DAYS:
        p = MF_BASE / day / "all_releases.json"
        if not p.exists():
            continue
        arr = json.loads(p.read_text(encoding="utf-8"))
        for r in arr:
            if r.get("source_id") != "myfonts":
                continue
            raw = r.get("raw") or {}
            c = raw.get("collection_url") or r.get("source_url") or ""
            # Не используем derive — даёт 404. Только проверенные collection_url.
            if not c or "/collections/" not in c:
                continue
            debut = (raw.get("myfonts_debut_date") or r.get("release_date") or "")[:10]
            if debut < "2026-03-08" or debut > "2026-03-15":
                continue
            key = c.lower().rstrip("/").split("?")[0]
            existing = by_family.get(key)
            # Предпочитаем: с tech_specs, с image, не package
            def score(x: dict) -> int:
                s = 0
                if (x.get("raw") or {}).get("tech_specs_scripts"):
                    s += 10
                if (x.get("raw") or {}).get("myfonts_debut_date"):
                    s += 5
                if (x.get("image_url") or "").startswith("http") and "Logo" not in (x.get("image_url") or ""):
                    s += 3
                name = (x.get("name") or "").lower()
                if "package" not in name and "bundle" not in name and "complete family" not in name:
                    s += 20
                return s

            if not existing or score(r) > score(existing):
                by_family[key] = r

    releases = list(by_family.values())
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "all_releases.json"
    out_path.write_text(json.dumps(releases, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "new_releases.json").write_text(json.dumps(releases, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {len(releases)} releases to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
