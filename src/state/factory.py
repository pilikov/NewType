from __future__ import annotations

from pathlib import Path
from typing import Literal

from src.state.base import StateAdapter
from src.state.json_adapter import JsonStateAdapter
from src.state.postgres_adapter import PostgresStateAdapter

StateBackend = Literal["json", "postgres"]


def create_state_adapter(
    backend: StateBackend,
    seen_ids_path: Path,
    postgres_dsn: str | None = None,
) -> StateAdapter:
    if backend == "json":
        return JsonStateAdapter(seen_ids_path=seen_ids_path)
    if backend == "postgres":
        if not postgres_dsn:
            raise ValueError("postgres_dsn is required when backend='postgres'")
        return PostgresStateAdapter(dsn=postgres_dsn)
    raise ValueError(f"Unsupported state backend: {backend}")
