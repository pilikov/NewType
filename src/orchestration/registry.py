from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.crawlers.base import Crawler
from src.crawlers.contemporarytype_products import ContemporaryTypeProductsCrawler
from src.crawlers.fontstand_catalog import FontstandCatalogCrawler
from src.crawlers.fontstand_new_releases import FontstandNewReleasesCrawler
from src.crawlers.futurefonts_activity import FutureFontsActivityCrawler
from src.crawlers.futurefonts_sitemap import FutureFontsSitemapCrawler
from src.crawlers.html_list import HtmlListCrawler
from src.crawlers.ilt_typesense import IltTypesenseCrawler
from src.crawlers.myfonts_api import MyFontsApiCrawler
from src.crawlers.myfonts_whats_new import MyFontsWhatsNewCrawler
from src.crawlers.type_today_api import TypeTodayApiCrawler
from src.crawlers.type_today_journal import TypeTodayJournalCrawler
from src.crawlers.type_today_next import TypeTodayNextCrawler
from src.crawlers.typenetwork_public_families import TypeNetworkPublicFamiliesCrawler

CrawlerFactory = Callable[[dict[str, Any]], Crawler]


class CrawlerRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, CrawlerFactory] = {}

    def register(self, mode: str, factory: CrawlerFactory) -> None:
        self._factories[mode] = factory

    def build(self, source_cfg: dict[str, Any]) -> Crawler:
        mode = source_cfg.get("crawl", {}).get("mode")
        if not mode:
            raise ValueError(f"Missing crawl mode for source '{source_cfg.get('id')}'")
        factory = self._factories.get(mode)
        if not factory:
            raise ValueError(f"Unsupported crawl mode '{mode}' for source '{source_cfg.get('id')}'")
        return factory(source_cfg)


def build_default_crawler_registry() -> CrawlerRegistry:
    registry = CrawlerRegistry()
    registry.register("html_list", HtmlListCrawler)
    registry.register("myfonts_api", MyFontsApiCrawler)
    registry.register("myfonts_whats_new", MyFontsWhatsNewCrawler)
    registry.register("type_today_api", TypeTodayApiCrawler)
    registry.register("type_today_next", TypeTodayNextCrawler)
    registry.register("type_today_journal", TypeTodayJournalCrawler)
    registry.register("futurefonts_sitemap", FutureFontsSitemapCrawler)
    registry.register("futurefonts_activity", FutureFontsActivityCrawler)
    registry.register("typenetwork_public_families", TypeNetworkPublicFamiliesCrawler)
    registry.register("contemporarytype_products", ContemporaryTypeProductsCrawler)
    registry.register("fontstand_catalog", FontstandCatalogCrawler)
    registry.register("fontstand_new_releases", FontstandNewReleasesCrawler)
    registry.register("ilt_typesense", IltTypesenseCrawler)
    return registry
