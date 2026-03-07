from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import requests


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def dump_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def absolutize(base_url: str, maybe_relative: str | None) -> str | None:
    if not maybe_relative:
        return None
    return urljoin(base_url, maybe_relative.strip())


def sanitize_filename(url_or_name: str, fallback: str) -> str:
    raw_name = urlparse(url_or_name).path.rsplit("/", 1)[-1] if "/" in url_or_name else url_or_name
    raw_name = raw_name.strip() or fallback
    allowed = "-_.() abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    return "".join(c for c in raw_name if c in allowed).strip() or fallback


def download_file(url: str, target_path: Path, timeout: int = 20) -> bool:
    try:
        r = requests.get(url, timeout=timeout, stream=True)
        r.raise_for_status()
        ensure_dir(target_path.parent)
        with target_path.open("wb") as f:
            for chunk in r.iter_content(chunk_size=16384):
                if chunk:
                    f.write(chunk)
        return True
    except requests.RequestException:
        return False
