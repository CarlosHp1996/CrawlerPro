"""
Centralizing class for all system configurations.

This module contains all system settings organized into a single class
to facilitate maintenance and customization. It includes CSS selectors, URLs,
timeouts, Crawl4AI settings, and directory structure.

Usage:
    from config import Config
    
    crawler = MercadoLivreCrawler(
        max_pages=Config.MAX_PAGES,
        delay_between_pages=Config.DELAY_BETWEEN_PAGES
    )
"""

import os
from pathlib import Path
from typing import Dict, List, Any

class Config:
    """
    Centralizing class for all system configurations.
    
    Organizes settings into logical categories:
    - Directories and files
    - Crawler parameters
    - URLs and endpoints
    - CSS selectors by layout
    - Crawl4AI settings
    - Logging and debugging
    """
    # Directories
    BASE_DIR = Path(__file__).parent
    OUTPUT_DIR = BASE_DIR / "output"
    JSON_OUTPUT_DIR = OUTPUT_DIR / "json"
    EXCEL_OUTPUT_DIR = OUTPUT_DIR / "excel"
    LOGS_DIR = BASE_DIR / "logs"
    
    # Crawler settings
    MAX_PAGES = 5
    DELAY_BETWEEN_PAGES = 2
    REQUEST_TIMEOUT = 30
    
    # URLs
    MERCADO_LIVRE_BASE_URL = "https://lista.mercadolivre.com.br"

    # CSS selectors organized by layout
    SELECTORS = {
        'POLY_CARD': {
            'title': [
                '.poly-component__title a',
                '.poly-component__title',
                'h2.poly-box',
                '.poly-component__title-wrapper a',
                'h2',
                'a[title]'
            ],
            'price_current': [
                '.poly-price__current .andes-money-amount__fraction',
                '.andes-money-amount__fraction',
                '.poly-component__price .andes-money-amount__fraction',
                'span.andes-money-amount__fraction'
            ],
            'price_original': [
                '.andes-money-amount--previous .andes-money-amount__fraction',
                's.andes-money-amount .andes-money-amount__fraction',
                '.andes-money-amount--previous',
                's.andes-money-amount'
            ],
            'discount': [
                '.andes-money-amount__discount',
                'span[class*="discount"]',
                '.poly-price__discount'
            ],
            'seller': [
                '.poly-component__seller',
                '.ui-search-official-store-label',
                'span[class*="seller"]',
                'span[class*="store"]'
            ],
            'rating': [
                '.poly-reviews__rating',
                '.ui-search-reviews__rating-number',
                'span[class*="rating"]'
            ],
            'reviews_count': [
                '.poly-reviews__total',
                '.ui-search-reviews__amount',
                'span[class*="reviews"]'
            ],
            'shipping': [
                '.poly-component__shipping',
                '.ui-search-item__shipping',
                'p[class*="shipping"]',
                'span[class*="shipping"]'
            ],
            'installments': [
                '.poly-price__installments',
                '.ui-search-item__group__element--installments',
                'span[class*="installments"]'
            ],
            'location': [
                '.poly-component__location',
                '.ui-search-item__location',
                'span[class*="location"]'
            ],
            'product_link': [
                '.poly-component__title a',
                '.poly-card a[href*="mercadolivre"]',
                'a[href*="mercadolibre"]',
                'a[href]'
            ],
            'image': [
                # Specific selectors for sponsored ads
                '.poly-card__portada img',
                '.poly-component__picture img',

                # Specific selectors for organic products
                '.ui-search-result-image img',
                '.ui-search-result__image img',
                '.ui-search-result-image__element img',
                '.ui-search-result__image-wrapper img',

                # Specific selectors for poly-card layout
                '.poly-card img',
                '.poly-component img',
                '.poly-box img',

                # Common CSS class selectors
                'img[class*="ui-search"]',
                'img[class*="poly"]',
                'img[class*="result"]',
                'img[class*="product"]',
                'img[class*="item"]',
                'img[class*="card"]',
                # Specific selectors for HTML structure
                'figure img',
                'picture img',
                'div[class*="image"] img',
                'div[class*="picture"] img',
                'div[class*="photo"] img',
                'span[class*="image"] img',

                # Specific selectors for position in structure
                'li img',
                'article img',
                'section img',
                'a img',
                
                # Seletores por atributos específicos
                'img[src*="mlstatic"]',
                'img[data-src*="mlstatic"]',
                'img[data-lazy*="mlstatic"]',
                'img[srcset*="mlstatic"]',
                
                # Fallback - any image with HTTP protocol
                'img[src*="http"]',
                'img[data-src*="http"]',

                # Last resort - any image
                'img'
            ]
        },
        'CLASSIC': {
            'title': [
                'h2.ui-search-item__title',
                '.ui-search-item__title',
                'a.ui-search-item__group__element'
            ],
            'price_current': [
                'span.andes-money-amount__fraction',
                'span.price-tag-fraction'
            ],
            'price_original': [],
            'discount': [],
            'seller': [],
            'rating': [],
            'reviews_count': [],
            'shipping': [],
            'installments': [],
            'location': [],
            'product_link': [
                'a[href*="mercadolivre"]',
                'a[href]'
            ],
            'image': [
                '.ui-search-result-image img',
                '.ui-search-result__image img',
                'img[class*="ui-search"]',
                'figure img',
                'a img',
                'img[src*="mlstatic"]',
                'img'
            ]
        },
        
        # Amazon Brasil selectors
        'AMAZON': {
            'CONTAINER': 'div.s-main-slot',
            'PRODUCT_CARD': 'div[data-component-type="s-search-result"]',
            'TITLE': 'h2.a-size-base-plus',
            'LINK': 'h2 a',
            'IMAGE': 'img.s-image',
            'PRICE_WHOLE': 'span.a-price-whole',
            'PRICE_FRACTION': 'span.a-price-fraction',
            'ORIGINAL_PRICE': 'span.a-price.a-text-price[data-a-strike="true"] span.a-offscreen',
            'RATING': 'span.a-icon-alt',
            'REVIEWS_COUNT': 'span.a-size-base.s-underline-text',
            'PRIME_BADGE': 'i.a-icon-prime',
            'SELLER': 'span.a-size-small.a-color-secondary',  # Often not in search results
            'PAGINATION': 'span.s-pagination-item'
        }
    }

    # Valid domains for image validation
    VALID_IMAGE_DOMAINS = [
        'mlstatic.com',
        'mercadolibre.com',
        'mercadolivre.com.br',
        'mla-s1-p.mlstatic.com',
        'mla-s2-p.mlstatic.com',
        'http2.mlstatic.com'
    ]

    # Image attributes for verification
    IMAGE_ATTRIBUTES = ['src', 'data-src', 'data-lazy', 'data-original', 'data-srcset', 'srcset']
    
    # Crawl4AI settings
    CRAWL4AI_CONFIG = {
        'headless': True,
        'browser_type': 'chromium',
        'verbose': False,
        'wait_for': 'css:.ui-search-results',
        'delay_before_return_html': 5,
        'simulate_user': True,
        'override_navigator': True
    }
    
    # Logging configuration
    LOG_FORMAT = '%(asctime)s - %(levelname)s - %(message)s'
    LOG_LEVEL = 'INFO'
    
    # Create directories if they don't exist
    @classmethod
    def ensure_directories(cls):
        for directory in [cls.OUTPUT_DIR, cls.JSON_OUTPUT_DIR, 
                         cls.EXCEL_OUTPUT_DIR, cls.LOGS_DIR]:
            directory.mkdir(parents=True, exist_ok=True)