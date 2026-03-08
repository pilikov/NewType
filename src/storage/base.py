from __future__ import annotations

from pathlib import Path
from typing import Protocol

from src.models import FontRelease


class StorageAdapter(Protocol):
    def source_output_dir(
        self,
        source_id: str,
        period_label: str | None = None,
    ) -> Path:
        ...

    def load_releases(self, path: Path) -> list[FontRelease]:
        ...

    def write_releases(self, path: Path, releases: list[FontRelease]) -> None:
        ...

    def persist_source_results(
        self,
        source_id: str,
        all_releases: list[FontRelease],
        new_releases: list[FontRelease],
        period_label: str | None = None,
    ) -> Path:
        ...

    def merge_releases(
        self,
        existing: list[FontRelease],
        incoming: list[FontRelease],
    ) -> list[FontRelease]:
        ...
