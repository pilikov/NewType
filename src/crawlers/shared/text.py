from __future__ import annotations

import re


def normalize_spaces(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(normalized)
    return out
