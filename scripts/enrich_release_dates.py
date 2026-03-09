from __future__ import annotations

import argparse
import csv
import json
import random
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

KEYWORDS = [
    "release",
    "released",
    "published",
    "launch",
    "launched",
    "new",
    "introduced",
    "available",
]

DATE_RE = re.compile(
    r"(\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b|"
    r"\b\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{4}\b|"
    r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b|"
    r"\b(?:19|20)\d{2}\b)",
    re.IGNORECASE,
)


@dataclass
class Candidate:
    date: str
    score: float
    source_type: str
    source_url: str
    snippet: str


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Enrich release dates from source pages")
    p.add_argument(
        "--input-json",
        type=str,
        default="data/catalog_snapshot/20260308T163309Z/reports/service_valid_last_10_weeks.json",
    )
    p.add_argument(
        "--output-dir",
        type=str,
        default="data/catalog_snapshot/20260308T163309Z/reports/release_date_enrichment",
    )
    p.add_argument(
        "--checkpoint",
        type=str,
        default="state/catalog_snapshot/release_date_enrichment_checkpoint.json",
    )
    p.add_argument("--max-workers", type=int, default=10)
    p.add_argument("--timeout", type=int, default=18)
    p.add_argument("--max-retries", type=int, default=4)
    p.add_argument("--max-items", type=int, default=0)
    p.add_argument("--force", action="store_true")
    return p.parse_args()


