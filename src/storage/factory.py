from __future__ import annotations

from pathlib import Path
from typing import Literal

from src.storage.base import StorageAdapter
from src.storage.json_adapter import JsonStorageAdapter
from src.storage.postgres_adapter import PostgresStorageAdapter

StorageBackend = Literal["json", "postgres"]


def create_storage_adapter(
    backend: StorageBackend,
    data_dir: Path,
    postgres_dsn: str | None = None,
) -> StorageAdapter:
    if backend == "json":
        return JsonStorageAdapter(data_dir=data_dir)
    if backend == "postgres":
        if not postgres_dsn:
            raise ValueError("postgres_dsn is required when backend='postgres'")
        return PostgresStorageAdapter(dsn=postgres_dsn)
    raise ValueError(f"Unsupported storage backend: {backend}")
