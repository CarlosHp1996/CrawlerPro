import asyncio
import time
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime

from src.core.enums import Platform
from src.core.models import ProductData, CrawlerResult
from src.exceptions import CrawlerBaseException, ValidationException
from src.logging_config import get_logger
from src.metrics import get_metrics_collector, setup_default_alerts
from src.health_monitor import get_adaptive_rate_limiter
from src.retry_system import get_retry_manager


class BaseCrawler(ABC):
    def __init__(self, max_pages: int = 5, delay_between_pages: int = 2):
        self.max_pages = max_pages
        self.delay_between_pages = delay_between_pages
        self.platform = self.get_platform()
        
        self.metrics_collector = get_metrics_collector()
        self.rate_limiter = get_adaptive_rate_limiter()
        self.retry_manager = get_retry_manager()
        self.logger = get_logger(f"{self.platform.value}_crawler")
        
        setup_default_alerts()
    
    @abstractmethod
    def get_platform(self) -> Platform:
        pass
    
    @abstractmethod
    def build_search_url(self, search_term: str, page: int) -> str:
        pass
    
    @abstractmethod
    async def extract_products(self, html: str, page: int) -> List[Dict[str, Any]]:
        pass
    
    @abstractmethod
    def normalize_product_data(self, raw_product: Dict[str, Any]) -> ProductData:
        pass
    
    async def search_products(self, search_term: str) -> CrawlerResult:
        if not search_term or not search_term.strip():
            raise ValidationException("Search term cannot be empty")
        
        search_term = search_term.strip()
        start_time = time.time()
        all_products = []
        pages_crawled = 0
        
        self.logger.info(f"Starting search on {self.platform.value}: term='{search_term}', max_pages={self.max_pages}")
        
        try:
            for page in range(1, self.max_pages + 1):
                self.logger.info(f"Processing page {page}/{self.max_pages}")
                
                await self.rate_limiter.acquire()
                
                search_url = self.build_search_url(search_term, page)
                html_content = await self._fetch_page(search_url)
                
                if not html_content:
                    self.logger.warning(f"No content retrieved for page {page}")
                    break
                
                products = await self.extract_products(html_content, page)
                
                if not products:
                    self.logger.info(f"No products found on page {page}, stopping")
                    break
                
                all_products.extend(products)
                pages_crawled += 1
                
                self.logger.info(f"Page {page}: extracted {len(products)} products")
                
                if page < self.max_pages:
                    await asyncio.sleep(self.delay_between_pages)
            
            normalized_products = [
                self.normalize_product_data(prod) for prod in all_products
            ]
            
            execution_time = time.time() - start_time
            
            self.logger.info(
                f"Search completed on {self.platform.value}: "
                f"{len(normalized_products)} products, {pages_crawled} pages, {execution_time:.2f}s"
            )
            
            return CrawlerResult(
                search_term=search_term,
                platform=self.platform.value,
                total_products=len(normalized_products),
                pages_crawled=pages_crawled,
                timestamp=datetime.utcnow().isoformat(),
                execution_time=execution_time,
                products=normalized_products,
                success=True
            )
            
        except CrawlerBaseException as e:
            execution_time = time.time() - start_time
            self.logger.error(f"Crawler error on {self.platform.value}: {str(e)}")
            
            return CrawlerResult(
                search_term=search_term,
                platform=self.platform.value,
                total_products=len(all_products),
                pages_crawled=pages_crawled,
                timestamp=datetime.utcnow().isoformat(),
                execution_time=execution_time,
                products=[self.normalize_product_data(prod) for prod in all_products],
                success=False,
                error_message=str(e)
            )
        
        except Exception as e:
            execution_time = time.time() - start_time
            self.logger.error(f"Unexpected error on {self.platform.value}: {str(e)}", exc_info=True)
            
            return CrawlerResult(
                search_term=search_term,
                platform=self.platform.value,
                total_products=0,
                pages_crawled=pages_crawled,
                timestamp=datetime.utcnow().isoformat(),
                execution_time=execution_time,
                products=[],
                success=False,
                error_message=f"Unexpected error: {str(e)}"
            )
    
    @abstractmethod
    async def _fetch_page(self, url: str) -> Optional[str]:
        pass