def normalize_date(value: str) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None

    raw = raw.replace("Sept ", "Sep ").replace("sept ", "sep ")
    formats = [
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d %b %Y",
        "%d %B %Y",
        "%b %d, %Y",
        "%B %d, %Y",
        "%b %d %Y",
        "%B %d %Y",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.year < 1990 or dt.year > datetime.now(timezone.utc).year + 1:
                return None
            return dt.date().isoformat()
        except Exception:
            pass

    year_match = re.search(r"\b(19|20)\d{2}\b", raw)
    if year_match:
        year = int(year_match.group(0))
        if 1990 <= year <= datetime.now(timezone.utc).year + 1:
            return f"{year:04d}-01-01"
    return None


def parse_jsonld_candidates(soup: BeautifulSoup, url: str) -> list[Candidate]:
    out: list[Candidate] = []
    allowed_types = {
        "product",
        "creativework",
        "article",
        "newsarticle",
        "blogposting",
        "webpage",
    }
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = (node.string or node.text or "").strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue

        stack = [payload]
        while stack:
            cur = stack.pop()
            if isinstance(cur, list):
                stack.extend(cur)
                continue
            if not isinstance(cur, dict):
                continue
            typ = cur.get("@type")
            type_ok = False
            if isinstance(typ, str):
                type_ok = typ.strip().lower() in allowed_types
            elif isinstance(typ, list):
                type_ok = any(isinstance(x, str) and x.strip().lower() in allowed_types for x in typ)

            for key in ["datePublished", "dateCreated", "dateModified", "uploadDate"]:
                if key in cur and cur[key]:
                    d = normalize_date(str(cur[key]))
                    if not d:
                        continue
                    score = 0.95 if key in {"datePublished", "dateCreated"} else 0.7
                    if not type_ok:
                        score -= 0.25
                    out.append(Candidate(d, score, f"jsonld:{key}", url, str(cur[key])[:180]))
            stack.extend(cur.values())
    return out


def parse_meta_candidates(soup: BeautifulSoup, url: str) -> list[Candidate]:
    out: list[Candidate] = []
    selectors = [
        ("property", "article:published_time", 0.92),
        ("property", "og:published_time", 0.9),
        ("name", "publish_date", 0.85),
        ("name", "date", 0.75),
        ("name", "dc.date", 0.8),
        ("itemprop", "datePublished", 0.9),
        ("itemprop", "dateCreated", 0.85),
        ("property", "article:modified_time", 0.6),
    ]
    for attr, name, score in selectors:
        for tag in soup.find_all("meta", attrs={attr: name}):
            val = tag.get("content")
            if not val:
                continue
            d = normalize_date(str(val))
            if not d:
                continue
            out.append(Candidate(d, score, f"meta:{name}", url, str(val)[:180]))
    return out


def parse_text_candidates(soup: BeautifulSoup, url: str) -> list[Candidate]:
    out: list[Candidate] = []
    text = soup.get_text(" ", strip=True)
    # Light size cap to avoid huge pages slowing regex.
    text = text[:300_000]
    for m in DATE_RE.finditer(text):
        raw = m.group(0)
        d = normalize_date(raw)
        if not d:
            continue
        start = max(0, m.start() - 120)
        end = min(len(text), m.end() + 120)
        snippet = text[start:end]
        low = snippet.lower()
        score = 0.55
        if any(k in low for k in KEYWORDS):
            score = 0.78
        out.append(Candidate(d, score, "text", url, snippet[:220]))
    return out


def choose_best(candidates: list[Candidate]) -> Candidate | None:
    if not candidates:
        return None
    # Keep best score, tie-break by earliest date.
    candidates = sorted(candidates, key=lambda c: (-c.score, c.date))
    best = candidates[0]

    # If we have high-confidence explicit release dates, pick earliest among them.
    high = [c for c in candidates if c.score >= 0.9]
    if high:
        high = sorted(high, key=lambda c: c.date)
        return high[0]
    return best


def is_homepage_url(url: str) -> bool:
    try:
        from urllib.parse import urlparse

        p = urlparse(url)
        path = (p.path or "").strip("/")
        return path == ""
    except Exception:
        return False


def classify_confidence(score: float) -> str:
    if score >= 0.9:
        return "high"
    if score >= 0.72:
        return "medium"
    return "low"


def request_html(
    session: requests.Session,
    url: str,
    timeout: int,
    max_retries: int,
) -> tuple[str | None, dict[str, Any]]:
    last_err: str | None = None
    for attempt in range(1, max_retries + 1):
        try:
            r = session.get(url, timeout=timeout, allow_redirects=True)
            if r.status_code in {429, 500, 502, 503, 504}:
                if attempt == max_retries:
                    return None, {"ok": False, "status": r.status_code, "error": f"HTTP {r.status_code}"}
                ra = r.headers.get("Retry-After")
                delay = float(ra) if ra and ra.isdigit() else min(10, 0.7 * (2 ** (attempt - 1))) + random.uniform(0, 0.3)
                time.sleep(delay)
                continue
            r.raise_for_status()
            ctype = (r.headers.get("Content-Type") or "").lower()
            if "text/html" not in ctype and "application/xhtml" not in ctype:
                return None, {
                    "ok": False,
                    "status": r.status_code,
                    "error": f"unsupported content-type: {ctype}",
                    "final_url": r.url,
                    "last_modified": r.headers.get("Last-Modified"),
                }
            return r.text, {
                "ok": True,
                "status": r.status_code,
                "final_url": r.url,
                "last_modified": r.headers.get("Last-Modified"),
            }
        except Exception as e:
            last_err = str(e)
            if attempt == max_retries:
                break
            time.sleep(min(10, 0.7 * (2 ** (attempt - 1))) + random.uniform(0, 0.3))

    return None, {"ok": False, "status": None, "error": last_err or "request failed"}


def process_record(
    record: dict[str, Any],
    timeout: int,
    max_retries: int,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    record_id = str(record.get("raw_typeface_id") or record.get("name") or "unknown")
    url = str(record.get("source_url") or "").strip()
    evidence: dict[str, Any] = {
        "record_id": record_id,
        "source_url": url,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "candidates": [],
    }

    if not url:
        enriched = dict(record)
        enriched["release_date_initial"] = record.get("release_date")
        enriched["release_date_source_url"] = None
        enriched["release_date_source_type"] = "missing_url"
        enriched["release_date_confidence"] = "low"
        enriched["release_date_confidence_score"] = 0.0
        enriched["release_date"] = record.get("release_date")
        return record_id, enriched, evidence

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})

    html, req_meta = request_html(session, url=url, timeout=timeout, max_retries=max_retries)
    evidence["request"] = req_meta

    candidates: list[Candidate] = []
    if html:
        soup = BeautifulSoup(html, "html.parser")
        candidates.extend(parse_jsonld_candidates(soup, url=req_meta.get("final_url") or url))
        candidates.extend(parse_meta_candidates(soup, url=req_meta.get("final_url") or url))
        candidates.extend(parse_text_candidates(soup, url=req_meta.get("final_url") or url))

    # Last-Modified header as weak fallback.
    lm = (req_meta.get("last_modified") or "").strip()
    if lm:
        d = normalize_date(lm)
        if d:
            candidates.append(Candidate(d, 0.45, "http:last-modified", req_meta.get("final_url") or url, lm))

    # Existing record date as weakest fallback.
    existing = (record.get("release_date") or "").strip()
    if existing and normalize_date(existing):
        candidates.append(Candidate(existing, 0.35, "existing", url, existing))

    # Dedup candidates by (date, source_type)
    dedup: dict[tuple[str, str], Candidate] = {}
    for c in candidates:
        if is_homepage_url(url) and c.source_type.startswith("jsonld:"):
            c = Candidate(c.date, max(0.0, c.score - 0.3), c.source_type, c.source_url, c.snippet)
        key = (c.date, c.source_type)
        if key not in dedup or dedup[key].score < c.score:
            dedup[key] = c
    candidates = list(dedup.values())

    evidence["candidates"] = [
        {
            "date": c.date,
            "score": c.score,
            "source_type": c.source_type,
            "source_url": c.source_url,
            "snippet": c.snippet,
        }
        for c in sorted(candidates, key=lambda x: (-x.score, x.date))[:120]
    ]

    best = choose_best(candidates)

    enriched = dict(record)
    enriched["release_date_initial"] = record.get("release_date")
    if best:
        enriched["release_date"] = best.date
        enriched["release_date_source_url"] = best.source_url
        enriched["release_date_source_type"] = best.source_type
        enriched["release_date_confidence_score"] = round(best.score, 3)
        enriched["release_date_confidence"] = classify_confidence(best.score)
    else:
        enriched["release_date_source_url"] = None
        enriched["release_date_source_type"] = "none"
        enriched["release_date_confidence_score"] = 0.0
        enriched["release_date_confidence"] = "low"

    enriched["release_date_candidates_count"] = len(candidates)
    return record_id, enriched, evidence


