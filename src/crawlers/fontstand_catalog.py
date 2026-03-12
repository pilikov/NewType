"""
Fontstand catalog crawler (stages 1–4).

Stage 1: Base data from /fonts/filteredfonts + release_date from New Releases.
Stage 2: Scripts (письменности) via API фильтров: сначала encodings (Latin, Cyrillic…),
         затем языки (languages[id]) → по языку определяется письменность, запрос фильтра по языку.
Stage 3: Category and Features via filter reverse-mapping.
Stage 4: Optional detail-page enrichment (designers, category hint).
"""

from __future__ import annotations

import re
import time
from html import unescape
from typing import Any
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from src.crawlers.shared.text import unique_strings
from src.models import FontRelease


def _extract_image_url(html: str, base_url: str = "https://fontstand.com") -> str | None:
    """Extract first img src from Image HTML snippet."""
    if not html or not isinstance(html, str):
        return None
    # Handle both " and \" in JSON-decoded string
    m = re.search(r'src=["\']([^"\']+)["\']', html)
    if not m:
        return None
    path = unescape(m.group(1).strip())
    if path.startswith("http"):
        return path
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def _parse_foundry_title(foundry_title: str) -> tuple[list[str], int | None]:
    """Parse FoundryTitle like '14 styles<br>TypeMates' -> (authors, styles_count)."""
    authors: list[str] = []
    styles_count: int | None = None
    if not foundry_title or not isinstance(foundry_title, str):
        return authors, styles_count
    parts = re.split(r"<br\s*/?>", foundry_title, flags=re.I)
    for part in parts:
        part = re.sub(r"\s+", " ", part).strip()
        if not part:
            continue
        # "14 styles" or "1 style"
        match = re.match(r"^(\d+)\s*style(s)?\s*$", part, re.I)
        if match:
            styles_count = int(match.group(1))
            continue
        authors.append(part)
    return unique_strings(authors), styles_count


