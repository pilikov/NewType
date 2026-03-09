from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.models import FontRelease
from src.normalization.contemporarytype import normalize_contemporarytype_release
from src.normalization.myfonts import normalize_myfonts_release

ReleaseNormalizer = Callable[[FontRelease, dict[str, Any]], FontRelease]


def _noop_normalizer(release: FontRelease, _: dict[str, Any]) -> FontRelease:
    return release


class ReleaseNormalizerRegistry:
    def __init__(self) -> None:
        self._normalizers: dict[str, ReleaseNormalizer] = {}

    def register(self, source_id: str, normalizer: ReleaseNormalizer) -> None:
        self._normalizers[source_id] = normalizer

    def normalize_release(self, source_cfg: dict[str, Any], release: FontRelease) -> FontRelease:
        source_id = str(source_cfg.get("id") or "")
        normalizer = self._normalizers.get(source_id, _noop_normalizer)
        return normalizer(release, source_cfg)

    def normalize_many(self, source_cfg: dict[str, Any], releases: list[FontRelease]) -> list[FontRelease]:
        return [self.normalize_release(source_cfg, release) for release in releases]


def build_default_normalizer_registry() -> ReleaseNormalizerRegistry:
    registry = ReleaseNormalizerRegistry()
    registry.register("myfonts", normalize_myfonts_release)
    registry.register("contemporarytype", normalize_contemporarytype_release)
    return registry
