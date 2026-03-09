#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def fmt_eta(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "n/a"
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"


@dataclass
class Config:
    timeout: int
    max_retries: int
    base_delay_seconds: float
    max_delay_seconds: float
    request_delay_seconds: float


class FutureFontsClient:
    def __init__(self, session: requests.Session, cfg: Config) -> None:
        self.session = session
        self.cfg = cfg

    def _get_json(self, url: str) -> dict[str, Any] | None:
        for attempt in range(self.cfg.max_retries + 1):
            try:
                resp = self.session.get(url, timeout=self.cfg.timeout)
                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        wait_s = float(retry_after)
                    else:
                        wait_s = min(
                            self.cfg.max_delay_seconds,
                            self.cfg.base_delay_seconds * (2**attempt),
                        )
                        wait_s += random.uniform(0.0, 0.7)
                    print(f"[429] {url} | attempt={attempt + 1}/{self.cfg.max_retries + 1} | sleep={wait_s:.1f}s")
                    time.sleep(wait_s)
                    continue

                if 500 <= resp.status_code < 600:
                    wait_s = min(
                        self.cfg.max_delay_seconds,
                        self.cfg.base_delay_seconds * (2**attempt),
                    )
                    wait_s += random.uniform(0.0, 0.7)
                    print(f"[{resp.status_code}] {url} | attempt={attempt + 1}/{self.cfg.max_retries + 1} | sleep={wait_s:.1f}s")
                    time.sleep(wait_s)
                    continue

                resp.raise_for_status()
                payload = resp.json()
                return payload if isinstance(payload, dict) else None
            except (requests.RequestException, ValueError) as exc:
                if attempt >= self.cfg.max_retries:
                    print(f"[error] {url} | exhausted retries: {exc}")
                    return None
                wait_s = min(
                    self.cfg.max_delay_seconds,
                    self.cfg.base_delay_seconds * (2**attempt),
                )
                wait_s += random.uniform(0.0, 0.7)
                print(f"[retry] {url} | attempt={attempt + 1}/{self.cfg.max_retries + 1} | sleep={wait_s:.1f}s | err={exc}")
                time.sleep(wait_s)
        return None

    def fetch_typeface_id_from_version(self, version_id: int) -> int | None:
        url = f"https://www.futurefonts.com/api/v1/typeface_versions/{version_id}"
        payload = self._get_json(url)
        if not isinstance(payload, dict):
            return None
        version_payload = payload.get("typeface_version")
        if not isinstance(version_payload, dict):
            return None
        typeface_id = version_payload.get("typeface_id")
        if not isinstance(typeface_id, int):
            return None
        if self.cfg.request_delay_seconds > 0:
            time.sleep(self.cfg.request_delay_seconds)
        return typeface_id

    def fetch_scripts_from_typeface(self, typeface_id: int) -> list[str]:
        url = f"https://www.futurefonts.com/api/v1/typefaces/{typeface_id}"
        payload = self._get_json(url)
        if not isinstance(payload, dict):
            return []
        typeface_payload = payload.get("typeface")
        if not isinstance(typeface_payload, dict):
            return []
        language_value = typeface_payload.get("language")
        if not isinstance(language_value, str):
            return []
        out: list[str] = []
        seen: set[str] = set()
        for token in language_value.split(","):
            script = token.strip()
            if not script:
                continue
            key = script.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(script)
        if self.cfg.request_delay_seconds > 0:
            time.sleep(self.cfg.request_delay_seconds)
        return out


def needs_enrichment(item: dict[str, Any]) -> bool:
    if item.get("source_id") != "futurefonts":
        return False
    scripts = item.get("scripts")
    if isinstance(scripts, list) and len(scripts) > 0:
        return False
    raw = item.get("raw")
    if not isinstance(raw, dict):
        return False
    trackable_id = raw.get("trackable_id")
    trackable_type = raw.get("trackable_type")
    if not isinstance(trackable_id, int):
        return False
    if trackable_type not in {"Typeface", "TypefaceVersion"}:
        return False
    return True


def enrich_record(
    item: dict[str, Any],
    api: FutureFontsClient,
    typeface_scripts_cache: dict[int, list[str]],
    version_to_typeface_cache: dict[int, int | None],
) -> tuple[bool, str]:
    raw = item.get("raw")
    if not isinstance(raw, dict):
        return False, "raw-missing"

    trackable_id = raw.get("trackable_id")
    trackable_type = raw.get("trackable_type")
    if not isinstance(trackable_id, int):
        return False, "trackable-id-missing"

    typeface_id: int | None = None
    if trackable_type == "Typeface":
        typeface_id = trackable_id
    elif trackable_type == "TypefaceVersion":
        if trackable_id in version_to_typeface_cache:
            typeface_id = version_to_typeface_cache[trackable_id]
        else:
            typeface_id = api.fetch_typeface_id_from_version(trackable_id)
            version_to_typeface_cache[trackable_id] = typeface_id
    else:
        return False, "trackable-type-unsupported"

    if typeface_id is None:
        return False, "typeface-id-missing"

    if typeface_id in typeface_scripts_cache:
        scripts = typeface_scripts_cache[typeface_id]
    else:
        scripts = api.fetch_scripts_from_typeface(typeface_id)
        typeface_scripts_cache[typeface_id] = scripts

    if not scripts:
        raw["resolved_typeface_id"] = typeface_id
        raw["typeface_language"] = None
        item["raw"] = raw
        return False, "scripts-empty"

    item["scripts"] = scripts
    raw["resolved_typeface_id"] = typeface_id
    raw["typeface_language"] = ",".join(scripts)
    item["raw"] = raw
    return True, "ok"


