#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

SCRIPT_ORDER = ["Latin", "Cyrillic", "Greek", "Arabic", "Hebrew", "Devanagari", "Thai", "Japanese", "Korean", "Chinese"]
LANGUAGE_TO_SCRIPT = {
    "arabic": "Arabic",
    "persian": "Arabic",
    "urdu": "Arabic",
    "pashto": "Arabic",
    "kurdish": "Arabic",
    "uyghur": "Arabic",
    "uighur": "Arabic",
    "sindhi": "Arabic",
    "greek": "Greek",
    "hebrew": "Hebrew",
    "yiddish": "Hebrew",
    "russian": "Cyrillic",
    "ukrainian": "Cyrillic",
    "belarusian": "Cyrillic",
    "bulgarian": "Cyrillic",
    "serbian": "Cyrillic",
    "macedonian": "Cyrillic",
    "kazakh": "Cyrillic",
    "kyrgyz": "Cyrillic",
    "tajik": "Cyrillic",
    "mongolian": "Cyrillic",
    "hindi": "Devanagari",
    "marathi": "Devanagari",
    "nepali": "Devanagari",
    "sanskrit": "Devanagari",
    "thai": "Thai",
    "japanese": "Japanese",
    "korean": "Korean",
    "chinese": "Chinese",
    "mandarin": "Chinese",
    "cantonese": "Chinese",
}

DATA_DIR = Path("data/myfonts")
CACHE_PATH = Path("state/myfonts_scripts_cache.json")
STORAGE_STATE = Path("state/myfonts_storage_state.json")


def merge_url_params(url: str, extra: dict[str, str]) -> str:
    split = urlsplit(url)
    pairs = parse_qsl(split.query, keep_blank_values=True)
    for k, v in extra.items():
        pairs.append((k, v))
    query = urlencode(pairs)
    return urlunsplit((split.scheme, split.netloc, split.path, query, split.fragment))


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def extract_block(text: str, label: str) -> str:
    pattern = (
        rf"{re.escape(label)}\s*:?\s*(.+?)"
        r"(?=(?:\s+(?:Supported Scripts|Supported Languages|OpenType Features|OpenType|Features|Styles|Weights|"
        r"Designer|Designers|Publisher|Foundry|MyFonts debut|Downloads))|$)"
    )
    m = re.search(pattern, text, flags=re.IGNORECASE)
    return (m.group(1) if m else "").strip()


def split_tokens(value: str) -> list[str]:
    if not value:
        return []
    return [p.strip(" .") for p in re.split(r",|;|•|\|", value) if p.strip(" .")]


def ordered_unique_scripts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        n = str(v or "").strip()
        if not n:
            continue
        label = next((s for s in SCRIPT_ORDER if s.lower() == n.lower()), n)
        k = label.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(label)
    order_idx = {s: i for i, s in enumerate(SCRIPT_ORDER)}
    return sorted(out, key=lambda x: order_idx.get(x, len(SCRIPT_ORDER)))


def extract_scripts_from_text(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    text = normalize_spaces(soup.get_text(" ", strip=True))
    if not text:
        return []
    scripts_block = extract_block(text, "Supported Scripts")
    explicit = [tok for tok in split_tokens(scripts_block) if tok in SCRIPT_ORDER]
    langs_block = extract_block(text, "Supported Languages")
    lang_tokens = split_tokens(langs_block)
    from_langs = [LANGUAGE_TO_SCRIPT.get(t.lower()) for t in lang_tokens]
    from_langs = [x for x in from_langs if x]
    combined = [*explicit, *from_langs]
    if lang_tokens and not from_langs:
        combined.append("Latin")
    return ordered_unique_scripts(combined)


def extract_collection_url(html: str, base_url: str) -> str | None:
    for match in re.findall(r'href=["\']([^"\']+)["\']', html, flags=re.IGNORECASE):
        href = match.strip().strip("'")
        if "/collections/" not in href:
            continue
        if "-font-" not in href:
            continue
        return urljoin(base_url, href)
    return None


def fetch_html(page, url: str, timeout_sec: int = 10, retries: int = 2) -> tuple[int, str]:
    for attempt in range(retries):
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_sec * 1000)
        except Exception:
            response = None
        status = response.status if response else 599
        if status != 429:
            body = ""
            if response:
                try:
                    body = response.text()
                except Exception:
                    body = ""
            if not body:
                try:
                    body = page.content()
                except Exception:
                    body = ""
            return status, body
        time.sleep(1.5 + attempt * 2.5)
    return 429, ""


def load_rows(files: list[Path]) -> list[dict]:
    rows: list[dict] = []
    for f in files:
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, list):
            continue
        for row in payload:
            if isinstance(row, dict) and row.get("source_id") == "myfonts":
                rows.append(row)
    return rows


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        norm = str(value or "").strip()
        if not norm:
            continue
        key = norm.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    return out


def main() -> int:
    files = sorted(
        p
        for p in DATA_DIR.rglob("*.json")
        if p.name != "downloaded_assets.json"
    )
    if not files:
        print("no myfonts json files found")
        return 0

    if CACHE_PATH.exists():
        try:
            cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
            if not isinstance(cache, dict):
                cache = {}
        except Exception:
            cache = {}
    else:
        cache = {}

    rows = load_rows(files)
    urls = sorted(
        {
            (row.get("source_url") or "").strip()
            for row in rows
            if (row.get("source_url") or "").strip()
        }
    )
    print(f"files={len(files)} rows={len(rows)} unique_urls={len(urls)} cache={len(cache)}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context_args = {
            "locale": "en-US",
        }
        if STORAGE_STATE.exists():
            context_args["storage_state"] = str(STORAGE_STATE)
        context = browser.new_context(**context_args)
        page = context.new_page()

        fetched = 0
        for i, url in enumerate(urls, start=1):
            if url in cache and isinstance(cache[url], list):
                continue
            status, html = fetch_html(page, url)
            if status != 200 or not html:
                continue
            scripts = extract_scripts_from_text(html)
            collection_url = extract_collection_url(html, url) if html else None

            if collection_url:
                status2, html2 = fetch_html(page, merge_url_params(collection_url, {"tab": "techSpecs"}))
                if status2 == 200 and html2:
                    scripts = ordered_unique_scripts(scripts + extract_scripts_from_text(html2))

            cache[url] = scripts
            fetched += 1
            if fetched % 10 == 0:
                CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
                CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
            if i % 10 == 0 or fetched % 10 == 0:
                print(f"progress i={i}/{len(urls)} fetched={fetched} cache={len(cache)}")
            time.sleep(0.4)

        context.close()
        browser.close()

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")

    updated_rows = 0
    for f in files:
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, list):
            continue

        changed = False
        for row in payload:
            if not isinstance(row, dict):
                continue
            if row.get("source_id") != "myfonts":
                continue
            url = (row.get("source_url") or "").strip()
            if not url:
                continue
            if url not in cache:
                continue
            scripts = cache.get(url) or []
            if list(scripts) != list(row.get("scripts") or []):
                row["scripts"] = list(scripts)
                changed = True
                updated_rows += 1

        if changed:
            f.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"done updated_rows={updated_rows} cache_entries={len(cache)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
