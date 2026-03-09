from __future__ import annotations

from pathlib import Path

from src.models import FontRelease


class PostgresStorageAdapter:
    """Skeleton adapter for future Postgres/Neon storage backend."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def source_output_dir(
        self,
        source_id: str,
        period_label: str | None = None,
    ) -> Path:
        raise NotImplementedError("PostgresStorageAdapter.source_output_dir is not implemented yet")

    def load_releases(self, path: Path) -> list[FontRelease]:
        raise NotImplementedError("PostgresStorageAdapter.load_releases is not implemented yet")

    def write_releases(self, path: Path, releases: list[FontRelease]) -> None:
        raise NotImplementedError("PostgresStorageAdapter.write_releases is not implemented yet")

    def merge_releases(
        self,
        existing: list[FontRelease],
        incoming: list[FontRelease],
    ) -> list[FontRelease]:
        raise NotImplementedError("PostgresStorageAdapter.merge_releases is not implemented yet")

    def persist_source_results(
        self,
        source_id: str,
        all_releases: list[FontRelease],
        new_releases: list[FontRelease],
        period_label: str | None = None,
    ) -> Path:
        raise NotImplementedError("PostgresStorageAdapter.persist_source_results is not implemented yet")
