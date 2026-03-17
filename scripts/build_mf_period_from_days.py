#!/usr/bin/env python3
"""
Собрать период 2026-03-08_2026-03-15 из day data (all_releases.json по дням).
Быстрый путь без парсинга API — используем уже собранные данные.
Derive collection_url из handle+authors для релизов без него.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent.parent
MF_BASE = ROOT / "web" / "data" / "myfonts"
OUTPUT_DIR = MF_BASE / "periods" / "2026-03-08_2026-03-15"
DAYS = ["2026-03-08", "2026-03-09", "2026-03-10", "2026-03-11", "2026-03-12", "2026-03-13", "2026-03-14", "2026-03-15", "2026-03-16", "2026-03-17"]


def derive_collection_url(r: dict) -> str | None:
    raw = r.get("raw") or {}
    if raw.get("collection_url"):
        return raw.get("collection_url")
    handle = str(raw.get("handle") or "").strip().lower()
    vendor = (r.get("authors") or [""])[0] if r.get("authors") else ""
    vendor = str(vendor or "").strip()
    if not handle or not vendor:
        return None
    family_slug = re.sub(
        r"-(?:complete-?family|family-?package|package|bundle)(?:-\d+)?$",
        "",
        handle,
        flags=re.IGNORECASE,
    ).strip("-")
    if family_slug.endswith("-complete"):
        family_slug = family_slug[:-9]
    if not family_slug:
        return None
    vendor_slug = re.sub(r"[^\w\s-]", "", vendor.lower()).strip()
    vendor_slug = re.sub(r"\s+", "-", vendor_slug).strip("-")
    if not vendor_slug:
        return None
    path = f"/collections/{family_slug}-font-{vendor_slug}"
    if path.rstrip("/").lower().endswith("-font-foundry"):
        return None
    return urljoin("https://www.myfonts.com", path)


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
            if not c or "/collections/" not in c:
                c = derive_collection_url(r)
                if c:
                    if raw.get("collection_url") is None:
                        raw["collection_url"] = c
                    r["source_url"] = c
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
