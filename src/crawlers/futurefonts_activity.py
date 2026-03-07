from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from src.models import FontRelease


@dataclass
class FutureFontsActivityCrawler:
    source_config: dict[str, Any]
    release_callback: Any = None

    def set_release_callback(self, callback: Any) -> None:
        self.release_callback = callback

    def crawl(self, session: requests.Session, timeout: int = 20) -> list[FontRelease]:
        source_id = self.source_config["id"]
        source_name = self.source_config.get("name", source_id)
        base_url = self.source_config.get("base_url", "https://www.futurefonts.com")

        crawl_cfg = self.source_config.get("crawl", {})
        endpoint = crawl_cfg.get("activity_endpoint", "/api/v1/activity")
        max_pages_per_type = int(crawl_cfg.get("max_pages_per_type", 6))
        lookback_days = int(crawl_cfg.get("lookback_days", 30))
        detail_fetch_limit = int(crawl_cfg.get("detail_fetch_limit", 40))
        start_date = _parse_ymd_date(crawl_cfg.get("start_date"))
        end_date = _parse_ymd_date(crawl_cfg.get("end_date"))
        since_day = start_date or (date.today() - timedelta(days=lookback_days))

        activity_filters = [
            ("typeface.new_release", "new_release"),
            ("typeface_version.new_version", "new_version"),
        ]

        releases: list[FontRelease] = []
        detail_fetch_count = 0
        seen_activity_ids: set[int] = set()

        for activity_value, release_kind in activity_filters:
            should_stop_filter = False

            for page in range(1, max_pages_per_type + 1):
                params = {
                    "activity_type[]": activity_value,
                    "page": page,
                }

                response = session.get(f"{base_url}{endpoint}", params=params, timeout=timeout)
                response.raise_for_status()
                payload = response.json()
                activities = payload.get("activities", [])

                if not activities:
                    break

                for activity in activities:
                    activity_id = activity.get("id")
                    if isinstance(activity_id, int) and activity_id in seen_activity_ids:
                        continue
                    if isinstance(activity_id, int):
                        seen_activity_ids.add(activity_id)

                    created_at_raw = activity.get("created_at")
                    created_day = _parse_iso_date(created_at_raw)
                    if end_date and created_day and created_day > end_date:
                        continue
                    if created_day and created_day < since_day:
                        should_stop_filter = True
                        break

                    trackable = activity.get("trackable") or {}
                    source_url = (activity.get("url") or "").strip()
                    if not source_url:
                        continue

                    name = (
                        (trackable.get("name") or "").strip()
                        or ((trackable.get("typeface") or {}).get("name") or "").strip()
                        or _name_from_url(source_url)
                    )

                    authors = []
                    foundry = trackable.get("foundry") or {}
                    foundry_name = (foundry.get("name") or "").strip()
                    if foundry_name:
                        authors.append(foundry_name)

                    image_url = _extract_image_url(activity.get("image"))

                    specimen_pdf_url = None
                    maybe_specimen = trackable.get("specimen_unsigned_url")
                    if isinstance(maybe_specimen, str) and maybe_specimen.lower().endswith(".pdf"):
                        specimen_pdf_url = maybe_specimen

                    woff_url = None

                    if detail_fetch_count < detail_fetch_limit:
                        detail = self._fetch_detail(session, source_url, timeout)
                        detail_fetch_count += 1
                        if detail:
                            detail_name = (detail.get("name") or "").strip()
                            if detail_name and detail_name.lower() != foundry_name.lower():
                                name = detail_name
                            if detail.get("image_url"):
                                image_url = detail["image_url"]
                            if detail.get("specimen_pdf_url"):
                                specimen_pdf_url = detail["specimen_pdf_url"]
                            if detail.get("woff_url"):
                                woff_url = detail["woff_url"]

                    version_label = None
                    if release_kind == "new_version":
                        major = trackable.get("major_version_number")
                        minor = trackable.get("minor_version_number")
                        if major is not None and minor is not None:
                            version_label = f"{major}.{minor}"

                    release = FontRelease(
                        source_id=source_id,
                        source_name=source_name,
                        source_url=source_url,
                        name=name,
                        styles=[],
                        authors=authors,
                        scripts=[],
                        release_date=created_day.isoformat() if created_day else None,
                        image_url=image_url,
                        woff_url=woff_url,
                        specimen_pdf_url=specimen_pdf_url,
                        raw={
                            "release_identity": (
                                f"futurefonts-activity:{activity_id}"
                                if activity_id is not None
                                else f"{release_kind}:{source_url}:{created_at_raw}:{version_label or ''}"
                            ),
                            "activity_id": activity_id,
                            "activity_key": activity.get("key"),
                            "activity_type": activity.get("activity_type"),
                            "activity_type_label": activity.get("activity_type_label"),
                            "release_kind": release_kind,
                            "is_new_version": release_kind == "new_version",
                            "version": version_label,
                            "trackable_type": activity.get("trackable_type"),
                            "trackable_id": activity.get("trackable_id"),
                        },
                    )
                    releases.append(release)
                    if self.release_callback:
                        self.release_callback(release)

                if should_stop_filter:
                    break

            if should_stop_filter:
                continue

        return releases

    def _fetch_detail(
        self,
        session: requests.Session,
        source_url: str,
        timeout: int,
    ) -> dict[str, str] | None:
        try:
            response = session.get(source_url, timeout=timeout)
            response.raise_for_status()
        except requests.RequestException:
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        name = None
        og_title = _meta_content(soup, "og:title")
        if og_title:
            name = og_title.split(" - Future Fonts", 1)[0].strip()
            if " by " in name:
                name = name.split(" by ", 1)[0].strip()

        image_url = _meta_content(soup, "og:image")

        specimen_pdf_url = None
        woff_url = None
        for a in soup.select("a[href]"):
            href = (a.get("href") or "").strip()
            low = href.lower()
            if not specimen_pdf_url and low.endswith(".pdf"):
                specimen_pdf_url = href
            if not woff_url and (low.endswith(".woff") or low.endswith(".woff2")):
                woff_url = href

        return {
            "name": name or "",
            "image_url": image_url or "",
            "specimen_pdf_url": specimen_pdf_url or "",
            "woff_url": woff_url or "",
        }


def _extract_image_url(image_payload: Any) -> str | None:
    if isinstance(image_payload, str):
        return image_payload
    if not isinstance(image_payload, dict):
        return None
    for key in ("large", "medium", "small", "thumb", "orginal"):
        value = image_payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _meta_content(soup: BeautifulSoup, key: str) -> str | None:
    node = soup.select_one(f"meta[property='{key}'], meta[name='{key}']")
    if node and node.get("content"):
        return node.get("content").strip()
    return None


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _name_from_url(url: str) -> str:
    parts = [p for p in urlparse(url).path.split("/") if p]
    if parts:
        return parts[-1].replace("-", " ").title()
    return "Unknown"


def _parse_ymd_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
