from __future__ import annotations

import argparse
import csv
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

KEYWORD_PATTERNS = [
    re.compile(r"/(news|blog|journal|articles?|updates?|stories|insights)(/|$)", re.IGNORECASE),
    re.compile(r"\b(news|blog|journal|articles?|updates?|stories|insights)\b", re.IGNORECASE),
]

CANDIDATE_PATHS = [
    "/news",
    "/blog",
    "/journal",
    "/articles",
    "/updates",
    "/stories",
    "/insights",
]


@dataclass
class DetectionResult:
    foundry_name: str
    foundry_url: str
    news_section_url: str
    news_section_status: str
    detection_method: str
    checked_at: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Detect studio news sections")
    parser.add_argument("--input-csv", required=True, help="Input CSV with foundry_name, foundry_url")
    parser.add_argument("--output-csv", required=True, help="Output CSV with news_section_url appended")
    parser.add_argument("--checkpoint", required=True, help="Checkpoint JSON path")
    parser.add_argument("--max-workers", type=int, default=12)
    parser.add_argument("--timeout", type=int, default=12)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_site_root(raw_url: str) -> str:
    parsed = urlparse(raw_url.strip())
    scheme = parsed.scheme or "https"
    netloc = parsed.netloc or parsed.path
    return f"{scheme}://{netloc.rstrip('/')}/"


def same_host(a: str, b: str) -> bool:
    return urlparse(a).netloc.lower() == urlparse(b).netloc.lower()


def looks_like_news_url(url: str, text: str) -> bool:
    hay = f"{url} {text}".strip()
    return any(pattern.search(hay) for pattern in KEYWORD_PATTERNS)


def request_html(
    session: requests.Session,
    url: str,
    timeout: int,
    max_retries: int,
) -> tuple[str | None, str | None]:
    last_final_url: str | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = session.get(url, timeout=timeout, allow_redirects=True)
            last_final_url = response.url
            if response.status_code in {429, 500, 502, 503, 504}:
                if attempt == max_retries:
                    return None, last_final_url
                time.sleep(min(8.0, 0.5 * (2 ** (attempt - 1))))
                continue
            response.raise_for_status()
            ctype = (response.headers.get("content-type") or "").lower()
            if "text/html" not in ctype and "application/xhtml+xml" not in ctype:
                return None, last_final_url
            return response.text, last_final_url
        except Exception:
            if attempt == max_retries:
                break
            time.sleep(min(8.0, 0.5 * (2 ** (attempt - 1))))
    return None, last_final_url


def extract_candidate_links(base_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[str] = []
    seen: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip()
        text = anchor.get_text(" ", strip=True)
        if not href:
            continue
        absolute = urljoin(base_url, href)
        if not absolute.startswith(("http://", "https://")):
            continue
        if not same_host(base_url, absolute):
            continue
        if not looks_like_news_url(absolute, text):
            continue
        clean = absolute.rstrip("/")
        if clean in seen:
            continue
        seen.add(clean)
        candidates.append(clean)

    return candidates


def check_candidate_path(
    session: requests.Session,
    site_root: str,
    candidate_path: str,
    timeout: int,
    max_retries: int,
) -> str | None:
    candidate_url = urljoin(site_root, candidate_path)
    html, final_url = request_html(session, candidate_url, timeout=timeout, max_retries=max_retries)
    if not html or not final_url or not same_host(site_root, final_url):
        return None
    low = html.lower()
    if any(token in low for token in ["news", "blog", "journal", "article", "story", "update"]):
        return final_url.rstrip("/")
    return None


def detect_news_for_row(
    foundry_name: str,
    foundry_url: str,
    timeout: int,
    max_retries: int,
) -> DetectionResult:
    checked_at = now_iso()
    if not foundry_url.strip():
        return DetectionResult(foundry_name, foundry_url, "", "missing_url", "none", checked_at)

    site_root = normalize_site_root(foundry_url)
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

    homepage_html, homepage_final = request_html(session, site_root, timeout=timeout, max_retries=max_retries)
    if homepage_html and homepage_final:
        candidates = extract_candidate_links(homepage_final, homepage_html)
        if candidates:
            return DetectionResult(foundry_name, foundry_url, candidates[0], "found", "homepage_link", checked_at)

    for candidate_path in CANDIDATE_PATHS:
        candidate = check_candidate_path(
            session=session,
            site_root=site_root,
            candidate_path=candidate_path,
            timeout=timeout,
            max_retries=max_retries,
        )
        if candidate:
            return DetectionResult(foundry_name, foundry_url, candidate, "found", f"path_probe:{candidate_path}", checked_at)

    if homepage_html is None:
        return DetectionResult(foundry_name, foundry_url, "", "fetch_failed", "none", checked_at)

    return DetectionResult(foundry_name, foundry_url, "", "not_found", "none", checked_at)


def load_checkpoint(path: Path, force: bool) -> dict[str, Any]:
    if path.exists() and not force:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
    return {"created_at": now_iso(), "done": {}}


def save_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def row_key(row: dict[str, str]) -> str:
    return f"{row.get('foundry_name', '').strip()}|{row.get('foundry_url', '').strip()}"


def main() -> None:
    args = parse_args()
    input_csv = Path(args.input_csv)
    output_csv = Path(args.output_csv)
    checkpoint_path = Path(args.checkpoint)

    rows = load_rows(input_csv)
    checkpoint = load_checkpoint(checkpoint_path, force=bool(args.force))
    done = checkpoint.get("done", {})
    if not isinstance(done, dict):
        done = {}
        checkpoint["done"] = done

    pending = [row for row in rows if row_key(row) not in done]

    with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
        futures = {
            executor.submit(
                detect_news_for_row,
                row.get("foundry_name", ""),
                row.get("foundry_url", ""),
                args.timeout,
                args.max_retries,
            ): row
            for row in pending
        }
        processed = 0
        for future in as_completed(futures):
            result = future.result()
            done[row_key({"foundry_name": result.foundry_name, "foundry_url": result.foundry_url})] = {
                "news_section_url": result.news_section_url,
                "news_section_status": result.news_section_status,
                "detection_method": result.detection_method,
                "checked_at": result.checked_at,
            }
            processed += 1
            if processed % 25 == 0:
                checkpoint["updated_at"] = now_iso()
                save_checkpoint(checkpoint_path, checkpoint)

    checkpoint["updated_at"] = now_iso()
    checkpoint["completed_at"] = now_iso()
    save_checkpoint(checkpoint_path, checkpoint)

    out_rows: list[dict[str, str]] = []
    for row in rows:
        meta = done.get(row_key(row), {})
        out_rows.append(
            {
                "foundry_name": row.get("foundry_name", ""),
                "foundry_url": row.get("foundry_url", ""),
                "news_section_url": str(meta.get("news_section_url", "")),
                "news_section_status": str(meta.get("news_section_status", "")),
                "detection_method": str(meta.get("detection_method", "")),
                "checked_at": str(meta.get("checked_at", "")),
            }
        )

    write_rows(output_csv, out_rows)

    summary = {
        "input_rows": len(rows),
        "output_csv": str(output_csv),
        "checkpoint": str(checkpoint_path),
        "found": sum(1 for row in out_rows if row["news_section_status"] == "found"),
        "not_found": sum(1 for row in out_rows if row["news_section_status"] == "not_found"),
        "fetch_failed": sum(1 for row in out_rows if row["news_section_status"] == "fetch_failed"),
        "missing_url": sum(1 for row in out_rows if row["news_section_status"] == "missing_url"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
