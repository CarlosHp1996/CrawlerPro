from typing import Optional, Dict, Type
from src.core.base_crawler import BaseCrawler
from src.core.enums import Platform
from src.crawlers.mercadolivre_crawler import MercadoLivreCrawler
from src.crawlers.amazon_crawler import AmazonCrawler
from src.exceptions import ValidationException


class CrawlerFactory:
    _crawlers: Dict[Platform, Type[BaseCrawler]] = {}
    
    @classmethod
    def register(cls, platform: Platform, crawler_class: Type[BaseCrawler]) -> None:
        if not issubclass(crawler_class, BaseCrawler):
            raise ValidationException(
                f"Crawler class must inherit from BaseCrawler",
                {"platform": platform.value, "crawler_class": crawler_class.__name__}
            )
        cls._crawlers[platform] = crawler_class
    
    @classmethod
    def create(cls, platform: Platform, max_pages: Optional[int] = None, 
               delay_between_pages: Optional[int] = None) -> BaseCrawler:
        if platform not in cls._crawlers:
            raise ValidationException(
                f"No crawler registered for platform: {platform.value}",
                {"platform": platform.value, "available_platforms": [p.value for p in cls._crawlers.keys()]}
            )
        
        crawler_class = cls._crawlers[platform]
        return crawler_class(max_pages=max_pages, delay_between_pages=delay_between_pages)
    
    @classmethod
    def get_available_platforms(cls) -> list[Platform]:
        return list(cls._crawlers.keys())
    
    @classmethod
    def is_platform_available(cls, platform: Platform) -> bool:
        return platform in cls._crawlers


CrawlerFactory.register(Platform.MERCADOLIVRE, MercadoLivreCrawler)
CrawlerFactory.register(Platform.AMAZON, AmazonCrawler)