def main() -> None:
    parser = argparse.ArgumentParser(description="Incremental scripts enrichment for FutureFonts releases")
    parser.add_argument(
        "--input",
        default="data/futurefonts/periods/1926-07-13_2026-03-09/all_releases.json",
        help="Path to all_releases.json",
    )
    parser.add_argument(
        "--state",
        default="state/futurefonts_scripts_enrichment_state.json",
        help="Checkpoint state file path",
    )
    parser.add_argument("--timeout", type=int, default=25)
    parser.add_argument("--max-retries", type=int, default=14)
    parser.add_argument("--base-delay-seconds", type=float, default=2.0)
    parser.add_argument("--max-delay-seconds", type=float, default=90.0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.8)
    parser.add_argument("--save-every", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0, help="Optional max records to process in this run")
    args = parser.parse_args()

    input_path = Path(args.input)
    state_path = Path(args.state)
    if not input_path.exists():
        raise SystemExit(f"Input file not found: {input_path}")

    records = read_json(input_path, default=[])
    if not isinstance(records, list):
        raise SystemExit(f"Input file does not contain list: {input_path}")

    if not (input_path.parent / "all_releases.backup_before_scripts_enrichment.json").exists():
        backup_path = input_path.parent / "all_releases.backup_before_scripts_enrichment.json"
        shutil.copy2(input_path, backup_path)
        print(f"[backup] {backup_path}")

    state = read_json(
        state_path,
        default={
            "started_at": utc_now(),
            "updated_at": None,
            "processed_ids": [],
            "version_to_typeface": {},
            "typeface_scripts": {},
            "stats": {},
        },
    )
    processed_ids = set(state.get("processed_ids") or [])
    version_to_typeface_cache = {
        int(k): (int(v) if isinstance(v, int) else None)
        for k, v in (state.get("version_to_typeface") or {}).items()
        if str(k).isdigit()
    }
    typeface_scripts_cache = {
        int(k): ([str(x) for x in v] if isinstance(v, list) else [])
        for k, v in (state.get("typeface_scripts") or {}).items()
        if str(k).isdigit()
    }

    candidates: list[dict[str, Any]] = []
    for item in records:
        rid = item.get("release_id")
        if not isinstance(rid, str) or not rid:
            continue
        if rid in processed_ids:
            continue
        if not needs_enrichment(item):
            continue
        candidates.append(item)

    if args.limit and args.limit > 0:
        candidates = candidates[: args.limit]

    total = len(candidates)
    print(f"[start] candidates={total} | file={input_path}")
    if total == 0:
        print("[done] nothing to enrich")
        return

    cfg = Config(
        timeout=args.timeout,
        max_retries=args.max_retries,
        base_delay_seconds=args.base_delay_seconds,
        max_delay_seconds=args.max_delay_seconds,
        request_delay_seconds=args.request_delay_seconds,
    )

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
        }
    )
    api = FutureFontsClient(session=session, cfg=cfg)

    started = time.monotonic()
    processed = 0
    enriched = 0
    skipped = 0
    failed = 0
    dirty = 0

    for item in candidates:
        rid = item["release_id"]
        ok, reason = enrich_record(
            item=item,
            api=api,
            typeface_scripts_cache=typeface_scripts_cache,
            version_to_typeface_cache=version_to_typeface_cache,
        )
        processed += 1
        processed_ids.add(rid)
        if ok:
            enriched += 1
            dirty += 1
        else:
            if reason.startswith("trackable-") or reason.endswith("-missing"):
                failed += 1
            else:
                skipped += 1

        elapsed = time.monotonic() - started
        avg = elapsed / processed if processed > 0 else 0.0
        remaining = total - processed
        eta = avg * remaining if remaining > 0 else 0.0

        print(
            f"[progress] {processed}/{total} | enriched={enriched} skipped={skipped} failed={failed} "
            f"| last={reason} | eta={fmt_eta(eta)}"
        )

        should_save = (dirty >= max(1, args.save_every)) or (processed == total)
        if should_save:
            write_json_atomic(input_path, records)
            state_payload = {
                "started_at": state.get("started_at") or utc_now(),
                "updated_at": utc_now(),
                "processed_ids": sorted(processed_ids),
                "version_to_typeface": {str(k): v for k, v in version_to_typeface_cache.items()},
                "typeface_scripts": {str(k): v for k, v in typeface_scripts_cache.items()},
                "stats": {
                    "processed": processed,
                    "total": total,
                    "enriched": enriched,
                    "skipped": skipped,
                    "failed": failed,
                    "elapsed_seconds": round(elapsed, 2),
                },
            }
            write_json_atomic(state_path, state_payload)
            dirty = 0
            print(f"[save] file+state persisted | processed={processed}/{total}")

    total_elapsed = time.monotonic() - started
    print(
        f"[done] processed={processed} enriched={enriched} skipped={skipped} failed={failed} "
        f"| elapsed={fmt_eta(total_elapsed)}"
    )


if __name__ == "__main__":
    main()

