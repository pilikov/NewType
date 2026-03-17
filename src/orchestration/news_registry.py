"""Registry for news crawlers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.crawlers.news_base import NewsCrawler

NewsCrawlerFactory = Callable[[dict[str, Any]], NewsCrawler]


class NewsCrawlerRegistry:
    def __init__(self) -> None:
        self._factories: dict[str, NewsCrawlerFactory] = {}

    def register(self, mode: str, factory: NewsCrawlerFactory) -> None:
        self._factories[mode] = factory

    def build(self, source_cfg: dict[str, Any]) -> NewsCrawler:
        mode = source_cfg.get("crawl", {}).get("mode")
        if not mode:
            raise ValueError(f"Missing crawl mode for news source '{source_cfg.get('id')}'")
        factory = self._factories.get(mode)
        if not factory:
            raise ValueError(f"Unsupported news crawl mode '{mode}' for source '{source_cfg.get('id')}'")
        return factory(source_cfg)


def build_news_crawler_registry() -> NewsCrawlerRegistry:
    from src.crawlers.news.type_today_news import TypeTodayNewsCrawler
    from src.crawlers.news.futurefonts_news import FutureFontsNewsCrawler
    from src.crawlers.news.adobe_news import AdobeNewsCrawler
    from src.crawlers.news.typotheque_news import TypothequeNewsCrawler
    from src.crawlers.news.fontfabric_news import FontfabricNewsCrawler
    from src.crawlers.news.monotype_news import MonotypeNewsCrawler
    from src.crawlers.news.fontstand_news import FontstandNewsCrawler
    from src.crawlers.news.typenetwork_news import TypeNetworkNewsCrawler
    from src.crawlers.news.losttype_news import LostTypeNewsCrawler
    from src.crawlers.news.boldmonday_news import BoldMondayNewsCrawler
    from src.crawlers.news.daltonmaag_news import DaltonMaagNewsCrawler
    from src.crawlers.news.emigre_news import EmigreNewsCrawler
    from src.crawlers.news.commercialtype_news import CommercialTypeNewsCrawler
    from src.crawlers.news.grillitype_news import GrilliTypeNewsCrawler

    registry = NewsCrawlerRegistry()
    registry.register("type_today_news", TypeTodayNewsCrawler)
    registry.register("futurefonts_news", FutureFontsNewsCrawler)
    registry.register("adobe_news", AdobeNewsCrawler)
    registry.register("typotheque_news", TypothequeNewsCrawler)
    registry.register("fontfabric_news", FontfabricNewsCrawler)
    registry.register("monotype_news", MonotypeNewsCrawler)
    registry.register("fontstand_news", FontstandNewsCrawler)
    registry.register("typenetwork_news", TypeNetworkNewsCrawler)
    registry.register("losttype_news", LostTypeNewsCrawler)
    registry.register("boldmonday_news", BoldMondayNewsCrawler)
    registry.register("daltonmaag_news", DaltonMaagNewsCrawler)
    registry.register("emigre_news", EmigreNewsCrawler)
    registry.register("commercialtype_news", CommercialTypeNewsCrawler)
    registry.register("grillitype_news", GrilliTypeNewsCrawler)
    return registry
