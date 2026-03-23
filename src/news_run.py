"""News crawl orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import requests

from src.orchestration.news_registry import build_news_crawler_registry
from src.state.news_daily_watermarks import (
    load_news_daily_watermarks,
    news_daily_start_end_dates,
    save_news_daily_watermarks,
    update_news_source_watermark,
)
from src.utils import dump_json, ensure_dir, load_json

ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = ROOT / "state"
NEWS_CONFIG_PATH = ROOT / "config" / "news_sources.json"
NEWS_DATA_DIR = ROOT / "data" / "news"
NEWS_SEEN_IDS_PATH = ROOT / "state" / "news_seen_ids.json"
NEWS_REGISTRY = build_news_crawler_registry()


def load_news_sources() -> list[dict]:
    payload = load_json(NEWS_CONFIG_PATH, default={"sources": []})
    return [s for s in payload.get("sources", []) if s.get("enabled", True)]


def load_news_seen_ids() -> dict[str, list[str]]:
    return load_json(NEWS_SEEN_IDS_PATH, default={})


def save_news_seen_ids(state: dict[str, list[str]]) -> None:
    ensure_dir(NEWS_SEEN_IDS_PATH.parent)
    dump_json(NEWS_SEEN_IDS_PATH, state)


def _apply_news_daily_overrides(
    source_cfg: dict[str, Any],
    source_id: str,
    watermarks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Inject start_date/end_date and lookback_days for daily run."""
    updated = dict(source_cfg)
    crawl = dict(updated.get("crawl") or {})
    start_date, end_date = news_daily_start_end_dates(
        watermarks, source_id, fallback_days_back=7
    )
    crawl["start_date"] = start_date.isoformat()
    crawl["end_date"] = end_date.isoformat()
    days = (end_date - start_date).days + 1
    crawl["lookback_days"] = max(7, days)
    updated["crawl"] = crawl
    return updated


def _load_existing_news(out_path: Path) -> dict[str, dict[str, Any]]:
    """Load existing all_news.json, return {news_id: item}."""
    if not out_path.exists():
        return {}
    try:
        data = load_json(out_path, default=[])
        if not isinstance(data, list):
            return {}
        return {str(item.get("news_id", "")): item for item in data if item.get("news_id")}
    except Exception:
        return {}


def _load_existing_from_date_dirs(source_dir: Path) -> dict[str, dict[str, Any]]:
    """Migrate: load items from old per-date directories into a single dict."""
    existing: dict[str, dict[str, Any]] = {}
    if not source_dir.is_dir():
        return existing
    for date_dir in sorted(source_dir.iterdir()):
        if not date_dir.is_dir():
            continue
        # Only pick up date-formatted directories (YYYY-MM-DD)
        import re
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_dir.name):
            continue
        f = date_dir / "all_news.json"
        items = _load_existing_news(f)
        existing.update(items)
    return existing


def run_news(
    source_filter: set[str] | None = None,
    timeout: int = 20,
    daily: bool = False,
) -> None:
    sources = load_news_sources()
    seen_state = load_news_seen_ids()
    watermarks = load_news_daily_watermarks(STATE_DIR) if daily else {}

    if source_filter:
        sources = [s for s in sources if s.get("id") in source_filter]

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

        for source_cfg in sources:
            source_id = source_cfg.get("id", "")
            if not source_id:
                continue

            cfg = (
                _apply_news_daily_overrides(source_cfg, source_id, watermarks)
                if daily
                else source_cfg
            )

            try:
                crawler = NEWS_REGISTRY.build(cfg)
                items = crawler.crawl(session=session, timeout=timeout)
            except Exception as e:
                print(f"[news:{source_id}] crawl failed: {e}")
                continue

            # Single accumulating file per source — never per-date
            out_dir = NEWS_DATA_DIR / source_id
            ensure_dir(out_dir)
            out_path = out_dir / "all_news.json"

            # Load accumulated history; fall back to migrating old date-dirs
            existing = _load_existing_news(out_path)
            if not existing:
                existing = _load_existing_from_date_dirs(out_dir)

            # Add new items; enrich existing items with missing fields
            new_count = 0
            updated_count = 0
            for item in items:
                if item.news_id not in existing:
                    existing[item.news_id] = item.to_dict()
                    new_count += 1
                else:
                    # Back-fill image_url if the old record lacks it
                    old = existing[item.news_id]
                    new_dict = item.to_dict()
                    if not old.get("image_url") and new_dict.get("image_url"):
                        old["image_url"] = new_dict["image_url"]
                        updated_count += 1

            # seen_ids mirrors the full accumulated set
            seen_state[source_id] = sorted(existing.keys())

            to_save = list(existing.values())
            dump_json(out_path, to_save)
            enriched = f" enriched={updated_count}" if updated_count else ""
            print(f"[news:{source_id}] total={len(to_save)} new={new_count}{enriched} output={out_dir}")

            if daily:
                update_news_source_watermark(watermarks, source_id)

    if daily and watermarks:
        save_news_daily_watermarks(STATE_DIR, watermarks)
    save_news_seen_ids(seen_state)
