from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

DEFAULT_API_BASE_URL = ""
DEFAULT_API_TOKEN = ""
DEFAULT_PAGE_SIZE = 1000
DEFAULT_MAX_RETRIES = 5

DEFAULT_TABLE_SELECTS: dict[str, str] = {
    "foundries": ",".join(
        [
            "id",
            "name",
            "url",
            "locations",
            "founded_year",
            "is_active",
            "has_trial",
            "trial_method",
            "trial_url",
            "og_image",
            "og_title",
            "og_description",
            "family_count",
            "font_count",
            "external_links",
            "sources",
            "is_distributor",
            "is_producer",
            "is_corporate",
            "status",
            "status_note",
            "deleted_at",
            "added_date",
            "added_by",
            "owner_id",
            "claimed_at",
            "featured_at",
            "featured_expires_at",
            "featured_order",
            "created_at",
            "created_by",
            "updated_by",
        ]
    ),
    "typefaces": ",".join(
        [
            "id",
            "name",
            "foundry_id",
            "url",
            "enriched_from",
            "release_year",
            "release_status",
            "primary_classification",
            "classification",
            "is_variable",
            "has_trial",
            "has_italic",
            "styles",
            "credits",
            "external_links",
            "language_support",
            "status",
            "status_note",
            "deleted_at",
            "featured_at",
            "featured_expires_at",
            "featured_order",
            "created_at",
            "created_by",
            "updated_by",
            "last_enriched",
        ]
    ),
    "designers": ",".join(
        [
            "id",
            "name",
            "designer_type",
            "url",
            "birth_year",
            "death_year",
            "location",
            "affiliations",
            "external_links",
            "profile_image_url",
            "last_verified",
            "status",
            "status_note",
            "deleted_at",
            "owner_id",
            "claimed_at",
            "featured_at",
            "featured_expires_at",
            "featured_order",
            "created_at",
            "created_by",
            "updated_by",
        ]
    ),
}


@dataclass
class ApiResponse:
    status_code: int
    payload: list[dict[str, Any]]
    headers: dict[str, str]


