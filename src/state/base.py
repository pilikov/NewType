from __future__ import annotations

from typing import Protocol


class StateAdapter(Protocol):
    def load_seen_ids(self) -> dict[str, list[str]]:
        ...

    def save_seen_ids(self, state: dict[str, list[str]]) -> None:
        ...
