from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunContext:
    run_id: str = field(default_factory=lambda: uuid4().hex[:12])
    started_at: str = field(default_factory=_utc_now_iso)
    source_filter: list[str] = field(default_factory=list)
    timeout_seconds: int = 20

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SourceRunSummary:
    source_id: str
    status: str
    total_releases: int = 0
    new_releases: int = 0
    duration_seconds: float | None = None
    output_dir: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RunSummary:
    run_id: str
    started_at: str
    finished_at: str
    sources: list[SourceRunSummary] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sources"] = [item.to_dict() for item in self.sources]
        return payload
