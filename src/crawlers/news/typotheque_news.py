"""Typotheque blog news crawler. Uses RSS feed."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from src.crawlers.news.rss_mixin import parse_rss_feed
from src.models import FontNewsItem


def _parse_ymd(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.strptime(str(s).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


class TypothequeNewsCrawler:
    def __init__(self, source_config: dict[str, Any]) -> None:
        self.source_config = source_config

    def crawl(self, session, timeout: int = 20) -> list[FontNewsItem]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        crawl_cfg = self.source_config.get("crawl", {})
        rss_url = str(crawl_cfg.get("rss_url", "https://www.typotheque.com/blog/feed"))
        base_url = str(self.source_config.get("base_url", "https://www.typotheque.com"))
        lookback_days = int(crawl_cfg.get("lookback_days", 1))
        start_date = _parse_ymd(crawl_cfg.get("start_date"))
        end_date = _parse_ymd(crawl_cfg.get("end_date"))

        return parse_rss_feed(
            session=session,
            timeout=timeout,
            rss_url=rss_url,
            base_url=base_url,
            source_id=source_id,
            source_name=source_name,
            lookback_days=lookback_days,
            start_date=start_date,
            end_date=end_date,
        )
