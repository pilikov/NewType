from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from src.models import FontRelease
from src.utils import dump_json, ensure_dir, load_json


class JsonStorageAdapter:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def source_output_dir(
        self,
        source_id: str,
        period_label: str | None = None,
    ) -> Path:
        run_date = date.today().isoformat()
        out_dir = self.data_dir / source_id / run_date
        if period_label:
            out_dir = self.data_dir / source_id / "periods" / period_label
        return out_dir

    def load_releases(self, path: Path) -> list[FontRelease]:
        rows = load_json(path, default=[])
        if not isinstance(rows, list):
            return []
        out: list[FontRelease] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            try:
                out.append(
                    FontRelease(
                        source_id=row.get("source_id") or "",
                        source_name=row.get("source_name") or "",
                        source_url=row.get("source_url"),
                        name=row.get("name") or "",
                        styles=list(row.get("styles") or []),
                        authors=list(row.get("authors") or []),
                        scripts=list(row.get("scripts") or []),
                        release_date=row.get("release_date"),
                        image_url=row.get("image_url"),
                        woff_url=row.get("woff_url"),
                        specimen_pdf_url=row.get("specimen_pdf_url"),
                        discovered_at=row.get("discovered_at") or datetime.utcnow().isoformat() + "Z",
                        raw=dict(row.get("raw") or {}),
                    )
                )
            except Exception:
                continue
        return out

    def write_releases(self, path: Path, releases: list[FontRelease]) -> None:
        dump_json(path, [r.to_dict() for r in releases])

    def merge_releases(
        self,
        existing: list[FontRelease],
        incoming: list[FontRelease],
    ) -> list[FontRelease]:
        by_id: dict[str, FontRelease] = {}
        for release in existing:
            by_id[release.release_id] = release
        for release in incoming:
            by_id[release.release_id] = release
        return list(by_id.values())

    def persist_source_results(
        self,
        source_id: str,
        all_releases: list[FontRelease],
        new_releases: list[FontRelease],
        period_label: str | None = None,
    ) -> Path:
        out_dir = self.source_output_dir(source_id, period_label)
        ensure_dir(out_dir)

        merged_all = self.merge_releases(
            self.load_releases(out_dir / "all_releases.json"),
            all_releases,
        )
        merged_new = self.merge_releases(
            self.load_releases(out_dir / "new_releases.json"),
            new_releases,
        )

        self.write_releases(out_dir / "all_releases.json", merged_all)
        self.write_releases(out_dir / "new_releases.json", merged_new)
        return out_dir