class SnapshotSyncRunner:
    def __init__(
        self,
        output_root: Path,
        state_root: Path,
        api_base_url: str = DEFAULT_API_BASE_URL,
        api_token: str = DEFAULT_API_TOKEN,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_retries: int = DEFAULT_MAX_RETRIES,
        timeout: int = 45,
    ) -> None:
        self.output_root = output_root
        self.state_root = state_root
        self.api_base_url = api_base_url.rstrip("/")
        self.api_token = api_token
        self.page_size = max(1, min(1000, page_size))
        self.max_retries = max(1, max_retries)
        self.timeout = timeout

        self.rest_url = f"{self.api_base_url}/rest/v1"
        self.output_root.mkdir(parents=True, exist_ok=True)
        self.state_root.mkdir(parents=True, exist_ok=True)
        self.checkpoint_path = self.state_root / "checkpoint.json"

        self.session = requests.Session()
        self.session.headers.update(
            {
                "apikey": self.api_token,
                "Authorization": f"Bearer {self.api_token}",
                "Accept": "application/json",
                "User-Agent": "TypeParser-SnapshotSync/1.0",
            }
        )

    def run(self, force_new_run: bool = False) -> dict[str, Any]:
        checkpoint = self._load_or_create_checkpoint(force_new_run=force_new_run)
        run_id = checkpoint["run_id"]
        output_dir = Path(checkpoint["output_dir"])
        raw_dir = output_dir / "raw"
        staging_dir = output_dir / "_staging"
        report_dir = output_dir / "reports"

        raw_dir.mkdir(parents=True, exist_ok=True)
        staging_dir.mkdir(parents=True, exist_ok=True)
        report_dir.mkdir(parents=True, exist_ok=True)

        metrics: dict[str, Any] = {
            "run_id": run_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "api": {
                "base_url": self.api_base_url,
                "rest_url": self.rest_url,
                "page_size": self.page_size,
            },
            "tables": {},
            "validation": {},
        }

        table_data: dict[str, list[dict[str, Any]]] = {}
        provenance_rows: list[dict[str, Any]] = []

        for table, select in DEFAULT_TABLE_SELECTS.items():
            table_metrics = self._crawl_table(
                table=table,
                select=select,
                checkpoint=checkpoint,
                raw_dir=raw_dir,
                staging_dir=staging_dir,
                run_id=run_id,
            )
            metrics["tables"][table] = table_metrics
            table_data[table] = self._load_json(staging_dir / f"{table}.json", default=[])

            for row in table_data[table]:
                provenance_rows.append(
                    {
                        "entity_type": table,
                        "entity_id": row.get("id"),
                        "source_table": table,
                        "source": "supabase.rest.v1",
                        "run_id": run_id,
                        "fetched_at": row.get("_fetched_at"),
                        "payload_sha256": row.get("_payload_sha256"),
                    }
                )

        normalized = self._build_normalized(table_data)
        validation = self._validate(normalized)
        metrics["validation"] = validation

        self._write_outputs(output_dir=output_dir, normalized=normalized, provenance_rows=provenance_rows)

        metrics["finished_at"] = datetime.now(timezone.utc).isoformat()
        metrics["duration_seconds"] = round(
            datetime.fromisoformat(metrics["finished_at"]).timestamp()
            - datetime.fromisoformat(metrics["started_at"]).timestamp(),
            3,
        )
        metrics["coverage"] = self._build_coverage(metrics, normalized)

        self._dump_json(report_dir / "coverage_report.json", metrics)
        checkpoint["status"] = "completed"
        checkpoint["completed_at"] = metrics["finished_at"]
        self._dump_json(self.checkpoint_path, checkpoint)

        return metrics

    def _crawl_table(
        self,
        table: str,
        select: str,
        checkpoint: dict[str, Any],
        raw_dir: Path,
        staging_dir: Path,
        run_id: str,
    ) -> dict[str, Any]:
        table_cp = checkpoint.setdefault("tables", {}).setdefault(
            table,
            {
                "next_offset": 0,
                "total_count": None,
                "completed": False,
                "pages_written": 0,
            },
        )

        total_count = table_cp.get("total_count")
        if total_count is None:
            total_count = self._count_table(table)
            table_cp["total_count"] = total_count
            self._dump_json(self.checkpoint_path, checkpoint)

        next_offset = int(table_cp.get("next_offset", 0))
        fetched_rows = 0
        raw_table_dir = raw_dir / table
        raw_table_dir.mkdir(parents=True, exist_ok=True)

        existing_rows = self._load_json(staging_dir / f"{table}.json", default=[])
        by_id: dict[str, dict[str, Any]] = {
            str(r.get("id")): r for r in existing_rows if isinstance(r, dict) and r.get("id") is not None
        }

        while next_offset < total_count:
            end_offset = min(next_offset + self.page_size - 1, total_count - 1)
            response = self._fetch_range(table=table, select=select, start=next_offset, end=end_offset)

            page_path = raw_table_dir / f"{next_offset:07d}_{end_offset:07d}.json"
            self._dump_json(
                page_path,
                {
                    "table": table,
                    "run_id": run_id,
                    "start": next_offset,
                    "end": end_offset,
                    "status_code": response.status_code,
                    "headers": response.headers,
                    "rows": response.payload,
                },
            )

            now_iso = datetime.now(timezone.utc).isoformat()
            for row in response.payload:
                if not isinstance(row, dict):
                    continue
                normalized = dict(row)
                normalized["_source_table"] = table
                normalized["_fetched_at"] = now_iso
                normalized["_payload_sha256"] = hashlib.sha256(
                    json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")
                ).hexdigest()
                rid = normalized.get("id")
                if rid is None:
                    # Keep row without id using synthetic hash key to avoid data loss.
                    rid = f"__noid__:{normalized['_payload_sha256']}"
                by_id[str(rid)] = self._merge_rows(by_id.get(str(rid)), normalized)

            fetched_rows += len(response.payload)
            table_cp["next_offset"] = end_offset + 1
            table_cp["pages_written"] = int(table_cp.get("pages_written", 0)) + 1
            next_offset = end_offset + 1

            self._dump_json(staging_dir / f"{table}.json", list(by_id.values()))
            self._dump_json(self.checkpoint_path, checkpoint)

        table_cp["completed"] = True
        self._dump_json(self.checkpoint_path, checkpoint)

        return {
            "total_count": total_count,
            "fetched_rows_this_run": fetched_rows,
            "unique_rows": len(by_id),
            "pages_written": table_cp.get("pages_written", 0),
            "completed": True,
        }

    def _count_table(self, table: str) -> int:
        url = f"{self.rest_url}/{table}"
        params = {"select": "id", "limit": 1}
        headers = {"Prefer": "count=exact"}

        response = self._request_with_retries("GET", url=url, params=params, headers=headers)
        content_range = response.headers.get("Content-Range", "")
        if "/" in content_range:
            total = content_range.split("/")[-1].strip()
            if total.isdigit():
                return int(total)

        payload = response.json()
        if isinstance(payload, list):
            return len(payload)
        return 0

    def _fetch_range(self, table: str, select: str, start: int, end: int) -> ApiResponse:
        url = f"{self.rest_url}/{table}"
        params = {"select": select}
        headers = {
            "Range-Unit": "items",
            "Range": f"{start}-{end}",
            "Prefer": "count=exact",
        }

        response = self._request_with_retries("GET", url=url, params=params, headers=headers)
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError(f"Unexpected payload type for table={table}, range={start}-{end}")

        return ApiResponse(
            status_code=response.status_code,
            payload=payload,
            headers={k: v for k, v in response.headers.items()},
        )

    def _request_with_retries(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self.session.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    timeout=self.timeout,
                )

                if resp.status_code in {429, 500, 502, 503, 504}:
                    if attempt >= self.max_retries:
                        resp.raise_for_status()
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        delay = float(retry_after)
                    else:
                        delay = min(10.0, 0.7 * (2 ** (attempt - 1))) + random.uniform(0, 0.25)
                    time.sleep(delay)
                    continue

                resp.raise_for_status()
                return resp
            except (requests.RequestException, ValueError):
                if attempt >= self.max_retries:
                    raise
                delay = min(10.0, 0.7 * (2 ** (attempt - 1))) + random.uniform(0, 0.25)
                time.sleep(delay)

        raise RuntimeError("Unreachable retry loop")

    def _build_normalized(self, table_data: dict[str, list[dict[str, Any]]]) -> dict[str, list[dict[str, Any]]]:
        foundries = table_data.get("foundries", [])
        typefaces = table_data.get("typefaces", [])
        designers = table_data.get("designers", [])

        for row in foundries:
            row["locations"] = self._parse_jsonish(row.get("locations"))
            row["external_links"] = self._parse_jsonish(row.get("external_links"))
            row["sources"] = self._parse_jsonish(row.get("sources"))

        for row in typefaces:
            row["classification"] = self._parse_jsonish(row.get("classification"))
            row["styles"] = self._parse_jsonish(row.get("styles"))
            row["credits"] = self._parse_jsonish(row.get("credits"))
            row["external_links"] = self._parse_jsonish(row.get("external_links"))
            row["language_support"] = self._parse_jsonish(row.get("language_support"))

        for row in designers:
            row["location"] = self._parse_jsonish(row.get("location"))
            row["affiliations"] = self._parse_jsonish(row.get("affiliations"))
            row["external_links"] = self._parse_jsonish(row.get("external_links"))

        rel_foundry_typeface: list[dict[str, Any]] = []
        rel_typeface_designer: list[dict[str, Any]] = []
        rel_designer_foundry: list[dict[str, Any]] = []

        for tf in typefaces:
            foundry_id = tf.get("foundry_id")
            typeface_id = tf.get("id")
            if typeface_id and foundry_id:
                rel_foundry_typeface.append(
                    {
                        "foundry_id": foundry_id,
                        "typeface_id": typeface_id,
                        "relationship": "publishes",
                        "source": "typefaces.foundry_id",
                    }
                )

            credits = tf.get("credits") if isinstance(tf.get("credits"), list) else []
            for credit in credits:
                if not isinstance(credit, dict):
                    continue
                designer_id = credit.get("designerId")
                if not designer_id or not typeface_id:
                    continue
                rel_typeface_designer.append(
                    {
                        "typeface_id": typeface_id,
                        "designer_id": designer_id,
                        "credit_name": credit.get("name"),
                        "source": "typefaces.credits",
                    }
                )

        for d in designers:
            designer_id = d.get("id")
            affiliations = d.get("affiliations") if isinstance(d.get("affiliations"), list) else []
            for aff in affiliations:
                if not isinstance(aff, dict):
                    continue
                foundry_id = aff.get("foundryId")
                if not designer_id or not foundry_id:
                    continue
                rel_designer_foundry.append(
                    {
                        "designer_id": designer_id,
                        "foundry_id": foundry_id,
                        "role": aff.get("role"),
                        "source": "designers.affiliations",
                    }
                )

        return {
            "foundries": foundries,
            "typefaces": typefaces,
            "designers": designers,
            "relationships_foundry_typeface": self._dedup_rows(rel_foundry_typeface),
            "relationships_typeface_designer": self._dedup_rows(rel_typeface_designer),
            "relationships_designer_foundry": self._dedup_rows(rel_designer_foundry),
        }

    def _validate(self, normalized: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        foundries = normalized["foundries"]
        typefaces = normalized["typefaces"]
        designers = normalized["designers"]

        foundry_ids = {str(r["id"]) for r in foundries if r.get("id") is not None}
        typeface_ids = {str(r["id"]) for r in typefaces if r.get("id") is not None}
        designer_ids = {str(r["id"]) for r in designers if r.get("id") is not None}

        missing_typeface_foundry = [
            r.get("id")
            for r in typefaces
            if r.get("foundry_id") and str(r.get("foundry_id")) not in foundry_ids
        ]

        rel_td = normalized["relationships_typeface_designer"]
        rel_df = normalized["relationships_designer_foundry"]

        missing_credit_designer = [
            r for r in rel_td if str(r.get("designer_id")) not in designer_ids
        ]
        missing_affiliation_foundry = [
            r for r in rel_df if str(r.get("foundry_id")) not in foundry_ids
        ]
        max_examples = 50

        return {
            "entity_counts": {
                "foundries": len(foundries),
                "typefaces": len(typefaces),
                "designers": len(designers),
                "foundry_ids_unique": len(foundry_ids),
                "typeface_ids_unique": len(typeface_ids),
                "designer_ids_unique": len(designer_ids),
            },
            "relationship_counts": {
                "foundry_typeface": len(normalized["relationships_foundry_typeface"]),
                "typeface_designer": len(rel_td),
                "designer_foundry": len(rel_df),
            },
            "referential_integrity": {
                "missing_typeface_foundry_refs_count": len(missing_typeface_foundry),
                "missing_credit_designer_refs_count": len(missing_credit_designer),
                "missing_affiliation_foundry_refs_count": len(missing_affiliation_foundry),
                "missing_typeface_foundry_refs_examples": missing_typeface_foundry[:max_examples],
                "missing_credit_designer_refs_examples": missing_credit_designer[:max_examples],
                "missing_affiliation_foundry_refs_examples": missing_affiliation_foundry[:max_examples],
            },
            "is_valid": (
                len(missing_typeface_foundry) == 0
                and len(missing_credit_designer) == 0
                and len(missing_affiliation_foundry) == 0
            ),
        }

    def _build_coverage(self, metrics: dict[str, Any], normalized: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
        coverage_tables: dict[str, Any] = {}
        for table in ("foundries", "typefaces", "designers"):
            table_metrics = metrics["tables"].get(table, {})
            total = int(table_metrics.get("total_count") or 0)
            unique = len(normalized.get(table, []))
            pct = 0.0 if total == 0 else round((unique / total) * 100, 2)
            coverage_tables[table] = {
                "total_count_api": total,
                "unique_rows_local": unique,
                "coverage_percent": pct,
            }

        return {
            "tables": coverage_tables,
            "overall_tables_with_100pct": [
                t for t, info in coverage_tables.items() if info["coverage_percent"] >= 100.0
            ],
        }

    def _write_outputs(
        self,
        output_dir: Path,
        normalized: dict[str, list[dict[str, Any]]],
        provenance_rows: list[dict[str, Any]],
    ) -> None:
        norm_dir = output_dir / "normalized"
        rel_dir = output_dir / "relationships"
        prov_dir = output_dir / "provenance"

        norm_dir.mkdir(parents=True, exist_ok=True)
        rel_dir.mkdir(parents=True, exist_ok=True)
        prov_dir.mkdir(parents=True, exist_ok=True)

        for key in ("foundries", "typefaces", "designers"):
            rows = normalized[key]
            self._dump_json(norm_dir / f"{key}.json", rows)
            self._write_csv(norm_dir / f"{key}.csv", rows)

        for key in (
            "relationships_foundry_typeface",
            "relationships_typeface_designer",
            "relationships_designer_foundry",
        ):
            rows = normalized[key]
            self._dump_json(rel_dir / f"{key}.json", rows)
            self._write_csv(rel_dir / f"{key}.csv", rows)

        self._dump_json(prov_dir / "entity_provenance.json", provenance_rows)
        self._write_csv(prov_dir / "entity_provenance.csv", provenance_rows)

    def _load_or_create_checkpoint(self, force_new_run: bool) -> dict[str, Any]:
        existing = self._load_json(self.checkpoint_path, default={})
        if (
            not force_new_run
            and isinstance(existing, dict)
            and existing.get("status") == "in_progress"
            and existing.get("run_id")
            and existing.get("output_dir")
        ):
            return existing

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_dir = self.output_root / run_id
        output_dir.mkdir(parents=True, exist_ok=True)

        checkpoint = {
            "run_id": run_id,
            "status": "in_progress",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "output_dir": str(output_dir),
            "tables": {},
        }
        self._dump_json(self.checkpoint_path, checkpoint)
        return checkpoint

    @staticmethod
    def _parse_jsonish(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (list, dict, int, float, bool)):
            return value
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return None
            try:
                return json.loads(raw)
            except Exception:
                return value
        return value

    @staticmethod
    def _merge_rows(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
        if not existing:
            return incoming
        merged = dict(existing)
        for key, value in incoming.items():
            if value is not None:
                merged[key] = value
        return merged

    @staticmethod
    def _dedup_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = hashlib.sha256(
                json.dumps(row, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            out[key] = row
        return list(out.values())

    @staticmethod
    def _load_json(path: Path, default: Any) -> Any:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default

    @staticmethod
    def _dump_json(path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _json_cell(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        return str(value)

    def _write_csv(self, path: Path, rows: list[dict[str, Any]]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not rows:
            path.write_text("", encoding="utf-8")
            return

        columns: list[str] = sorted({k for row in rows for k in row.keys()})
        with path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({col: self._json_cell(row.get(col)) for col in columns})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Snapshot sync runner")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/catalog_snapshot",
        help="Output directory root for generated snapshots",
    )
    parser.add_argument(
        "--state-dir",
        type=str,
        default="state/catalog_snapshot",
        help="State directory for checkpoint metadata",
    )
    parser.add_argument(
        "--api-base-url",
        type=str,
        default=os.getenv("SNAPSHOT_API_BASE_URL", DEFAULT_API_BASE_URL),
        help="Base URL for REST API host",
    )
    parser.add_argument(
        "--api-token",
        type=str,
        default=os.getenv("SNAPSHOT_API_TOKEN", DEFAULT_API_TOKEN),
        help="Bearer/apikey token for REST API",
    )
    parser.add_argument(
        "--page-size",
        type=int,
        default=DEFAULT_PAGE_SIZE,
        help="Page size for range pagination (max 1000)",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=DEFAULT_MAX_RETRIES,
        help="Max retry attempts for failed requests",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=45,
        help="HTTP timeout in seconds",
    )
    parser.add_argument(
        "--force-new-run",
        action="store_true",
        help="Ignore in-progress checkpoint and create a new run",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.api_base_url or not args.api_token:
        raise SystemExit("Missing API credentials: set --api-base-url and --api-token")

    crawler = SnapshotSyncRunner(
        output_root=Path(args.output_dir),
        state_root=Path(args.state_dir),
        api_base_url=args.api_base_url,
        api_token=args.api_token,
        page_size=args.page_size,
        max_retries=args.max_retries,
        timeout=args.timeout,
    )
    report = crawler.run(force_new_run=bool(args.force_new_run))

    coverage = report.get("coverage", {}).get("tables", {})
    short = {
        table: {
            "total": data.get("total_count_api"),
            "local": data.get("unique_rows_local"),
            "coverage_percent": data.get("coverage_percent"),
        }
        for table, data in coverage.items()
    }
    print(json.dumps({"run_id": report.get("run_id"), "coverage": short}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
