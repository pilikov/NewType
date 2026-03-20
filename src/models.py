from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any


@dataclass
class FontRelease:
    source_id: str
    source_name: str
    source_url: str | None
    name: str
    styles: list[str] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)
    script_status: str | None = None
    release_date: str | None = None
    image_url: str | None = None
    woff_url: str | None = None
    specimen_pdf_url: str | None = None
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def release_id(self) -> str:
        release_identity = str(self.raw.get("release_identity", "")).strip().lower()
        stable_ref = release_identity or (self.source_url or "").strip().lower() or (self.name or "").strip().lower()
        material = "|".join(
            [
                self.source_id,
                stable_ref,
            ]
        )
        return sha256(material.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["release_id"] = self.release_id
        return payload


@dataclass
class FontNewsItem:
    source_id: str
    source_name: str
    title: str
    url: str
    published_at: str | None = None
    image_url: str | None = None
    discovered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def news_id(self) -> str:
        material = "|".join([self.source_id, self.url.strip().lower()])
        return sha256(material.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["news_id"] = self.news_id
        return payload
