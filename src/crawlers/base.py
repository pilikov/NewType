from __future__ import annotations

from typing import Any, Protocol

import requests

from src.models import FontRelease


class Crawler(Protocol):
    source_config: dict[str, Any]

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontRelease]:
        ...

    def set_release_callback(self, callback: Any) -> None:
        ...
