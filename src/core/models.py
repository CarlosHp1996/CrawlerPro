from dataclasses import dataclass, asdict
from typing import List, Optional
import json


@dataclass
class ProductData:
    title: str
    price: str
    original_price: str
    discount_percentage: str
    seller: str
    rating: str
    reviews_count: str
    shipping: str
    product_url: str
    image_url: str
    installments: str
    location: str
    page_number: int
    position_on_page: int


@dataclass
class CrawlerResult:
    search_term: str
    platform: str
    total_products: int
    pages_crawled: int
    timestamp: str
    execution_time: float
    products: List[ProductData]
    success: bool
    error_message: Optional[str] = None
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)