def save_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    cols = sorted({k for r in rows for k in r.keys()})
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    c: (json.dumps(r.get(c), ensure_ascii=False) if isinstance(r.get(c), (dict, list)) else r.get(c))
                    for c in cols
                }
            )


def main() -> None:
    args = parse_args()
    in_path = Path(args.input_json)
    out_dir = Path(args.output_dir)
    checkpoint_path = Path(args.checkpoint)
    evidence_dir = out_dir / "evidence"

    out_dir.mkdir(parents=True, exist_ok=True)
    evidence_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = json.loads(in_path.read_text(encoding="utf-8"))
    if args.max_items and args.max_items > 0:
        rows = rows[: args.max_items]

    if checkpoint_path.exists() and not args.force:
        cp = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    else:
        cp = {"done": {}, "created_at": datetime.now(timezone.utc).isoformat(), "input": str(in_path)}

    done: dict[str, dict[str, Any]] = cp.get("done", {}) if isinstance(cp.get("done"), dict) else {}

    pending = []
    for r in rows:
        rid = str(r.get("raw_typeface_id") or r.get("name") or "unknown")
        if rid in done:
            continue
        pending.append(r)

    processed_now = 0
    started = datetime.now(timezone.utc)

    def flush_checkpoint() -> None:
        cp["done"] = done
        cp["updated_at"] = datetime.now(timezone.utc).isoformat()
        cp["processed_now"] = processed_now
        checkpoint_path.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")

    # Streaming submission to avoid giant future queues and long stalls.
    with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as ex:
        pending_idx = 0
        in_flight: set[Any] = set()

        while pending_idx < len(pending) or in_flight:
            while pending_idx < len(pending) and len(in_flight) < max(1, args.max_workers) * 3:
                fut = ex.submit(process_record, pending[pending_idx], args.timeout, args.max_retries)
                in_flight.add(fut)
                pending_idx += 1

            if not in_flight:
                continue

            try:
                for fut in as_completed(list(in_flight), timeout=30):
                    in_flight.remove(fut)
                    rid, enriched, evidence = fut.result()
                    done[rid] = enriched
                    (evidence_dir / f"{rid}.json").write_text(
                        json.dumps(evidence, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                    processed_now += 1

                    if processed_now % 25 == 0:
                        flush_checkpoint()
                    break
            except TimeoutError:
                flush_checkpoint()
                continue

    flush_checkpoint()

    # Compose output in original order.
    by_id = done
    enriched_rows: list[dict[str, Any]] = []
    for r in rows:
        rid = str(r.get("raw_typeface_id") or r.get("name") or "unknown")
        enriched_rows.append(by_id.get(rid, r))

    out_json = out_dir / "service_valid_last_10_weeks_enriched.json"
    out_csv = out_dir / "service_valid_last_10_weeks_enriched.csv"
    summary_json = out_dir / "release_date_enrichment_summary.json"

    out_json.write_text(json.dumps(enriched_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    save_csv(out_csv, enriched_rows)

    confidence_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    changed = 0
    with_candidates = 0
    for r in enriched_rows:
        conf = str(r.get("release_date_confidence") or "low")
        confidence_counts[conf] = confidence_counts.get(conf, 0) + 1
        if r.get("release_date_candidates_count", 0) > 0:
            with_candidates += 1
        if (r.get("release_date") or "") != (r.get("release_date_initial") or ""):
            changed += 1

    finished = datetime.now(timezone.utc)
    summary = {
        "input_rows": len(rows),
        "processed_new_rows": processed_now,
        "total_rows_enriched": len(enriched_rows),
        "with_candidates": with_candidates,
        "release_date_changed": changed,
        "confidence_counts": confidence_counts,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 3),
        "files": {
            "json": str(out_json),
            "csv": str(out_csv),
            "summary": str(summary_json),
            "checkpoint": str(checkpoint_path),
            "evidence_dir": str(evidence_dir),
        },
    }

    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    cp["done"] = done
    cp["updated_at"] = datetime.now(timezone.utc).isoformat()
    cp["summary"] = summary
    checkpoint_path.write_text(json.dumps(cp, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
