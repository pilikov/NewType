from __future__ import annotations

from src.crawlers.shared.text import unique_strings
from src.models import FontRelease


def normalize_contemporarytype_release(release: FontRelease, source_cfg: dict) -> FontRelease:
    raw = release.raw if isinstance(release.raw, dict) else {}
    languages = raw.get("supported_languages")
    if not isinstance(languages, list):
        product = raw.get("product") if isinstance(raw.get("product"), dict) else {}
        languages = product.get("languages") if isinstance(product.get("languages"), list) else []

    hints = " ".join([str(x or "").strip().lower() for x in languages if str(x or "").strip()])
    scripts: list[str] = []

    if any(token in hints for token in ("latin", "english", "french", "german", "spanish", "portuguese")):
        scripts.append("Latin")
    if any(token in hints for token in ("cyrillic", "russian", "ukrainian", "bulgarian", "serbian")):
        scripts.append("Cyrillic")
    if "greek" in hints:
        scripts.append("Greek")
    if "arabic" in hints:
        scripts.append("Arabic")
    if "hebrew" in hints:
        scripts.append("Hebrew")

    release.scripts = unique_strings(scripts) if scripts else release.scripts
    return release
