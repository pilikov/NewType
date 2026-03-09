from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

from src.crawlers.myfonts_api import MyFontsApiCrawler

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "myfonts"
CONFIG_PATH = ROOT / "config" / "sources.json"
REQUEST_TIMEOUT = 12
DETAIL_DELAY = 0.05


def load_myfonts_cfg() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for source in payload.get("sources", []):
        if source.get("id") == "myfonts":
            return source
    raise RuntimeError("myfonts source config not found")


def release_key(release: dict[str, Any]) -> str:
    rid = str(release.get("release_id") or "").strip()
    if rid:
        return rid
    return "::".join(
        [
            str(release.get("source_id") or ""),
            str(release.get("source_url") or ""),
            str(release.get("name") or ""),
            str(release.get("release_date") or ""),
        ]
    )


def pick_collection_url(release: dict[str, Any]) -> str | None:
    raw = release.get("raw") if isinstance(release.get("raw"), dict) else {}
    collection_url = str(raw.get("collection_url") or "").strip()
    if collection_url:
        return collection_url
    source_url = str(release.get("source_url") or "").strip()
    if "/collections/" in source_url:
        return source_url
    return None


def pick_product_url(release: dict[str, Any]) -> str | None:
    raw = release.get("raw") if isinstance(release.get("raw"), dict) else {}
    product_url = str(raw.get("product_url") or "").strip()
    if product_url:
        return product_url
    source_url = str(release.get("source_url") or "").strip()
    if "/products/" in source_url:
        return source_url
    return None


def load_json(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


def write_json(path: Path, payload: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    myfonts_cfg = load_myfonts_cfg()
    source_cfg = {
        "id": "myfonts",
        "name": myfonts_cfg.get("name", "MyFonts"),
        "base_url": myfonts_cfg.get("base_url", "https://www.myfonts.com"),
        "crawl": myfonts_cfg.get("crawl", {}),
    }

    crawler = MyFontsApiCrawler(source_cfg)
    script_mode = str(myfonts_cfg.get("crawl", {}).get("language_script_signal_mode", "balanced")).strip().lower()
    if script_mode not in {"balanced", "strong"}:
        script_mode = "balanced"
    crawler._language_script_signal_mode = script_mode
    crawler._log_path = None
    crawler._req_no = 0
    crawler._first_429 = None
    crawler._browser_client = None

    json_files = sorted(DATA_DIR.rglob("all_releases.json")) + sorted(DATA_DIR.rglob("new_releases.json"))
    if not json_files:
        print("No MyFonts JSON files found.")
        return

    cache_by_collection: dict[str, tuple[list[str], list[str]]] = {}
    cache_by_product: dict[str, tuple[list[str], list[str]]] = {}
    scripts_by_release: dict[str, tuple[list[str], list[str]]] = {}

    updated_files = 0
    updated_releases = 0
    checked_releases = 0

    with requests.Session() as session:
        session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

        for file_index, file_path in enumerate(json_files, start=1):
            releases = load_json(file_path)
            if not releases:
                continue

            file_changed = False
            for release in releases:
                if str(release.get("source_id") or "") != "myfonts":
                    continue
                checked_releases += 1
                if checked_releases % 25 == 0:
                    print(
                        f"progress checked={checked_releases} updated={updated_releases} "
                        f"file={file_index}/{len(json_files)}"
                    )

                rid = release_key(release)
                if rid in scripts_by_release:
                    scripts, supported_languages = scripts_by_release[rid]
                else:
                    scripts: list[str] = []
                    supported_languages: list[str] = []
                    collection_url = pick_collection_url(release)
                    if collection_url:
                        if collection_url in cache_by_collection:
                            scripts, supported_languages = cache_by_collection[collection_url]
                        else:
                            try:
                                page = crawler._get_with_backoff(
                                    session=session,
                                    url=collection_url,
                                    params={"tab": "techSpecs"},
                                    timeout=REQUEST_TIMEOUT,
                                    delay_seconds=DETAIL_DELAY,
                                )
                                if page is not None:
                                    html = page.text
                                    scripts = crawler._extract_scripts_from_text(html)
                                    if not scripts:
                                        scripts, supported_languages = crawler._extract_scripts_from_tech_metadata_api(
                                            session=session,
                                            tech_specs_html=html,
                                            timeout=REQUEST_TIMEOUT,
                                            detail_request_delay=DETAIL_DELAY,
                                        )
                            except Exception:
                                scripts = []
                                supported_languages = []
                            cache_by_collection[collection_url] = (scripts, supported_languages)

                    if not scripts:
                        product_url = pick_product_url(release)
                        if product_url:
                            if product_url in cache_by_product:
                                scripts, supported_languages = cache_by_product[product_url]
                            else:
                                try:
                                    _, _, _, tech_scripts, tech_supported_languages = crawler._extract_debut_from_product_page(
                                        session=session,
                                        product_url=product_url,
                                        base_url=str(source_cfg.get("base_url")),
                                        timeout=REQUEST_TIMEOUT,
                                        detail_request_delay=DETAIL_DELAY,
                                        fetch_tech_specs_scripts=True,
                                    )
                                    scripts = tech_scripts
                                    supported_languages = tech_supported_languages
                                except Exception:
                                    scripts = []
                                    supported_languages = []
                                cache_by_product[product_url] = (scripts, supported_languages)

                    scripts = [str(v) for v in scripts if str(v).strip()]
                    supported_languages = [str(v) for v in supported_languages if str(v).strip()]
                    scripts_by_release[rid] = (scripts, supported_languages)

                if scripts or supported_languages:
                    release["scripts"] = scripts
                    raw = release.get("raw") if isinstance(release.get("raw"), dict) else {}
                    raw["tech_specs_scripts"] = scripts
                    raw["tech_specs_supported_languages"] = supported_languages
                    release["raw"] = raw
                    file_changed = True
                    updated_releases += 1

            if file_changed:
                write_json(file_path, releases)
                updated_files += 1
                print(f"updated file: {file_path}")

    print("done")
    print(f"checked_releases={checked_releases}")
    print(f"updated_releases={updated_releases}")
    print(f"updated_files={updated_files}")


if __name__ == "__main__":
    main()
