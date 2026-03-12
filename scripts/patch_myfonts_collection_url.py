#!/usr/bin/env python3
"""
Точечно добавить collection_url в релизы MyFonts с collection_url=None.

Использует ту же логику derive, что и myfonts_api._derive_collection_url_from_product:
handle + vendor (authors[0]) -> /collections/{family_slug}-font-{vendor_slug}

Usage:
  python3 scripts/patch_myfonts_collection_url.py --dry-run
  python3 scripts/patch_myfonts_collection_url.py --write --roots web/data/myfonts
  # Только Solvane, Munch Platter, Todays Island (проверенные URL):
  python3 scripts/patch_myfonts_collection_url.py --write --only "Munch Platter Complete Family" "Solvane Complete Family" "Todays Island Complete Family"
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.parse import urljoin


BASE_URL = "https://www.myfonts.com"


def derive_collection_url(handle: str, vendor: str) -> str | None:
    """Строит URL коллекции из handle и vendor (как в myfonts_api)."""
    handle = str(handle or "").strip().lower()
    vendor = str(vendor or "").strip()
    if not handle or not vendor:
        return None
    family_slug = re.sub(
        r"-(?:complete-?family|family-?package|package|bundle)(?:-\d+)?$",
        "",
        handle,
        flags=re.IGNORECASE,
    ).strip("-")
    # MyFonts collection URLs используют только имя семьи, без -complete
    if family_slug.endswith("-complete"):
        family_slug = family_slug[:-9]
    if not family_slug:
        return None
    vendor_slug = re.sub(r"[^\w\s-]", "", vendor.lower()).strip()
    vendor_slug = re.sub(r"\s+", "-", vendor_slug).strip("-")
    if not vendor_slug:
        return None
    path = f"/collections/{family_slug}-font-{vendor_slug}"
    return urljoin(BASE_URL, path)


def patch_release(
    r: dict,
    only_names: set[str] | None = None,
    force: bool = False,
) -> bool:
    """Обновляет релиз с collection_url=None. Возвращает True если был обновлён."""
    raw = r.get("raw") or {}
    if raw.get("collection_url") and not force:
        return False
    if only_names is not None and (r.get("name") or "").strip() not in only_names:
        return False
    handle = raw.get("handle")
    authors = r.get("authors") or []
    vendor = authors[0] if authors else ""
    if not handle or not vendor:
        return False
    collection_url = derive_collection_url(handle, vendor)
    if not collection_url:
        return False
    raw["collection_url"] = collection_url
    r["source_url"] = collection_url
    r["raw"] = raw
    return True


def find_files(root: Path) -> list[Path]:
    """Находит all_releases.json и new_releases.json в дереве."""
    out: list[Path] = []
    for p in root.rglob("all_releases.json"):
        if "myfonts" in str(p):
            out.append(p)
    for p in root.rglob("new_releases.json"):
        if "myfonts" in str(p):
            out.append(p)
    return sorted(set(out))


def main() -> None:
    ap = argparse.ArgumentParser(description="Patch collection_url for MyFonts releases")
    ap.add_argument("--dry-run", action="store_true", help="Не записывать.")
    ap.add_argument("--write", action="store_true", help="Записать изменения.")
    ap.add_argument(
        "--roots",
        nargs="+",
        default=["web/data/myfonts"],
        help="Корни для поиска JSON.",
    )
    ap.add_argument(
        "--only",
        nargs="+",
        metavar="NAME",
        help="Патчить только релизы с этими именами (точечно).",
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="Перезаписать даже если collection_url уже есть (для исправления ошибочных).",
    )
    args = ap.parse_args()
    if not args.write and not args.dry_run:
        args.dry_run = True

    only_names = frozenset((args.only or [])) or None

    total_patched = 0
    for root_str in args.roots:
        root = Path(root_str)
        if not root.exists():
            print(f"Skip {root}: not found")
            continue
        for fp in find_files(root):
            data = json.loads(fp.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                continue
            patched = 0
            for r in data:
                if r.get("source_id") != "myfonts":
                    continue
                if patch_release(r, only_names=only_names, force=args.force):
                    patched += 1
                    if args.dry_run:
                        print(f"  [dry] {fp}: {r.get('name')} -> {r.get('source_url')}")
            if patched:
                total_patched += patched
                if args.write:
                    fp.write_text(
                        json.dumps(data, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    print(f"Wrote {fp}: {patched} patched")
    if args.dry_run and total_patched:
        print(f"\n[dry-run] Would patch {total_patched} releases. Run with --write to apply.")
    elif total_patched == 0:
        print("No releases to patch (all already have collection_url or missing handle/vendor).")


if __name__ == "__main__":
    main()
