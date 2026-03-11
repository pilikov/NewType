from __future__ import annotations


class PostgresStateAdapter:
    """Skeleton adapter for future Postgres/Neon crawl state backend."""

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn

    def load_seen_ids(self) -> dict[str, list[str]]:
        raise NotImplementedError("PostgresStateAdapter.load_seen_ids is not implemented yet")

    def save_seen_ids(self, state: dict[str, list[str]]) -> None:
        raise NotImplementedError("PostgresStateAdapter.save_seen_ids is not implemented yet")