def _fetch_filteredfonts_page(
    session: requests.Session,
    url: str,
    start: int,
    timeout: int,
    referer: str = "https://fontstand.com/fonts/",
    extra_params: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    params: dict[str, str | int] = {"start": start}
    if extra_params:
        params.update(extra_params)
    resp = session.get(
        url,
        params=params,
        headers={
            "Referer": referer,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json() if resp.text.strip() else None


def _fetch_new_releases_dates(
    session: requests.Session,
    rss_url: str,
    loadmore_url: str | None,
    timeout: int,
) -> dict[tuple[str, str], str]:
    """
    Build (name_normalized, foundry_normalized) -> release_date (YYYY-MM-DD).
    Uses RSS and optionally loadMore pages.
    """
    from datetime import datetime

    key_to_date: dict[tuple[str, str], str] = {}
    referer = "https://fontstand.com/news/new-releases/"

    # RSS
    try:
        r = session.get(rss_url, timeout=timeout, headers={"Accept": "application/xml"})
        r.raise_for_status()
    except Exception:
        return key_to_date

    # Simple RSS item parse: <item>...<title>X</title>...<description><![CDATA[by Y]]>...<pubDate>...
    title_pattern = re.compile(r"<title>([^<]+)</title>", re.I)
    desc_pattern = re.compile(r"<description>(?:<!\[CDATA\[)?(?:by\s+)?([^\]<]+)", re.I)
    pub_pattern = re.compile(r"<pubDate>([^<]+)</pubDate>", re.I)
    text = r.text
    pos = 0
    while True:
        item_start = text.find("<item>", pos)
        if item_start == -1:
            break
        item_end = text.find("</item>", item_start)
        if item_end == -1:
            break
        block = text[item_start:item_end]
        title_m = title_pattern.search(block)
        desc_m = desc_pattern.search(block)
        pub_m = pub_pattern.search(block)
        if title_m and pub_m:
            name = re.sub(r"\s+", " ", title_m.group(1)).strip()
            foundry = (desc_m.group(1).strip() if desc_m else "").strip()
            if foundry and foundry.lower().startswith("by "):
                foundry = foundry[3:].strip()
            try:
                dt = datetime.strptime(pub_m.group(1).strip()[:25], "%a, %d %b %Y %H:%M:%S")
                date_str = dt.strftime("%Y-%m-%d")
            except ValueError:
                date_str = pub_m.group(1).strip()[:10]
            if name:
                key = (name.lower(), foundry.lower())
                key_to_date[key] = date_str
        pos = item_end + 1

    # Load more pages (start=0 gives first "next" batch; we need start=9, 18, ... for subsequent)
    if not loadmore_url:
        return key_to_date
    start = 9
    while True:
        time.sleep(0.3)
        try:
            r = session.get(
                loadmore_url,
                params={"url": "news%2Fnew-releases%2F", "start": start},
                headers={"Referer": referer, "X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
                timeout=timeout,
            )
            r.raise_for_status()
            data = r.json()
        except Exception:
            break
        if data.get("last") is True:
            break
        for html_fragment in data.get("data") or []:
            if not isinstance(html_fragment, str):
                continue
            # <h2 class="article-post__title" ...>Title</h2>, standfirst "by Foundry", footer "26 Sep 2025"
            title_m = re.search(r'class="article-post__title"[^>]*>\s*([^<]+)\s*<', html_fragment)
            stand_m = re.search(r"article-post__standfirst[^>]*>\s*by\s+([^<]+)<", html_fragment)
            meta_m = re.search(r"article-post__meta[^>]*>\s*(\d{1,2}\s+\w+\s+\d{4})", html_fragment)
            if title_m and meta_m:
                name = re.sub(r"\s+", " ", title_m.group(1)).strip()
                foundry = (stand_m.group(1).strip() if stand_m else "").strip()
                raw_date = meta_m.group(1).strip()
                try:
                    dt = datetime.strptime(raw_date, "%d %b %Y")
                    date_str = dt.strftime("%Y-%m-%d")
                except ValueError:
                    date_str = raw_date
                if name:
                    key = (name.lower(), foundry.lower())
                    key_to_date[key] = date_str
        start += 9
        if start > 500:  # safety
            break

    return key_to_date


def _fetch_filter_options(
    session: requests.Session,
    options_url: str,
    type_param: str,
    timeout: int,
    referer: str = "https://fontstand.com/fonts/",
) -> str:
    """GET FilterV2?type=X, return items HTML or empty string."""
    try:
        r = session.get(
            options_url,
            params={"type": type_param},
            headers={
                "Referer": referer,
                "X-Requested-With": "XMLHttpRequest",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
        r.raise_for_status()
        data = r.json()
        return str(data.get("items") or "")
    except Exception:
        return ""


def _parse_languages_options(html: str) -> list[tuple[str, str]]:
    """
    Parse FilterV2?type=languages items HTML.
    Returns list of (encoding_id, script_name) e.g. ("1", "Latin").
    Script name comes from left column <a data-pos="N">; encoding ids from ul-holder data-pos=N.
    """
    out: list[tuple[str, str]] = []
    if not html:
        return out
    # Left column: <a data-pos="1">Latin</a>, <a data-pos="2">Arabic</a>, ...
    left_items = re.findall(r'<a\s+data-pos="(\d+)"\s*>([^<]+)</a>', html)
    pos_to_script: dict[str, str] = {}
    for pos, name in left_items:
        name = re.sub(r"\s+", " ", name).strip()
        if name and name != "Encodings" and name != "Languages" and len(name) < 30:
            pos_to_script[pos] = name
    # Right: <div class="ul-holder" data-pos="1"> ... <input ... name="encodings[1]" value="1" data-type="encodings" data-value="1">
    for pos, script_name in pos_to_script.items():
        block = re.search(
            rf'<div\s+class="ul-holder"\s+data-pos="{re.escape(pos)}"[^>]*>(.*?)</div>\s*</div>',
            html,
            re.DOTALL,
        )
        if not block:
            continue
        block_html = block.group(1)
        for m in re.finditer(
            r'<input[^>]+name="encodings\[(\d+)\]"[^>]+(?:data-value="(\d+)"|value="(\d+)")',
            block_html,
        ):
            enc_id = m.group(2) or m.group(3) or m.group(1)
            out.append((enc_id, script_name))
    # Fallback: any encodings input with data-value
    if not out:
        for m in re.finditer(r'data-type="encodings"[^>]+data-value="(\d+)"', html):
            out.append((m.group(1), "Latin"))  # default
    return out


# Маркерный язык для каждой письменности Fontstand (один запрос на скрипт вместо сотен по языкам).
# Подобрано по FilterV2?type=languages: id языка и его label.
SCRIPT_MARKER_LANGUAGE_IDS: dict[str, str] = {
    "Latin": "393",      # English
    "Arabic": "626",     # Arabic
    "Cyrillic": "511",   # Russian
    "Greek": "512",      # Greek
    "Armenian": "612",   # Armenian
    "Indic": "610",      # Hindi
    "Hebrew": "594",     # Hebrew
    "Chinese": "698",    # Chinese (Simplified)
    "Hangul": "689",     # Korean
    "Japanese": "732",   # Japanese
    "Thai": "734",       # Thai
    "Georgian": "756",   # Georgian
}


def _parse_language_to_script(html: str) -> list[tuple[str, str]]:
    """
    Parse FilterV2?type=languages: for each language checkbox (languages[id])
    determine parent script from ul-holder data-pos.
    Returns list of (language_id, script_name) e.g. ("547", "Cyrillic").
    Used to get scripts via languages: request filter by language, assign script to returned slugs.
    """
    out: list[tuple[str, str]] = []
    if not html:
        return out
    # Left column: data-pos -> script name
    left_items = re.findall(r'<a\s+data-pos="(\d+)"\s*>([^<]+)</a>', html)
    pos_to_script: dict[str, str] = {}
    for pos, name in left_items:
        name = re.sub(r"\s+", " ", name).strip()
        if name and name not in ("Encodings", "Languages") and len(name) < 30:
            pos_to_script[pos] = name
    # Right: each <div class="ul-holder" data-pos="N"> contains <input name="languages[XXX]" value="XXX">
    for pos, script_name in pos_to_script.items():
        block = re.search(
            rf'<div\s+class="ul-holder"\s+data-pos="{re.escape(pos)}"[^>]*>(.*?)</div>\s*</div>',
            html,
            re.DOTALL,
        )
        if not block:
            continue
        block_html = block.group(1)
        for m in re.finditer(r'name="languages\[(\d+)\]"[^>]*(?:value="(\d+)"|data-value="(\d+)")', block_html):
            lang_id = m.group(2) or m.group(3) or m.group(1)
            out.append((lang_id, script_name))
    return out


def _parse_checkbox_options(html: str, name_prefix: str, id_group: str) -> list[tuple[str, str]]:
    """
    Parse FilterV2 items HTML for catparams or features (checkboxes name="catparams[N]" or "features[N]").
    Returns list of (value_id, display_name).
    """
    out: list[tuple[str, str]] = []
    if not html:
        return out
    # <input ... name="catparams[4]" value="4" id="catparams_4" data-tagtitle="Serif Oldstyle">
    # <label for="catparams_4">Oldstyle</label>
    for m in re.finditer(rf'name="{re.escape(name_prefix)}\[(\d+)\]"[^>]*>', html):
        value_id = m.group(1)
        block_start = m.start()
        block_end = html.find(">", m.end()) + 1
        tag = html[block_start:block_end]
        value_m = re.search(r'value="(\d+)"', tag)
        if value_m:
            value_id = value_m.group(1)
        id_m = re.search(rf'id="{re.escape(id_group)}_(\d+)"', tag)
        idx = id_m.group(1) if id_m else value_id
        tagtitle_m = re.search(r'data-tagtitle="([^"]*)"', tag)
        tagtitle = (tagtitle_m.group(1) or "").strip() if tagtitle_m else ""
        label_m = re.search(rf'<label\s+for="{re.escape(id_group)}_{re.escape(idx)}"\s*>([^<]+)</label>', html)
        display = (label_m.group(1).strip() if label_m else tagtitle) or value_id
        display = re.sub(r"\s+", " ", display).strip()
        out.append((value_id, display))
    return out


def _fetch_filtered_slugs(
    session: requests.Session,
    filter_url: str,
    filter_key: str,
    filter_value: str,
    page_size: int,
    delay: float,
    timeout: int,
    referer: str,
) -> set[str]:
    """
    GET FilterV2 with one filter param in query string, paginate, return set of font slugs.
    Filter works only with GET (POST returns full catalog).
    """
    slugs: set[str] = set()
    start = 0
    while True:
        if delay > 0:
            time.sleep(delay)
        try:
            resp = session.get(
                filter_url,
                params={"start": start, filter_key: filter_value},
                headers={
                    "Referer": referer,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                },
                timeout=timeout,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception:
            break
        if not payload.get("Good"):
            break
        data = payload.get("Data") or []
        if not data:
            break
        for item in data:
            if not isinstance(item, dict):
                continue
            link = (item.get("Link") or "").strip()
            if link.startswith("fonts/"):
                slug = link.replace("fonts/", "").strip().rstrip("/")
                if slug:
                    slugs.add(slug)
        if len(data) < page_size:
            break
        start += page_size
        if start >= 50000:
            break
    return slugs


def _enrich_from_family_page(
    session: requests.Session,
    slug: str,
    base_url: str,
    timeout: int,
) -> tuple[list[str], list[str], str | None]:
    """
    Fetch /fonts/{slug}, parse Designers and optional category from description.
    Returns (designers_list, scripts_from_page, category_hint).
    """
    url = f"{base_url.rstrip('/')}/fonts/{slug}"
    designers: list[str] = []
    scripts: list[str] = []
    category_hint: str | None = None
    try:
        r = session.get(url, timeout=timeout, headers={"Accept": "text/html"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        # Table: | Foundry | ... |  | Designers | Name1 , Name2 |  | More Info | ... |
        for row in soup.find_all("tr"):
            cells = row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            label = (cells[0].get_text() or "").strip()
            value = (cells[1].get_text() or "").strip()
            if re.match(r"designers?", label, re.I):
                for part in re.split(r"[,&]", value):
                    name = re.sub(r"\s+", " ", part).strip()
                    if name and len(name) > 1:
                        designers.append(name)
                break
        # Optional: category from description (e.g. "Slab Serif", "Sans")
        desc = soup.find(class_=re.compile(r"description|intro|body", re.I)) or soup.find("main") or soup
        if desc:
            desc_text = desc.get_text() or ""
            for hint in ["Slab Serif", "Slab", "Sans", "Serif", "Script", "Display", "Decorative", "Oldstyle", "Modern", "Geometric", "Humanist", "Grotesque"]:
                if re.search(rf"\b{re.escape(hint)}\b", desc_text, re.I):
                    category_hint = hint
                    break
    except Exception:
        pass
    return unique_strings(designers), scripts, category_hint


class FontstandCatalogCrawler:
    """Stages 1–3: catalog + release_date + scripts + category + features."""

    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config
        self.release_callback: Any = None

    def set_release_callback(self, callback: Any) -> None:
        self.release_callback = callback

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontRelease]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = self.source_config.get("base_url", "https://fontstand.com").rstrip("/")
        referer = f"{base_url}/fonts/"

        crawl_cfg = self.source_config.get("crawl", {})
        filteredfonts_url = crawl_cfg.get("filteredfonts_url", f"{base_url}/fonts/filteredfonts")
        page_size = int(crawl_cfg.get("page_size", 64))
        delay = float(crawl_cfg.get("request_delay_seconds", 0.5))
        enable_new_releases = bool(crawl_cfg.get("enable_new_releases_enrichment", True))
        rss_url = crawl_cfg.get("new_releases_rss_url", f"{base_url}/news/new-releases/rss")
        loadmore_url = crawl_cfg.get("new_releases_loadmore_url")
        enable_scripts = bool(crawl_cfg.get("enable_scripts_enrichment", True))
        enable_scripts_via_languages = bool(crawl_cfg.get("enable_scripts_via_languages", True))
        enable_category = bool(crawl_cfg.get("enable_category_enrichment", True))
        enable_features = bool(crawl_cfg.get("enable_features_enrichment", True))
        max_scripts_filters = int(crawl_cfg.get("max_scripts_filters", 20))
        max_category_filters = int(crawl_cfg.get("max_category_filters", 0))  # 0 = all
        max_features_filters = int(crawl_cfg.get("max_features_filters", 30))
        enable_detail_enrichment = bool(crawl_cfg.get("enable_detail_enrichment", False))
        detail_fetch_limit = int(crawl_cfg.get("detail_fetch_limit", 0))  # 0 = off
        detail_delay = float(crawl_cfg.get("detail_delay_seconds", 1.0))

        new_releases_dates: dict[tuple[str, str], str] = {}
        if enable_new_releases:
            new_releases_dates = _fetch_new_releases_dates(
                session=session,
                rss_url=rss_url,
                loadmore_url=loadmore_url,
                timeout=timeout,
            )

        releases: list[FontRelease] = []
        slug_to_release: dict[str, FontRelease] = {}
        start = 0
        seen_links: set[str] = set()

        while True:
            if delay > 0:
                time.sleep(delay)
            payload = _fetch_filteredfonts_page(
                session=session,
                url=filteredfonts_url,
                start=start,
                timeout=timeout,
                referer=referer,
            )
            if not payload or not payload.get("Good"):
                break
            data = payload.get("Data") or []
            if not data:
                break
            for item in data:
                if not isinstance(item, dict):
                    continue
                link = (item.get("Link") or "").strip()
                if not link or link in seen_links:
                    continue
                seen_links.add(link)
                slug = link.replace("fonts/", "").strip().rstrip("/")
                if not slug:
                    continue
                title = (item.get("Title") or "").strip()
                if not title:
                    continue
                source_url = f"{base_url}/fonts/{slug}" if slug else None
                authors, _styles_count = _parse_foundry_title(str(item.get("FoundryTitle") or ""))
                image_url = _extract_image_url(str(item.get("Image") or ""), base_url)

                release_date = None
                key = (title.lower(), (authors[0].lower() if authors else ""))
                release_date = new_releases_dates.get(key)

                release = FontRelease(
                    source_id=source_id,
                    source_name=source_name,
                    source_url=source_url,
                    name=title,
                    styles=[],
                    authors=authors,
                    scripts=[],
                    release_date=release_date,
                    image_url=image_url,
                    woff_url=None,
                    specimen_pdf_url=None,
                    raw={
                        "release_identity": f"fontstand:{slug}",
                        "link": link,
                        "foundry_title_raw": item.get("FoundryTitle"),
                    },
                )
                releases.append(release)
                slug_to_release[slug] = release
                if self.release_callback:
                    self.release_callback(release)

            start += page_size
            if len(data) < page_size:
                break
            if start >= 100000:
                break

        if not releases:
            return releases

        script_map: dict[str, list[str]] = {}
        category_map: dict[str, list[str]] = {}
        feature_map: dict[str, list[str]] = {}

        total_slugs = len(slug_to_release)
        filter_effective_threshold = max(1, int(total_slugs * 0.9))  # if result >= 90% of catalog, filter likely ignored

        if enable_scripts or enable_category or enable_features:
            filter_v2_url = f"{base_url}/fonts/FilterV2"

            if enable_scripts:
                html = _fetch_filter_options(session, filter_v2_url, "languages", timeout, referer)
                # 1) Письменности через encodings (Latin, Cyrillic, Arabic, ...)
                encoding_to_script = _parse_languages_options(html)
                if max_scripts_filters > 0:
                    encoding_to_script = encoding_to_script[:max_scripts_filters]
                for enc_id, script_name in encoding_to_script:
                    slugs = _fetch_filtered_slugs(
                        session, filter_v2_url, f"encodings[{enc_id}]", enc_id, page_size, delay, timeout, referer
                    )
                    if len(slugs) < filter_effective_threshold:
                        for slug in slugs:
                            script_map.setdefault(slug, []).append(script_name)
                # 2) Письменности через маркерные языки: один запрос на скрипт (English→Latin, Russian→Cyrillic и т.д.)
                if enable_scripts_via_languages:
                    for script_name, lang_id in SCRIPT_MARKER_LANGUAGE_IDS.items():
                        slugs = _fetch_filtered_slugs(
                            session,
                            filter_v2_url,
                            f"languages[{lang_id}]",
                            lang_id,
                            page_size,
                            delay,
                            timeout,
                            referer,
                        )
                        if len(slugs) < filter_effective_threshold:
                            for slug in slugs:
                                script_map.setdefault(slug, []).append(script_name)
                for slug in script_map:
                    script_map[slug] = unique_strings(script_map[slug])

            if enable_category:
                html = _fetch_filter_options(session, filter_v2_url, "catparams", timeout, referer)
                cat_options = _parse_checkbox_options(html, "catparams", "catparams")
                if max_category_filters > 0:
                    cat_options = cat_options[:max_category_filters]
                for value_id, display_name in cat_options:
                    slugs = _fetch_filtered_slugs(
                        session, filter_v2_url, f"catparams[{value_id}]", value_id, page_size, delay, timeout, referer
                    )
                    if len(slugs) < filter_effective_threshold:
                        for slug in slugs:
                            category_map.setdefault(slug, []).append(display_name or value_id)
                for slug in category_map:
                    category_map[slug] = unique_strings(category_map[slug])

            if enable_features:
                html = _fetch_filter_options(session, filter_v2_url, "features", timeout, referer)
                feat_options = _parse_checkbox_options(html, "features", "features")
                if max_features_filters > 0:
                    feat_options = feat_options[:max_features_filters]
                for value_id, display_name in feat_options:
                    slugs = _fetch_filtered_slugs(
                        session, filter_v2_url, f"features[{value_id}]", value_id, page_size, delay, timeout, referer
                    )
                    if len(slugs) < filter_effective_threshold:
                        for slug in slugs:
                            feature_map.setdefault(slug, []).append(display_name or value_id)
                for slug in feature_map:
                    feature_map[slug] = unique_strings(feature_map[slug])

        for slug, release in slug_to_release.items():
            release.scripts = script_map.get(slug, [])
            release.raw["categories"] = category_map.get(slug, [])
            release.raw["features"] = feature_map.get(slug, [])

        # Stage 4: optional detail-page enrichment (designers, category hint)
        if enable_detail_enrichment and detail_fetch_limit > 0:
            slugs_to_enrich = list(slug_to_release.keys())[:detail_fetch_limit]
            for i, slug in enumerate(slugs_to_enrich):
                if detail_delay > 0 and i > 0:
                    time.sleep(detail_delay)
                release = slug_to_release[slug]
                designers, scripts_from_page, category_hint = _enrich_from_family_page(
                    session, slug, base_url, timeout
                )
                if designers:
                    release.authors = unique_strings(list(release.authors) + designers)
                if scripts_from_page:
                    release.scripts = unique_strings(list(release.scripts) + scripts_from_page)
                if category_hint and isinstance(release.raw.get("categories"), list):
                    if category_hint not in release.raw["categories"]:
                        release.raw["categories"] = release.raw["categories"] + [category_hint]
                elif category_hint:
                    release.raw["categories"] = [category_hint]

        return releases
