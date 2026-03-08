from __future__ import annotations

import argparse
import mimetypes
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.domain.run_models import RunContext, RunSummary, SourceRunSummary
from src.models import FontRelease
from src.orchestration.registry import build_default_crawler_registry
from src.state.json_adapter import JsonStateAdapter
from src.storage.json_adapter import JsonStorageAdapter
from src.utils import download_file, dump_json, ensure_dir, load_json, sanitize_filename

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "sources.json"
DATA_DIR = ROOT / "data"
COVERAGE_PATH = ROOT / "state" / "data_coverage.json"
FAVICON_CACHE_PATH = ROOT / "state" / "source_favicons.json"
FAVICON_DATA_DIR = DATA_DIR / "_meta" / "favicons"
RUNS_DIR = ROOT / "state" / "runs"
CRAWLER_REGISTRY = build_default_crawler_registry()
JSON_STORAGE = JsonStorageAdapter(data_dir=DATA_DIR)
JSON_STATE = JsonStateAdapter(seen_ids_path=ROOT / "state" / "seen_ids.json")


def load_sources() -> list[dict]:
    payload = load_json(CONFIG_PATH, default={"sources": []})
    return [s for s in payload.get("sources", []) if s.get("enabled", True)]


def load_seen_ids() -> dict[str, list[str]]:
    return JSON_STATE.load_seen_ids()


def save_seen_ids(state: dict[str, list[str]]) -> None:
    JSON_STATE.save_seen_ids(state)


def build_crawler(source_cfg: dict):
    return CRAWLER_REGISTRY.build(source_cfg)


def persist_source_results(
    source_id: str,
    all_releases: list[FontRelease],
    new_releases: list[FontRelease],
    period_label: str | None = None,
) -> Path:
    return JSON_STORAGE.persist_source_results(
        source_id=source_id,
        all_releases=all_releases,
        new_releases=new_releases,
        period_label=period_label,
    )


class IncrementalSourceWriter:
    def __init__(
        self,
        source_id: str,
        seen_ids: set[str],
        period_label: str | None = None,
        flush_every: int = 25,
    ) -> None:
        self.source_id = source_id
        self.seen_ids = seen_ids
        self.period_label = period_label
        self.flush_every = max(1, flush_every)
        self.output_dir = JSON_STORAGE.source_output_dir(source_id=source_id, period_label=period_label)
        self.all_releases: list[FontRelease] = JSON_STORAGE.load_releases(self.output_dir / "all_releases.json")
        self.new_releases: list[FontRelease] = JSON_STORAGE.load_releases(self.output_dir / "new_releases.json")
        self.current_ids: set[str] = {r.release_id for r in self.all_releases}
        self._counter = 0
        ensure_dir(self.output_dir)

    def on_release(self, release: FontRelease) -> None:
        rid = release.release_id
        if rid in self.current_ids:
            return
        self.current_ids.add(rid)
        self.all_releases.append(release)
        if rid not in self.seen_ids:
            self.new_releases.append(release)
        self._counter += 1
        if self._counter % self.flush_every == 0:
            self.flush()

    def flush(self) -> None:
        JSON_STORAGE.write_releases(self.output_dir / "all_releases.json", self.all_releases)
        JSON_STORAGE.write_releases(self.output_dir / "new_releases.json", self.new_releases)

    def finalize(self, fallback_releases: list[FontRelease]) -> tuple[list[FontRelease], list[FontRelease], Path]:
        if not self.all_releases and fallback_releases:
            for release in fallback_releases:
                self.on_release(release)
        self.flush()
        return self.all_releases, self.new_releases, self.output_dir


