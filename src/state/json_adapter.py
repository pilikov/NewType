from __future__ import annotations

from pathlib import Path

from src.utils import dump_json, load_json


class JsonStateAdapter:
    def __init__(self, seen_ids_path: Path) -> None:
        self.seen_ids_path = seen_ids_path

    def load_seen_ids(self) -> dict[str, list[str]]:
        return load_json(self.seen_ids_path, default={})

    def save_seen_ids(self, state: dict[str, list[str]]) -> None:
        dump_json(self.seen_ids_path, state)
