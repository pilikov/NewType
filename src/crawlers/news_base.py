"""Base protocol for news crawlers."""

from __future__ import annotations

from typing import Any, Protocol

import requests

from src.models import FontNewsItem


class NewsCrawler(Protocol):
    """Protocol for news crawlers. Each source has its own implementation."""

    source_config: dict[str, Any]

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontNewsItem]:
        """Fetch news items. Daily-only: only items from today (or recent window)."""
        ...
