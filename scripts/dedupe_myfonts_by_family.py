#!/usr/bin/env python3
"""
Одноразовый дедуп all_releases MyFonts по семье (один релиз на семью).
Читает data/myfonts/<source_dir>/all_releases.json, пишет в data/myfonts/<target_dir>/.
Используется чтобы заменить старый снимок с 1767 продуктами на ~1k семей без повторного краула.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_MF = ROOT / "data" / "myfonts"


def _normalize_collection_url(url: str) -> str:
    if not url or not url.strip():
        return ""
    u = url.strip().lower().rstrip("/").split("?")[0].rstrip("/")
    return u


def _family_key_from_name(name: str) -> str:
    if not name or not name.strip():
        return ""
    key = name.strip().lower()
    if " + " in key:
        key = key.split(" + ")[0].strip()
    for suffix in (
        " complete family",
        " family package",
        " package",
        " bundle",
        " one",
        " two",
        " three",
        " four",
        " five",
        " six",
        " flaca",
        " fina",
        " thin",
        " light",
        " regular",
        " bold",
        " black",
        " rough italic",
        " liner",
        " chalk",
        " chalky",
        " italic",
        " semibold",
        " medium",
        " condensed",
        " extended",
        " narrow",
        " wide",
        " rounded",
        " stencil",
        " display",
        " text",
        " caption",
        " extralight",
    ):
        if key.endswith(suffix):
            key = key[: -len(suffix)].strip()
    return key or ""


def _family_key_from_product_slug(product_url: str) -> str:
    if not product_url or "/products/" not in product_url:
        return ""
    parts = product_url.rstrip("/").split("/products/")
    if len(parts) < 2:
        return ""
    slug = parts[-1].split("?")[0].lower()
    for suffix in ("-package", "-bundle", "-family"):
        if slug.endswith(suffix):
            slug = slug[: -len(suffix)].strip("-")
    id_match = re.search(r"-(\d+)$", slug)
    if id_match:
        slug = slug[: id_match.start()].strip("-")
    if not slug:
        return ""
    words = slug.replace("-", " ").split()
    seen: set[str] = set()
    out: list[str] = []
    for w in words:
        if w in seen:
            break
        seen.add(w)
        out.append(w)
    base = " ".join(out).strip() if out else ""
    return _family_key_from_name(base) if base else ""


def canonical_family_key(release: dict) -> str | None:
    raw = release.get("raw") or {}
    coll = raw.get("collection_url")
    if coll:
        n = _normalize_collection_url(coll)
        if n:
            return f"url:{n}"
    product_url = raw.get("product_url") or release.get("source_url") or ""
    if product_url and "/collections/" in product_url and "whats-new" not in product_url.lower():
        n = _normalize_collection_url(product_url)
        if n:
            return f"url:{n}"
    name = release.get("name") or ""
    k = _family_key_from_name(name)
    if k:
        return f"name:{k}"
    slug_key = _family_key_from_product_slug(product_url)
    if slug_key:
        return f"name:{slug_key}"
    return None


def _is_bundle(r: dict) -> bool:
    if (r.get("raw") or {}).get("is_package_product"):
        return True
    n = (r.get("name") or "").lower()
    return "package" in n or "bundle" in n or "complete family" in n


def _has_family_link(r: dict) -> bool:
    """Есть ссылка на семью: collection_url или source_url — страница коллекции."""
    c = (r.get("raw") or {}).get("collection_url")
    if c and isinstance(c, str) and c.startswith("http"):
        return True
    url = (r.get("source_url") or "").lower()
    return "/collections/" in url and "whats-new" not in url


def _product_without_family(r: dict) -> bool:
    return not _has_family_link(r)


def _prefer_release(a: dict, b: dict) -> dict:
    """Приоритет: collection_url, затем не bundle."""
    ra, rb = (a.get("raw") or {}).get("collection_url"), (b.get("raw") or {}).get("collection_url")
    a_has, b_has = ra and str(ra).startswith("http"), rb and str(rb).startswith("http")
    if a_has and not b_has:
        return a
    if b_has and not a_has:
        return b
    if _is_bundle(a) and not _is_bundle(b):
        return b
    if _is_bundle(b) and not _is_bundle(a):
        return a
    return a


def _prefer_with_collection_url(a: dict, b: dict) -> dict:
    return _prefer_release(a, b)


def _apply_family_link(release: dict) -> dict:
    """Подменить source_url на collection_url только если он реально есть в данных (со страницы).
    Угадывать /collections/<family>-font-<foundry> не делаем: такая страница может быть «no longer available».
    """
    out = dict(release)
    raw = out.get("raw") or {}
    coll = raw.get("collection_url")
    if coll and isinstance(coll, str) and coll.startswith("http"):
        out["source_url"] = coll
    return out


def main() -> None:
    import json
    import sys
    source_dir = DATA_MF / "2026-03-09"
    target_dir = DATA_MF / "2026-03-10"
    if len(sys.argv) >= 2:
        source_dir = Path(sys.argv[1])
    if len(sys.argv) >= 3:
        target_dir = Path(sys.argv[2])
    if not source_dir.exists():
        print(f"Missing {source_dir}")
        return
    path = source_dir / "all_releases.json"
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        print("Invalid all_releases.json")
        return
    rows = [r for r in rows if r.get("source_id") == "myfonts"]
    seen: dict[str, dict] = {}
    for r in rows:
        key = canonical_family_key(r)
        if not key:
            key = r.get("release_id") or r.get("source_url") or ""
        if not key:
            continue
        if key not in seen:
            seen[key] = r
        else:
            seen[key] = _prefer_with_collection_url(seen[key], r)
    deduped = [_apply_family_link(r) for r in seen.values() if _has_family_link(r)]
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "all_releases.json").write_text(
        json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (target_dir / "new_releases.json").write_text(
        json.dumps([], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Wrote {len(deduped)} releases (one per family) to {target_dir}")


if __name__ == "__main__":
    main()
