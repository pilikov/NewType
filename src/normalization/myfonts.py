from __future__ import annotations

from typing import Any

from src.crawlers.myfonts_api import _SCRIPT_HINTS, _map_languages_to_scripts, _ordered_unique_scripts
from src.models import FontRelease


def normalize_myfonts_release(release: FontRelease, source_cfg: dict[str, Any]) -> FontRelease:
    raw = release.raw if isinstance(release.raw, dict) else {}
    crawl_cfg = source_cfg.get("crawl", {}) if isinstance(source_cfg, dict) else {}
    mode = str(crawl_cfg.get("language_script_signal_mode", "balanced")).strip().lower()
    if mode not in {"balanced", "strong"}:
        mode = "balanced"

    supported_languages = raw.get("tech_specs_supported_languages")
    language_tokens: list[str] = []
    if isinstance(supported_languages, list):
        language_tokens = [str(v).strip() for v in supported_languages if str(v).strip()]
    elif isinstance(supported_languages, str) and supported_languages.strip():
        language_tokens = [part.strip() for part in supported_languages.split(",") if part.strip()]

    tag_scripts = _extract_tag_scripts(raw.get("tags"))

    if language_tokens:
        inferred_scripts = _map_languages_to_scripts(language_tokens, mode=mode)
        # Prefer deterministic re-derivation from stored language signals + explicit tag hints.
        release.scripts = _ordered_unique_scripts([*tag_scripts, *inferred_scripts])

    is_package_product = bool(raw.get("is_package_product"))
    if not is_package_product:
        is_package_product = _looks_like_package(
            str(raw.get("handle") or ""),
            str(release.name or ""),
            str(raw.get("product_url") or release.source_url or ""),
        )
        raw["is_package_product"] = is_package_product

    has_script_metadata = bool(raw.get("tech_specs_scripts") or raw.get("tech_specs_supported_languages"))
    has_collection_url = bool(raw.get("collection_url"))
    raw["is_package_without_metadata"] = bool(is_package_product and not has_script_metadata and not has_collection_url)

    if release.scripts:
        release.script_status = "ok"
    elif raw["is_package_without_metadata"]:
        release.script_status = "unknown_package_no_metadata"
    else:
        release.script_status = "unknown"

    release.raw = raw
    return release


def _extract_tag_scripts(tags: Any) -> list[str]:
    values = tags if isinstance(tags, list) else [tags]
    normalized = " ".join(str(item or "").lower() for item in values)
    scripts: list[str] = []
    for needle, label in _SCRIPT_HINTS.items():
        if needle in normalized:
            scripts.append(label)
    return _ordered_unique_scripts(scripts)


def _looks_like_package(handle: str, name: str, url: str) -> bool:
    lowered = " ".join([handle, name, url]).lower()
    return (
        "-package-" in lowered
        or " package " in f" {lowered} "
        or " bundle" in lowered
        or "collection-package" in lowered
        or "family-package" in lowered
    )