def maybe_download_assets(source_cfg: dict, output_dir: Path, releases: list[FontRelease]) -> None:
    assets_cfg = source_cfg.get("assets", {})
    assets_dir = output_dir / "assets"
    max_downloads_per_run = int(assets_cfg.get("max_downloads_per_run", 25))
    processed = 0

    for release in releases:
        if processed >= max_downloads_per_run:
            break
        release_assets: dict[str, str] = {}
        per_release_dir = assets_dir / release.release_id
        ensure_dir(per_release_dir)

        if assets_cfg.get("download_image") and release.image_url:
            image_name = sanitize_filename(release.image_url, "preview.jpg")
            image_path = per_release_dir / image_name
            if download_file(release.image_url, image_path):
                release_assets["image"] = str(image_path.relative_to(output_dir))

        if assets_cfg.get("download_woff") and release.woff_url:
            woff_name = sanitize_filename(release.woff_url, "font.woff")
            woff_path = per_release_dir / woff_name
            if download_file(release.woff_url, woff_path):
                release_assets["woff"] = str(woff_path.relative_to(output_dir))

        if assets_cfg.get("download_specimen_pdf") and release.specimen_pdf_url:
            pdf_name = sanitize_filename(release.specimen_pdf_url, "specimen.pdf")
            pdf_path = per_release_dir / pdf_name
            if download_file(release.specimen_pdf_url, pdf_path):
                release_assets["specimen_pdf"] = str(pdf_path.relative_to(output_dir))

        if release_assets:
            dump_json(per_release_dir / "downloaded_assets.json", release_assets)
            processed += 1


