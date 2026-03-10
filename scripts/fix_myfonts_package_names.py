#!/usr/bin/env python3
"""
Fix MyFonts release names in existing JSON without re-crawling.

Problem:
  products.json returns separate Shopify products per package (Complete Family,
  Upright, Slanted, ...). The crawler sets source_url to collection_url after
  enrichment but keeps product title as name — so you get cards titled
  "Upright" linking to Mizhon Flare, and "Mizhon Sans Complete Family"
  instead of "Mizhon Sans".

This script:
  1. Strips " Complete Family" / " complete family" suffix from name.
  2. For package handles (raw.handle contains "-package-") with collection_url,
     if name is a generic package label, derives display name from collection
     URL slug (segment before "-font-" → title case).
  3. Optionally dedupes by collection_url, keeping one row per family
     (prefers entry that already has a proper family name and image).

Usage:
  python3 scripts/fix_myfonts_package_names.py --dry-run
  python3 scripts/fix_myfonts_package_names.py --write
  python3 scripts/fix_myfonts_package_names.py --write --roots web/data data
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any


# Titles that are package slots, not font names (same title reused across families).
GENERIC_PACKAGE_NAMES = {
    "upright",
    "slanted",
    "buying choices",
    "best value",
    "individual styles",
    "family packages",
}


def slug_to_family_name(slug: str) -> str:
    """collections/mizhon-sans-font-skinny-type -> Mizhon Sans"""
    slug = slug.strip("/").split("/")[-1]
    if "-font-" in slug:
        slug = slug.split("-font-", 1)[0]
    parts = slug.split("-")
    return " ".join(p.capitalize() for p in parts if p)


def collection_url_slug(url: str | None) -> str | None:
    if not url or "/collections/" not in url:
        return None
    m = re.search(r"/collections/([^/]+)/?", url)
    return m.group(1) if m else None


def is_package_row(raw: dict[str, Any]) -> bool:
    handle = str(raw.get("handle") or "").lower()
    return "-package-" in handle or "package" in handle


def should_rename_to_slug(name: str, raw: dict[str, Any]) -> bool:
    if not raw.get("collection_url"):
        return False
    if not is_package_row(raw):
        return False
    n = name.strip().lower()
    if n in GENERIC_PACKAGE_NAMES:
        return True
    if n.endswith(" complete family"):
        return True
    # Short single-word titles that are likely package rows when handle has package
    if len(name.split()) <= 2 and "-package-" in str(raw.get("handle") or ""):
        return True
    return False


def fix_release(release: dict[str, Any]) -> bool:
    """Mutate release in place. Returns True if changed."""
    if release.get("source_id") != "myfonts":
        return False
    raw = release.get("raw")
    if not isinstance(raw, dict):
        return False
    name = str(release.get("name") or "").strip()
    if not name:
        return False
    changed = False

    # 1) Strip " Complete Family"
    suffix = " Complete Family"
    if name.endswith(suffix):
        release["name"] = name[: -len(suffix)].strip()
        name = release["name"]
        changed = True

    # 2) Generic package title + collection → name from slug
    if should_rename_to_slug(name, raw):
        slug = collection_url_slug(release.get("source_url")) or collection_url_slug(
            raw.get("collection_url")
        )
        if slug:
            new_name = slug_to_family_name(slug)
            if new_name and new_name != name:
                release["name"] = new_name
                changed = True

    return changed


def dedupe_by_collection_url(releases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """
    Keep one release per collection URL when multiple package rows point to
    same family. Prefer: has image_url, longer name, stable release_id.
    """
    from urllib.parse import urlparse

    def score(r: dict[str, Any]) -> tuple:
        url = r.get("source_url") or ""
        if "/collections/" not in url:
            return (0,)  # don't dedupe
        img = 1 if r.get("image_url") else 0
        name_len = len(str(r.get("name") or ""))
        # Prefer debut date in release_date
        date = str(r.get("release_date") or "")
        return (img, name_len, date)

    by_collection: dict[str, list[dict[str, Any]]] = {}
    rest: list[dict[str, Any]] = []
    for r in releases:
        if r.get("source_id") != "myfonts":
            rest.append(r)
            continue
        url = r.get("source_url") or ""
        if "/collections/" in url and is_package_row(r.get("raw") or {}):
            key = urlparse(url).path.rstrip("/") or url
            by_collection.setdefault(key, []).append(r)
        else:
            rest.append(r)

    removed = 0
    kept: list[dict[str, Any]] = list(rest)
    for _key, group in by_collection.items():
        if len(group) <= 1:
            kept.extend(group)
            continue
        group.sort(key=score, reverse=True)
        kept.append(group[0])
        removed += len(group) - 1

    # Preserve original order as much as possible: not trivial; simpler to sort by release_date desc
    return kept, removed


def process_file(path: Path, write: bool, dedupe: bool) -> tuple[int, int]:
    """Returns (modified_count, dedupe_removed)."""
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, list):
        return 0, 0
    modified = 0
    for item in data:
        if fix_release(item):
            modified += 1
    dedupe_removed = 0
    if dedupe:
        new_list, dedupe_removed = dedupe_by_collection_url(data)
        data.clear()
        data.extend(new_list)
    if write and (modified or dedupe_removed):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return modified, dedupe_removed


def main() -> None:
    ap = argparse.ArgumentParser(description="Fix MyFonts package display names in JSON snapshots.")
    ap.add_argument("--write", action="store_true", help="Write changes to disk")
    ap.add_argument("--dry-run", action="store_true", help="Print only (default if --write not set)")
    ap.add_argument("--dedupe", action="store_true", help="Collapse multiple package rows per collection URL")
    ap.add_argument(
        "--roots",
        nargs="*",
        default=["web/data/myfonts", "data/myfonts"],
        help="Roots to scan for all_releases.json",
    )
    args = ap.parse_args()
    write = args.write and not args.dry_run

    roots = [Path(r) for r in args.roots]
    files: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        files.extend(root.rglob("all_releases.json"))
        files.extend(root.rglob("new_releases.json"))

    total_modified = 0
    total_deduped = 0
    for f in sorted(set(files)):
        m, d = process_file(f, write=write, dedupe=args.dedupe)
        if m or d:
            print(f"{f}: renamed={m} dedupe_removed={d} wrote={write}")
        total_modified += m
        total_deduped += d

    print(f"Total releases renamed: {total_modified}, dedupe removed: {total_deduped}, write={write}")


if __name__ == "__main__":
    main()
