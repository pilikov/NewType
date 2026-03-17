#!/usr/bin/env python3
"""
Применить derive collection_url к существующим MF данным (day + periods).
Заполняет collection_url из handle+authors для релизов без него.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parent.parent
MF_BASE = ROOT / "web" / "data" / "myfonts"


def derive_collection_url(r: dict) -> str | None:
    raw = r.get("raw") or {}
    if raw.get("collection_url"):
        return None
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
    total_filled = 0
    for json_path in sorted(MF_BASE.rglob("all_releases.json")):
        if "_reports" in str(json_path):
            continue
        arr = json.loads(json_path.read_text(encoding="utf-8"))
        changed = False
        for r in arr:
            if r.get("source_id") != "myfonts":
                continue
            raw = r.get("raw") or {}
            if raw.get("collection_url"):
                continue
            url = derive_collection_url(r)
            if url:
                raw["collection_url"] = url
                r["source_url"] = url
                r["raw"] = raw
                changed = True
                total_filled += 1
        if changed:
            json_path.write_text(json.dumps(arr, ensure_ascii=False, indent=2), encoding="utf-8")
            new_path = json_path.parent / "new_releases.json"
            if new_path.exists():
                new_arr = json.loads(new_path.read_text(encoding="utf-8"))
                for r in new_arr:
                    if r.get("source_id") != "myfonts":
                        continue
                    raw = r.get("raw") or {}
                    if raw.get("collection_url"):
                        continue
                    url = derive_collection_url(r)
                    if url:
                        raw["collection_url"] = url
                        r["source_url"] = url
                        r["raw"] = raw
                new_path.write_text(json.dumps(new_arr, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  {json_path.relative_to(MF_BASE)}")
    print(f"Filled collection_url for {total_filled} releases")


if __name__ == "__main__":
    main()