def run(
    source_filter: set[str] | None = None,
    timeout: int = 20,
    myfonts_debut_date: str | None = None,
    myfonts_start_date: str | None = None,
    myfonts_end_date: str | None = None,
    history_weeks: int | None = None,
    history_end_date: str | None = None,
) -> None:
    run_ctx = RunContext(
        source_filter=sorted(source_filter) if source_filter else [],
        timeout_seconds=timeout,
    )
    source_results: list[SourceRunSummary] = []
    sources = load_sources()
    seen_state = load_seen_ids()
    history_start, history_end = _resolve_history_range(history_weeks, history_end_date)
    period_label = f"{history_start}_{history_end}" if history_start and history_end else None

    with requests.Session() as session:
        session.headers.update(
            {
                # Browser-like UA gives fuller MyFonts HTML (debut/promo blocks), while still using static requests.
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

        for source_cfg in sources:
            source_id = source_cfg["id"]
            if source_filter and source_id not in source_filter:
                continue
            source_started = datetime.utcnow()

            if source_id == "myfonts" and (myfonts_debut_date or myfonts_start_date or myfonts_end_date):
                source_cfg = dict(source_cfg)
                source_cfg["crawl"] = dict(source_cfg.get("crawl", {}))
                source_cfg["crawl"]["max_pages"] = max(int(source_cfg["crawl"].get("max_pages", 1)), 40)
                if myfonts_debut_date:
                    source_cfg["crawl"]["start_date"] = myfonts_debut_date
                    source_cfg["crawl"]["end_date"] = myfonts_debut_date
                    source_cfg["crawl"]["target_debut_date"] = myfonts_debut_date
                if myfonts_start_date:
                    source_cfg["crawl"]["start_date"] = myfonts_start_date
                if myfonts_end_date:
                    source_cfg["crawl"]["end_date"] = myfonts_end_date
            if history_start and history_end:
                source_cfg = dict(source_cfg)
                source_cfg["crawl"] = dict(source_cfg.get("crawl", {}))
                if source_id == "myfonts":
                    source_cfg["crawl"]["start_date"] = history_start
                    source_cfg["crawl"]["end_date"] = history_end
                if source_id == "type_today":
                    source_cfg["crawl"]["start_date"] = history_start
                    source_cfg["crawl"]["end_date"] = history_end
                if source_id == "futurefonts":
                    source_cfg["crawl"]["start_date"] = history_start
                    source_cfg["crawl"]["end_date"] = history_end
                    start_dt = datetime.strptime(history_start, "%Y-%m-%d").date()
                    delta_days = (date.today() - start_dt).days + 7
                    source_cfg["crawl"]["lookback_days"] = max(
                        int(source_cfg["crawl"].get("lookback_days", 30)),
                        delta_days,
                    )
                if source_id == "typenetwork":
                    source_cfg["crawl"]["start_date"] = history_start
                    source_cfg["crawl"]["end_date"] = history_end

            crawler = build_crawler(source_cfg)
            seen_ids = set(seen_state.get(source_id, []))
            incremental_writer: IncrementalSourceWriter | None = None
            flush_every = int(source_cfg.get("crawl", {}).get("incremental_flush_every", 25))
            if hasattr(crawler, "set_release_callback"):
                incremental_writer = IncrementalSourceWriter(
                    source_id=source_id,
                    seen_ids=seen_ids,
                    period_label=period_label,
                    flush_every=flush_every,
                )
                crawler.set_release_callback(incremental_writer.on_release)

            try:
                releases = crawler.crawl(session=session, timeout=timeout)
            except Exception as e:
                print(f"[{source_id}] crawl failed: {e}")
                source_results.append(
                    SourceRunSummary(
                        source_id=source_id,
                        status="failed",
                        error=str(e),
                        duration_seconds=round((datetime.utcnow() - source_started).total_seconds(), 3),
                    )
                )
                continue

            if incremental_writer:
                releases, new_releases, output_dir = incremental_writer.finalize(releases)
            else:
                new_releases = [r for r in releases if r.release_id not in seen_ids]
                output_dir = persist_source_results(
                    source_id=source_id,
                    all_releases=releases,
                    new_releases=new_releases,
                    period_label=period_label,
                )
            assets_cfg = source_cfg.get("assets", {})
            asset_source_releases = (
                releases if assets_cfg.get("download_for_all_releases") else new_releases
            )
            maybe_download_assets(source_cfg, output_dir, asset_source_releases)

            seen_ids.update(r.release_id for r in releases)
            seen_state[source_id] = sorted(seen_ids)

            print(
                f"[{source_id}] total={len(releases)} new={len(new_releases)} output={output_dir}"
            )
            source_results.append(
                SourceRunSummary(
                    source_id=source_id,
                    status="success",
                    total_releases=len(releases),
                    new_releases=len(new_releases),
                    duration_seconds=round((datetime.utcnow() - source_started).total_seconds(), 3),
                    output_dir=str(output_dir),
                )
            )

    save_seen_ids(seen_state)
    write_data_coverage(sources)
    run_summary = RunSummary(
        run_id=run_ctx.run_id,
        started_at=run_ctx.started_at,
        finished_at=datetime.utcnow().isoformat() + "Z",
        sources=source_results,
    )
    persist_run_summary(run_ctx=run_ctx, summary=run_summary)


def persist_run_summary(run_ctx: RunContext, summary: RunSummary) -> Path:
    ensure_dir(RUNS_DIR)
    path = RUNS_DIR / f"{summary.run_id}.json"
    dump_json(
        path,
        {
            "context": run_ctx.to_dict(),
            "summary": summary.to_dict(),
        },
    )
    return path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily crawler for new font releases")
    parser.add_argument(
        "--sources",
        type=str,
        default="",
        help="Comma-separated source ids (e.g. myfonts,type_today,futurefonts)",
    )
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument(
        "--myfonts-debut-date",
        type=str,
        default="",
        help="Optional YYYY-MM-DD filter for MyFonts debut date",
    )
    parser.add_argument(
        "--myfonts-start-date",
        type=str,
        default="",
        help="Optional YYYY-MM-DD range start for MyFonts debut date",
    )
    parser.add_argument(
        "--myfonts-end-date",
        type=str,
        default="",
        help="Optional YYYY-MM-DD range end for MyFonts debut date",
    )
    parser.add_argument(
        "--history-weeks",
        type=int,
        default=0,
        help="Backfill last N weeks for sources that support date filtering",
    )
    parser.add_argument(
        "--history-end-date",
        type=str,
        default="",
        help="Optional YYYY-MM-DD end date for --history-weeks (defaults to today)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_filter = {s.strip() for s in args.sources.split(",") if s.strip()} or None
    run(
        source_filter=source_filter,
        timeout=args.timeout,
        myfonts_debut_date=args.myfonts_debut_date.strip() or None,
        myfonts_start_date=args.myfonts_start_date.strip() or None,
        myfonts_end_date=args.myfonts_end_date.strip() or None,
        history_weeks=args.history_weeks if args.history_weeks > 0 else None,
        history_end_date=args.history_end_date.strip() or None,
    )


def _resolve_history_range(
    history_weeks: int | None,
    history_end_date: str | None,
) -> tuple[str | None, str | None]:
    if not history_weeks or history_weeks <= 0:
        return None, None
    end_day = _parse_ymd(history_end_date) or date.today()
    start_day = end_day - timedelta(days=history_weeks * 7 - 1)
    return start_day.isoformat(), end_day.isoformat()


def _parse_ymd(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_release_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if len(raw) >= 10:
        raw = raw[:10]
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _week_bounds(day: date) -> tuple[date, date]:
    start = day - timedelta(days=day.weekday())
    end = start + timedelta(days=6)
    return start, end


def write_data_coverage(sources: list[dict] | None = None) -> None:
    with requests.Session() as session:
        session.headers.update(
            {
                "User-Agent": "TypeReleaseCrawler/0.1 (+https://local.dev)",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        source_meta = _build_source_meta_map(sources or [], session=session)
    summary: dict[str, dict] = {}

    for source_dir in sorted(DATA_DIR.iterdir()) if DATA_DIR.exists() else []:
        if not source_dir.is_dir():
            continue
        if source_dir.name.startswith("_"):
            continue
        source_id = source_dir.name
        days: list[date] = []
        weeks: dict[str, dict[str, str]] = {}

        for json_path in source_dir.rglob("all_releases.json"):
            releases = load_json(json_path, default=[])
            if not isinstance(releases, list):
                continue
            for rel in releases:
                if not isinstance(rel, dict):
                    continue
                rel_day = _parse_release_date(rel.get("release_date"))
                if not rel_day:
                    continue
                days.append(rel_day)
                week_start, week_end = _week_bounds(rel_day)
                key = week_start.isoformat()
                weeks[key] = {
                    "week_start": week_start.isoformat(),
                    "week_end": week_end.isoformat(),
                    "label": f"{week_start.isoformat()}..{week_end.isoformat()}",
                }

        if not days:
            summary[source_id] = {
                "source_id": source_id,
                "meta": source_meta.get(source_id, {}),
                "has_data": False,
                "min_date": None,
                "max_date": None,
                "weeks": [],
            }
            continue

        summary[source_id] = {
            "source_id": source_id,
            "meta": source_meta.get(source_id, {}),
            "has_data": True,
            "min_date": min(days).isoformat(),
            "max_date": max(days).isoformat(),
            "weeks": [weeks[k] for k in sorted(weeks.keys())],
        }

    for source_id, meta in source_meta.items():
        if source_id in summary:
            continue
        summary[source_id] = {
            "source_id": source_id,
            "meta": meta,
            "has_data": False,
            "min_date": None,
            "max_date": None,
            "weeks": [],
        }

    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "sources": summary,
    }
    dump_json(COVERAGE_PATH, payload)


def _build_source_meta_map(sources: list[dict], session: requests.Session | None = None) -> dict[str, dict]:
    meta_map: dict[str, dict] = {}
    cache = load_json(FAVICON_CACHE_PATH, default={})
    cache_updated = False

    use_session = session or requests.Session()
    if session is None:
        use_session.headers.update(
            {
                "User-Agent": "TypeReleaseCrawler/0.1 (+https://local.dev)",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )

    for src in sources:
        source_id = src.get("id")
        if not source_id:
            continue
        base_url = (src.get("base_url") or "").rstrip("/")
        meta_cfg = src.get("meta", {}) if isinstance(src.get("meta"), dict) else {}
        configured_favicon = (meta_cfg.get("favicon_url") or "").strip()
        resolved_meta = _resolve_source_favicon(
            source_id=source_id,
            base_url=base_url,
            configured_favicon=configured_favicon,
            session=use_session,
            cache=cache,
        )
        if resolved_meta.get("_updated_cache"):
            cache_updated = True

        favicon_url = resolved_meta.get("favicon_url") or configured_favicon or (f"{base_url}/favicon.ico" if base_url else "")
        meta_map[source_id] = {
            "name": src.get("name") or source_id,
            "base_url": base_url or None,
            "favicon_url": favicon_url or None,
            "favicon_local_path": resolved_meta.get("favicon_local_path"),
            "favicon_resolved_from": resolved_meta.get("favicon_resolved_from"),
        }

    if cache_updated:
        dump_json(FAVICON_CACHE_PATH, cache)

    if session is None:
        use_session.close()
    return meta_map


def _resolve_source_favicon(
    source_id: str,
    base_url: str,
    configured_favicon: str,
    session: requests.Session,
    cache: dict,
) -> dict[str, str | bool | None]:
    cached = cache.get(source_id, {}) if isinstance(cache.get(source_id), dict) else {}
    cached_local = cached.get("favicon_local_path")
    if isinstance(cached_local, str) and cached_local:
        if (DATA_DIR / cached_local).exists():
            return {
                "favicon_url": cached.get("favicon_url") if isinstance(cached.get("favicon_url"), str) else configured_favicon or None,
                "favicon_local_path": cached_local,
                "favicon_resolved_from": cached.get("favicon_resolved_from"),
                "_updated_cache": False,
            }

    candidates: list[str] = []
    if configured_favicon:
        candidates.append(configured_favicon)
    if base_url:
        candidates.append(urljoin(base_url + "/", "favicon.ico"))
        discovered = _discover_favicon_candidates(session, base_url)
        candidates.extend(discovered)
    candidates = _unique_nonempty(candidates)

    for candidate in candidates:
        downloaded = _download_favicon(session, candidate)
        if not downloaded:
            continue
        body, content_type = downloaded
        local_rel = _store_favicon_asset(source_id=source_id, url=candidate, body=body, content_type=content_type)
        if not local_rel:
            continue
        cache[source_id] = {
            "favicon_url": candidate,
            "favicon_local_path": local_rel,
            "favicon_resolved_from": "configured" if candidate == configured_favicon else "discovered",
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
        return {
            "favicon_url": candidate,
            "favicon_local_path": local_rel,
            "favicon_resolved_from": cache[source_id]["favicon_resolved_from"],
            "_updated_cache": True,
        }

    return {
        "favicon_url": configured_favicon or (cached.get("favicon_url") if isinstance(cached.get("favicon_url"), str) else None),
        "favicon_local_path": None,
        "favicon_resolved_from": None,
        "_updated_cache": False,
    }


def _discover_favicon_candidates(session: requests.Session, base_url: str) -> list[str]:
    try:
        response = session.get(base_url, timeout=12)
        response.raise_for_status()
    except requests.RequestException:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    found: list[str] = []

    for link in soup.select("link[rel][href]"):
        rel = " ".join(link.get("rel") or []).lower()
        if "icon" not in rel and "apple-touch-icon" not in rel:
            continue
        href = (link.get("href") or "").strip()
        if not href:
            continue
        found.append(urljoin(base_url, href))

    manifest_link = soup.select_one("link[rel='manifest'][href]")
    if manifest_link and manifest_link.get("href"):
        manifest_url = urljoin(base_url, manifest_link.get("href"))
        found.extend(_discover_manifest_icons(session, manifest_url))

    return _unique_nonempty(found)


def _discover_manifest_icons(session: requests.Session, manifest_url: str) -> list[str]:
    try:
        response = session.get(manifest_url, timeout=12)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    icons = payload.get("icons", []) if isinstance(payload, dict) else []
    out: list[str] = []
    for icon in icons:
        if not isinstance(icon, dict):
            continue
        src = (icon.get("src") or "").strip()
        if not src:
            continue
        out.append(urljoin(manifest_url, src))
    return _unique_nonempty(out)


def _download_favicon(session: requests.Session, url: str) -> tuple[bytes, str] | None:
    if not (url.startswith("http://") or url.startswith("https://")):
        return None

    try:
        response = session.get(url, timeout=12)
        if response.status_code != 200:
            return None
        body = response.content
        if not body or len(body) > 1_000_000:
            return None
        content_type = (response.headers.get("content-type") or "").split(";")[0].strip().lower()
        if content_type.startswith("image/") or url.lower().endswith((".ico", ".png", ".svg", ".webp", ".jpg", ".jpeg")):
            return body, content_type
    except requests.RequestException:
        return None
    return None


def _store_favicon_asset(source_id: str, url: str, body: bytes, content_type: str) -> str | None:
    ensure_dir(FAVICON_DATA_DIR)
    ext = _guess_favicon_extension(url, content_type)
    output = FAVICON_DATA_DIR / f"{source_id}{ext}"
    try:
        output.write_bytes(body)
    except Exception:
        return None
    return str(output.relative_to(DATA_DIR).as_posix())


def _guess_favicon_extension(url: str, content_type: str) -> str:
    from_ct = mimetypes.guess_extension(content_type) if content_type else None
    if from_ct in {".ico", ".png", ".svg", ".webp", ".jpg", ".jpeg"}:
        return from_ct
    path_ext = Path(urlparse(url).path).suffix.lower()
    if path_ext in {".ico", ".png", ".svg", ".webp", ".jpg", ".jpeg"}:
        return path_ext
    return ".ico"


def _unique_nonempty(values: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = (value or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


if __name__ == "__main__":
    main()
