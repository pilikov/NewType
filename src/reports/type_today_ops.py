from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from src.models import FontRelease
from src.utils import dump_json, ensure_dir, load_json


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _release_row(release: FontRelease) -> dict[str, Any]:
    payload = asdict(release)
    payload["release_id"] = release.release_id
    return payload


def _release_fingerprint(release: FontRelease) -> str:
    material = {
        "name": release.name,
        "styles": sorted(set(release.styles)),
        "authors": sorted(set(release.authors)),
        "scripts": sorted(set(release.scripts)),
        "release_date": release.release_date,
        "image_url": release.image_url,
        "woff_url": release.woff_url,
        "specimen_pdf_url": release.specimen_pdf_url,
        "year": release.raw.get("year"),
        "new_badge": release.raw.get("new_badge"),
    }
    encoded = str(material).encode("utf-8")
    return sha256(encoded).hexdigest()[:24]


def _build_missing_fields_report(releases: list[FontRelease]) -> dict[str, Any]:
    checks = {
        "missing_source_url": lambda r: not r.source_url,
        "missing_name": lambda r: not (r.name or "").strip(),
        "missing_release_date": lambda r: not r.release_date,
        "missing_styles": lambda r: len(r.styles) == 0,
        "missing_authors": lambda r: len(r.authors) == 0,
        "missing_scripts": lambda r: len(r.scripts) == 0,
        "missing_image_url": lambda r: not r.image_url,
        "missing_woff_url": lambda r: not r.woff_url,
        "missing_specimen_pdf_url": lambda r: not r.specimen_pdf_url,
    }
    rows: dict[str, list[str]] = {key: [] for key in checks}
    for release in releases:
        for key, fn in checks.items():
            if fn(release):
                rows[key].append(release.release_id)
    return {
        "generated_at": _now_iso(),
        "total_releases": len(releases),
        "missing_counts": {key: len(value) for key, value in rows.items()},
        "missing_release_ids": rows,
    }


def _build_normalization_plan(releases: list[FontRelease]) -> dict[str, Any]:
    canonical_scripts = {"Latin", "Cyrillic", "Greek", "Arabic", "Hebrew", "Armenian", "Georgian"}
    bad_script_rows: list[dict[str, Any]] = []
    noisy_author_rows: list[dict[str, Any]] = []
    duplicate_style_rows: list[dict[str, Any]] = []

    for release in releases:
        weird_scripts = [s for s in release.scripts if s not in canonical_scripts]
        if weird_scripts:
            bad_script_rows.append(
                {
                    "release_id": release.release_id,
                    "source_url": release.source_url,
                    "scripts": release.scripts,
                }
            )

        noisy_authors = [a for a in release.authors if "<" in a or ">" in a or len(a.strip()) < 2]
        if noisy_authors:
            noisy_author_rows.append(
                {
                    "release_id": release.release_id,
                    "source_url": release.source_url,
                    "authors": release.authors,
                }
            )

        style_lc = [s.strip().lower() for s in release.styles if s.strip()]
        if len(style_lc) != len(set(style_lc)):
            duplicate_style_rows.append(
                {
                    "release_id": release.release_id,
                    "source_url": release.source_url,
                    "styles": release.styles,
                }
            )

    return {
        "generated_at": _now_iso(),
        "total_releases": len(releases),
        "normalization_findings": {
            "non_canonical_scripts": {
                "count": len(bad_script_rows),
                "examples": bad_script_rows[:25],
            },
            "noisy_authors": {
                "count": len(noisy_author_rows),
                "examples": noisy_author_rows[:25],
            },
            "duplicate_styles_case_insensitive": {
                "count": len(duplicate_style_rows),
                "examples": duplicate_style_rows[:25],
            },
        },
        "recommendations": [
            "Normalize scripts to canonical enum and map unknown variants to Known/Other buckets.",
            "Strip HTML/noise from author strings and keep explicit array semantics.",
            "Deduplicate style names case-insensitively while preserving original title in raw.",
            "Keep release_date null if unknown; store year in raw and derive confidence in enrichment step.",
        ],
    }


def _build_monitor_report(
    source_cfg: dict[str, Any],
    releases: list[FontRelease],
    state_root: Path,
) -> dict[str, Any]:
    source_id = str(source_cfg.get("id") or "type_today")
    snapshot_path = state_root / f"{source_id}_monitor_snapshot.json"
    prev = load_json(snapshot_path, default={})
    prev_items = prev.get("items") if isinstance(prev, dict) else {}
    if not isinstance(prev_items, dict):
        prev_items = {}

    current_items = {
        release.release_id: {
            "slug": str(release.raw.get("slug") or ""),
            "name": release.name,
            "source_url": release.source_url,
            "fingerprint": _release_fingerprint(release),
        }
        for release in releases
    }

    prev_ids = set(prev_items.keys())
    current_ids = set(current_items.keys())
    new_ids = sorted(current_ids - prev_ids)
    removed_ids = sorted(prev_ids - current_ids)
    changed_ids = sorted(
        rid for rid in current_ids & prev_ids if current_items[rid].get("fingerprint") != prev_items[rid].get("fingerprint")
    )

    snapshot_payload = {
        "generated_at": _now_iso(),
        "source_id": source_id,
        "count": len(current_items),
        "items": current_items,
    }
    dump_json(snapshot_path, snapshot_payload)

    return {
        "generated_at": _now_iso(),
        "source_id": source_id,
        "total_releases": len(releases),
        "baseline_count": len(prev_items),
        "new_release_count": len(new_ids),
        "removed_release_count": len(removed_ids),
        "changed_release_count": len(changed_ids),
        "new_release_examples": [current_items[rid] for rid in new_ids[:30]],
        "removed_release_examples": [prev_items[rid] for rid in removed_ids[:30]],
        "changed_release_examples": [
            {
                "release_id": rid,
                "before": prev_items[rid],
                "after": current_items[rid],
            }
            for rid in changed_ids[:30]
        ],
        "monitoring_plan": [
            "Run source=type_today daily and inspect new_release_count/changed_release_count in this report.",
            "Alert when new_release_count > 0 or changed_release_count > 0.",
            "Store latest monitor snapshot in state to diff against previous run.",
            "Use fields[fonts]=slug,title,new_badge,year lightweight probe for frequent checks if needed.",
        ],
    }


def build_type_today_ops_reports(
    source_cfg: dict[str, Any],
    output_dir: Path,
    releases: list[FontRelease],
    state_root: Path,
) -> None:
    reports_dir = output_dir / "reports"
    ensure_dir(reports_dir)

    dump_json(
        reports_dir / "type_today_raw_releases.json",
        [_release_row(release) for release in releases],
    )
    dump_json(
        reports_dir / "type_today_missing_fields.json",
        _build_missing_fields_report(releases),
    )
    dump_json(
        reports_dir / "type_today_normalization_plan.json",
        _build_normalization_plan(releases),
    )
    dump_json(
        reports_dir / "type_today_monitor_report.json",
        _build_monitor_report(source_cfg=source_cfg, releases=releases, state_root=state_root),
    )
