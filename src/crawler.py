import asyncio
import time
import re
from typing import List, Optional, Dict, Any, Union
from urllib.parse import urljoin, quote
from bs4 import BeautifulSoup, Tag
from crawl4ai import AsyncWebCrawler
import logging
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))
from config import Config
from .exceptions import (
    CrawlerBaseException, NetworkException, ParsingException, 
    BlockedException, RateLimitException, ValidationException
)
from .logging_config import configure_logging, get_logger
from .retry_system import (
    with_retry, get_retry_manager, NETWORK_RETRY_POLICY, 
    RATE_LIMIT_RETRY_POLICY, RetryPolicy
)
from .metrics import get_metrics_collector, setup_default_alerts
from .health_monitor import get_adaptive_rate_limiter

# Configure professional logging
configure_logging()
logger = get_logger(__name__)

class MercadoLivreCrawler:
    """
    Specialized crawler for extracting products from Mercado Livre.

    This class implements a robust web scraping system for Mercado Livre,
    supporting multiple product layouts and anti-blocking strategies.
    
    Attributes:
        max_pages (int): Maximum number of pages to process
        delay_between_pages (int): Delay in seconds between processing pages
        base_url (str): Base URL for Mercado Livre

    Example:
        >>> crawler = MercadoLivreCrawler(max_pages=3, delay_between_pages=2)
        >>> result = await crawler.search_products("creatina")
        >>> print(f"Found {result['total_products']} products")
    """
    
    def __init__(self, max_pages: Optional[int] = None, delay_between_pages: Optional[int] = None) -> None:
        """
        Initializes the crawler with custom or default settings.
        
        Args:
            max_pages: Maximum number of pages to process.
                      If None, uses Config.MAX_PAGES (default: 5)
            delay_between_pages: Delay in seconds between pages.
                               If None, uses Config.DELAY_BETWEEN_PAGES (default: 2)
        """
        self.max_pages = max_pages if max_pages is not None else Config.MAX_PAGES
        self.delay_between_pages = delay_between_pages if delay_between_pages is not None else Config.DELAY_BETWEEN_PAGES
        self.base_url = Config.MERCADO_LIVRE_BASE_URL

        # Initialize monitoring systems
        self.metrics_collector = get_metrics_collector()
        self.rate_limiter = get_adaptive_rate_limiter()

        # Set up default alerts
        setup_default_alerts()
        
    async def search_products(self, search_term: str) -> Dict[str, Any]:
        """
        Executes product search on Mercado Livre with automatic retry and robust error handling.

        This method processes multiple pages of results, extracting structured data
        from each product found. It implements automatic retry,
        block detection, and professional logging.

        Args:
            search_term (str): Search term (e.g., "creatina", "iphone 15")
                             Will be automatically URL-encoded

        Returns:
            Dict[str, Any]: Structured dictionary containing:
                - search_term (str): Search term
                - total_products (int): Total products found
                - pages_crawled (int): Number of pages processed
                - timestamp (str): Execution timestamp
                - execution_time (float): Total time in seconds
                - products (List[dict]): List of extracted products
                - success (bool): Indicates if the operation was successful
                - error_message (str, optional): Error message if success=False
                - retry_metrics (dict): Retry system metrics

        Raises:
            CrawlerBaseException: For specific crawler errors
            ValidationException: For invalid parameters

        Example:
            >>> result = await crawler.search_products("notebook gamer")
            >>> if result["success"]:
            ...     for product in result["products"]:
            ...         print(f"{product['title']}: R$ {product['price']}")
        """
        # Validate input
        if not search_term or not search_term.strip():
            raise ValidationException(
                "Search term cannot be empty",
                {"search_term": search_term}
            )
        
        start_time = time.time()
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        retry_manager = get_retry_manager()
        
        try:
            logger.info(f"Starting search for: {search_term}", extra={
                "search_term": search_term,
                "max_pages": self.max_pages,
                "operation": "search_products"
            })
            
            all_products = []
            search_url = f"{self.base_url}/{quote(search_term)}"
            pages_processed = 0
            
            async with AsyncWebCrawler(
                **Config.CRAWL4AI_CONFIG
            ) as crawler:
                
                for page in range(1, self.max_pages + 1):
                    try:
                        # Process page with automatic retry
                        products = await self._process_page_with_retry(
                            crawler, search_url, page, search_term
                        )

                        if products is None:  # Non-retryable error or limit reached
                            continue
                            
                        all_products.extend(products)
                        pages_processed = page

                        logger.info(f"Page {page}: {len(products)} products extracted", extra={
                            "page": page,
                            "products_count": len(products),
                            "total_products": len(all_products),
                            "search_term": search_term
                        })

                        # Log first product for validation
                        if products and page == 1:
                            first_product = products[0]
                            logger.info("First product extracted successfully", extra={
                                "title": first_product.get('title', 'N/A'),
                                "price": first_product.get('price', 'N/A'),
                                "seller": first_product.get('seller', 'N/A'),
                                "search_term": search_term
                            })

                        # If no products were found, stop the search
                        if not products:
                            logger.info(f"No products found on page {page}. Stopping search.", extra={
                                "page": page,
                                "search_term": search_term
                            })
                            break

                        # Delay between pages
                        if page < self.max_pages:
                            await asyncio.sleep(self.delay_between_pages)
                            
                    except CrawlerBaseException as e:
                        logger.error(f"Specific crawler error on page {page}", extra={
                            "page": page,
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                            "search_term": search_term,
                            "context": e.context
                        })

                        # If blocked, stop search
                        if isinstance(e, BlockedException):
                            logger.warning("Search interrupted due to blocking", extra={
                                "search_term": search_term,
                                "pages_processed": pages_processed
                            })
                            break
                        continue
                        
                    except Exception as e:
                        logger.error(f"Unexpected error on page {page}", extra={
                            "page": page,
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                            "search_term": search_term
                        })
                        continue
            
            execution_time = time.time() - start_time
            retry_metrics = retry_manager.get_metrics()

            # Collect final metrics
            final_metrics = self.metrics_collector.get_current_metrics()
            rate_limiter_status = self.rate_limiter.get_current_limits()

            logger.info("Search completed successfully", extra={
                "search_term": search_term,
                "total_products": len(all_products),
                "pages_crawled": pages_processed,
                "execution_time": execution_time,
                "retry_metrics": retry_metrics,
                "final_metrics": final_metrics
            })
            
            return {
                "search_term": search_term,
                "total_products": len(all_products),
                "pages_crawled": pages_processed,
                "timestamp": timestamp,
                "execution_time": round(execution_time, 2),
                "products": all_products,
                "success": True,
                "retry_metrics": retry_metrics,
                "performance_metrics": final_metrics,
                "rate_limiter_status": rate_limiter_status
            }
            
        except CrawlerBaseException as e:
            execution_time = time.time() - start_time
            logger.error("Specific crawler error", extra={
                "search_term": search_term,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "execution_time": execution_time,
                "context": e.context
            })
            
            return {
                "search_term": search_term,
                "total_products": 0,
                "pages_crawled": 0,
                "timestamp": timestamp,
                "execution_time": round(execution_time, 2),
                "products": [],
                "success": False,
                "error_message": str(e),
                "error_type": type(e).__name__,
                "retry_metrics": get_retry_manager().get_metrics()
            }
            
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error("Unexpected error in crawler", extra={
                "search_term": search_term,
                "error_type": type(e).__name__,
                "error_message": str(e),
                "execution_time": execution_time
            })
            
            return {
                "search_term": search_term,
                "total_products": 0,
                "pages_crawled": 0,
                "timestamp": timestamp,
                "execution_time": round(execution_time, 2),
                "products": [],
                "success": False,
                "error_message": str(e),
                "error_type": type(e).__name__,
                "retry_metrics": get_retry_manager().get_metrics()
            }
    
    async def _process_page_with_retry(self, 
                                     crawler: AsyncWebCrawler, 
                                     search_url: str, 
                                     page: int, 
                                     search_term: str) -> Optional[List[Dict[str, Any]]]:
        """
        Process a specific page with automatic retry and error handling.
        
        Args:
            crawler: Instance of AsyncWebCrawler
            search_url: Base search URL
            page: Page number (1-indexed)
            search_term: Original search term

        Returns:
            List of extracted products or None in case of non-retryable error

        Raises:
            NetworkException: For network errors
            BlockedException: For blocking detection
            RateLimitException: For rate limiting
            ParsingException: For parsing errors
        """
        # Build page URL
        if page == 1:
            current_url = search_url
        else:
            offset = (page - 1) * 50 + 1
            current_url = f"{search_url}_Desde_{offset}_NoIndex_True"

        logger.debug(f"Processing page {page}: {current_url}", extra={
            "page": page,
            "url": current_url,
            "search_term": search_term
        })
        
        try:
            # Apply adaptive rate limiting
            await self.rate_limiter.acquire()
            
            try:
                # Track request with metrics
                async with self.metrics_collector.track_request(current_url) as tracker:
                    # Crawl with automatic retry
                    result = await get_retry_manager().execute_with_retry(
                        crawler.arun,
                        url=current_url,
                        policy=NETWORK_RETRY_POLICY,
                        context={
                            "page": page,
                            "search_term": search_term,
                            "url": current_url
                        }
                    )

                    # Mark success and set response size
                    if result.success:
                        tracker.mark_success()
                        tracker.set_response_size(len(result.html) if result.html else 0)
                    else:
                        tracker.mark_error("crawl_failed")
                        
            except Exception as e:
                # Release rate limiter in case of error
                await self.rate_limiter.release(False, 0)
                raise
            else:
                # Release rate limiter on success
                response_time = 1000  # Estimate response time (crawler doesn't return this)
                await self.rate_limiter.release(result.success, response_time)
            
            # Check crawling success
            if not result.success:
                error_msg = result.error_message or "Unknown crawling error"
                
                # Detect specific error types
                if "403" in error_msg or "blocked" in error_msg.lower():
                    raise BlockedException(
                        f"Access blocked on page {page}",
                        {"page": page, "url": current_url, "response": error_msg}
                    )
                elif "429" in error_msg or "rate" in error_msg.lower():
                    raise RateLimitException(
                        f"Rate limit reached on page {page}",
                        {"page": page, "url": current_url, "response": error_msg}
                    )
                else:
                    raise NetworkException(
                        f"Network error on page {page}: {error_msg}",
                        {"page": page, "url": current_url, "response": error_msg}
                    )
            
            # Extract products from page
            products = self._extract_products_from_html(result.html, page)
            
            logger.debug(f"Page {page} processed successfully: {len(products)} products", extra={
                "page": page,
                "products_count": len(products),
                "search_term": search_term
            })
            
            return products
            
        except CrawlerBaseException:
            # Re-raise custom exceptions
            raise
        except Exception as e:
            # Convert generic exceptions to NetworkException
            logger.warning(f"Converting generic exception to NetworkException: {type(e).__name__}", extra={
                "page": page,
                "original_error": str(e),
                "search_term": search_term
            })
            raise NetworkException(
                f"Unexpected error on page {page}: {str(e)}",
                {"page": page, "url": current_url, "original_error": type(e).__name__}
            )
    
    def _extract_products_from_html(self, html: str, page_number: int) -> List[Dict[str, Any]]:
        """
        Extrai dados estruturados de produtos a partir de HTML da página com error handling robusto.
        
        Implementa detecção automática de layout (Poly-Card vs Classic) e
        processa todos os containers de produto encontrados na página.
        
        Args:
            html (str): HTML completo da página de resultados do Mercado Livre
            page_number (int): Número da página atual para logging e metadata
        
        Returns:
            List[Dict[str, Any]]: Lista de dicionários com dados dos produtos.
                                 Cada produto contém campos como title, price,
                                 image_url, seller, etc.
        
        Raises:
            ParsingException: Para erros críticos de parsing
            ValidationException: Para HTML inválido ou vazio
        
        Note:
            - Prioriza layout Poly-Card (mais moderno) sobre layout Classic
            - Registra estatísticas de extração via logger
            - Continua processamento mesmo com falha em produtos individuais
        """
        # Validar entrada
        if not html or not html.strip():
            raise ValidationException(
                f"HTML vazio ou inválido na página {page_number}",
                {"page": page_number, "html_length": len(html) if html else 0}
            )
        
        products = []
        
        try:
            soup = BeautifulSoup(html, 'html.parser')
        except Exception as e:
            raise ParsingException(
                f"Erro ao fazer parsing do HTML na página {page_number}",
                {"page": page_number, "html_length": len(html), "parser_error": str(e)}
            )
        
        # Detect layout based on debug data
        # Priority: poly-card > ui-search-layout__item > ui-search-result__wrapper
        
        # Option 1: Poly-Card Layout (more modern)
        containers = soup.find_all('li', class_='ui-search-layout__item')
        layout_type = "poly-card"
        
        if not containers:
            # Fallback: Classic layout
            containers = soup.find_all('div', class_='ui-search-result__wrapper')
            layout_type = "classic"
        
        logger.info(f"Page {page_number}: Layout detected: {layout_type}")
        logger.info(f"Page {page_number}: {len(containers)} containers found")
        
        successful_extractions = 0
        failed_extractions = 0
        
        for index, container in enumerate(containers, 1):
            try:
                if layout_type == "poly-card":
                    product = self._extract_poly_card_product(container, page_number, index)
                else:
                    product = self._extract_classic_product(container, page_number, index)
                
                if product:
                    products.append(product)
                    successful_extractions += 1
                else:
                    failed_extractions += 1
                    logger.debug(f"Product {index} returned empty data", extra={
                        "page": page_number,
                        "product_index": index,
                        "layout_type": layout_type
                    })
                    
            except ParsingException as e:
                failed_extractions += 1
                logger.warning(f"Parsing error on product {index}", extra={
                    "page": page_number,
                    "product_index": index,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "context": e.context
                })
                continue
                
            except Exception as e:
                failed_extractions += 1
                logger.warning(f"Unexpected error extracting product {index}", extra={
                    "page": page_number,
                    "product_index": index,
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                })
                continue
        
        # Log extraction statistics
        logger.info(f"Extraction completed on page {page_number}", extra={
            "page": page_number,
            "layout_type": layout_type,
            "containers_found": len(containers),
            "successful_extractions": successful_extractions,
            "failed_extractions": failed_extractions,
            "success_rate": round(successful_extractions / len(containers) * 100, 2) if containers else 0
        })
        
        # If no products were successfully extracted, may indicate layout change
        if containers and successful_extractions == 0:
            logger.warning(f"No products successfully extracted on page {page_number} - possible layout change", extra={
                "page": page_number,
                "layout_type": layout_type,
                "containers_found": len(containers),
                "failed_extractions": failed_extractions
            })
                
        return products

    def _extract_title(self, soup_container: BeautifulSoup, layout_type: str = "poly-card") -> str:
        """
        Extracts product title using layout-specific selectors.
        
        Args:
            soup_container (BeautifulSoup): Product HTML container
            layout_type (str): Layout type ("poly-card" or "classic")
        
        Returns:
            str: Product title or "N/A" if not found
        """
        layout_key = "POLY_CARD" if layout_type == "poly-card" else "CLASSIC"
        selectors = Config.SELECTORS[layout_key]['title']
        return self._extract_text_with_selectors(soup_container, selectors)
    
    def _extract_price_data(self, soup_container: BeautifulSoup, layout_type: str = "poly-card") -> Dict[str, str]:
        """
        Extracts complete product price data.
        
        Args:
            soup_container (BeautifulSoup): Product HTML container
            layout_type (str): Layout type ("poly-card" or "classic")
        
        Returns:
            Dict[str, str]: Dictionary containing:
                - price: Current price in cents as string
                - original_price: Original price (before discount) or "N/A"
                - discount_percentage: Discount percentage or "N/A"
        
        Note:
            Prices are converted to cents and returned as string
            for compatibility with .NET systems expecting this format.
        """
        layout_key = "POLY_CARD" if layout_type == "poly-card" else "CLASSIC"
        selectors = Config.SELECTORS[layout_key]
        
        price_raw = self._extract_text_with_selectors(soup_container, selectors['price_current'])
        price = self._convert_price_to_cents_string(price_raw)
        original_price = self._extract_text_with_selectors(soup_container, selectors['price_original'])
        discount = self._extract_text_with_selectors(soup_container, selectors['discount'])
        
        return {
            "price": price,
            "original_price": original_price,
            "discount_percentage": discount
        }

    def _extract_poly_card_product(self, container: Tag, page_number: int, position: int) -> Optional[Dict[str, Any]]:
        """
        Extracts complete product data using modern Poly-Card layout.
        
        The Poly-Card layout is Mercado Livre's newest format, with richer
        structure and additional fields like ratings, shipping, location, etc.
        
        Args:
            container (Tag): Product container HTML element
            page_number (int): Current page number
            position (int): Product position on page (1-indexed)
        
        Returns:
            Optional[Dict[str, Any]]: Structured product dictionary or None if error.
                Contains all available fields: title, price, seller, rating,
                reviews_count, shipping, image_url, product_url, installments,
                location, plus metadata (page_number, position_on_page).
        
        Raises:
            Exception: Caught and logged, returns None to continue processing
        """
        try:
            soup_container = BeautifulSoup(str(container), 'html.parser')
            
            # Title
            title = self._extract_title(soup_container, "poly-card")
            
            # Use centralized selectors
            selectors = Config.SELECTORS['POLY_CARD']
            
            # Product URL
            product_url = self._extract_link_with_selectors(soup_container, selectors['product_link'])
            
            # Prices
            price_data = self._extract_price_data(soup_container, "poly-card")
            
            # Seller
            seller = self._extract_text_with_selectors(soup_container, selectors['seller'])
            
            # Rating
            rating = self._extract_text_with_selectors(soup_container, selectors['rating'])
            
            # Review count
            reviews_count = self._extract_text_with_selectors(soup_container, selectors['reviews_count'])
            
            # Shipping
            shipping = self._extract_text_with_selectors(soup_container, selectors['shipping'])
            
            # Image
            image_url = self._extract_image_with_selectors(soup_container, selectors['image'])
            
            # Installments
            installments = self._extract_text_with_selectors(soup_container, selectors['installments'])
            
            # Location
            location = self._extract_text_with_selectors(soup_container, selectors['location'])
            
            return {
                "title": title,
                "price": price_data["price"],
                "original_price": price_data["original_price"],
                "discount_percentage": price_data["discount_percentage"],
                "seller": seller,
                "rating": rating,
                "reviews_count": reviews_count,
                "shipping": shipping,
                "product_url": product_url,
                "image_url": image_url,
                "installments": installments,
                "location": location,
                "page_number": page_number,
                "position_on_page": position
            }
            
        except Exception as e:
            logger.warning(f"Error extracting poly-card product: {str(e)}")
            return None
    
    def _extract_classic_product(self, container: Tag, page_number: int, position: int) -> Optional[Dict[str, Any]]:
        """
        Extracts basic product data using Classic layout (fallback).
        
        Layout used when Poly-Card is not detected. Offers more limited
        fields but maintains compatibility with older page versions.
        
        Args:
            container (Tag): Product container HTML element
            page_number (int): Current page number
            position (int): Product position on page (1-indexed)
        
        Returns:
            Optional[Dict[str, Any]]: Basic product dictionary or None if error.
                Limited available fields: title, price, product_url, image_url,
                with other fields filled as "N/A".
        """
        try:
            soup_container = BeautifulSoup(str(container), 'html.parser')
            
            # Use centralized selectors
            selectors = Config.SELECTORS['CLASSIC']
            
            # Title
            title = self._extract_title(soup_container, "classic")
            
            # Product URL
            product_url = self._extract_link_with_selectors(soup_container, selectors['product_link'])
            
            # Price
            price_data = self._extract_price_data(soup_container, "classic")
            
            # Image
            image_url = self._extract_image_with_selectors(soup_container, selectors['image'])
            
            return {
                "title": title,
                "price": price_data["price"],
                "original_price": "N/A",
                "discount_percentage": "N/A",
                "seller": "N/A",
                "rating": "N/A",
                "reviews_count": "N/A",
                "shipping": "N/A",
                "product_url": product_url,
                "image_url": image_url,
                "installments": "N/A",
                "location": "N/A",
                "page_number": page_number,
                "position_on_page": position
            }
            
        except Exception as e:
            logger.warning(f"Error extracting classic product: {str(e)}")
            return None
    
    def _extract_text_with_selectors(self, soup_container: BeautifulSoup, selectors: List[str]) -> str:
        """
        Extracts text using fallback strategy with multiple CSS selectors.
        
        Tries selectors in priority order until valid text is found.
        Robust strategy to handle changes in page HTML.
        
        Args:
            soup_container (BeautifulSoup): HTML container for search
            selectors (List[str]): List of CSS selectors in priority order
        
        Returns:
            str: Extracted text (stripped) or "N/A" if no selector works
        
        Example:
            >>> selectors = ['.title-new', '.title-old', 'h2']
            >>> text = crawler._extract_text_with_selectors(soup, selectors)
        """
        for selector in selectors:
            try:
                element = soup_container.select_one(selector)
                if element:
                    text = element.get_text(strip=True)
                    if text and len(text.strip()) > 0:
                        return text
            except Exception:
                continue
        return "N/A"
    
    def _extract_link_with_selectors(self, soup_container: BeautifulSoup, selectors: List[str]) -> str:
        """
        Extracts URL using fallback strategy with multiple CSS selectors.
        
        Searches for elements with valid href attribute, prioritizing complete
        URLs that start with 'http' (avoids relative links or fragments).
        
        Args:
            soup_container (BeautifulSoup): HTML container for search
            selectors (List[str]): List of CSS selectors in priority order
        
        Returns:
            str: Complete URL found or "N/A" if no valid link
        
        Note:
            Validates that href exists and starts with 'http' before returning
        """
        for selector in selectors:
            try:
                element = soup_container.select_one(selector)
                if element and element.get('href'):
                    href = element['href']
                    if href.startswith('http'):
                        return href
            except Exception:
                continue
        return "N/A"
    
    def _extract_image_with_selectors(self, soup_container: BeautifulSoup, selectors: List[str]) -> str:
        """
        Extracts image URL using robust multi-selector and multi-attribute strategy.
        
        Implements sophisticated algorithm that:
        1. Tries multiple CSS selectors in priority order
        2. For each found element, tests various image attributes
        3. Processes srcsets extracting the first valid URL  
        4. Validates URLs using Mercado Livre domains
        5. Converts to high quality (2X) when possible
        
        Args:
            soup_container (BeautifulSoup): HTML container for search
            selectors (List[str]): List of CSS selectors in priority order
                                  (configured in Config.SELECTORS)
        
        Returns:
            str: Valid image URL found or "N/A" if failed
        
        Note:
            - Tests only the first 3 elements of each selector (performance)
            - Supports attributes: src, data-src, data-lazy, data-original, srcset, etc.
            - Converts _V_ URLs to _2X_ (high quality) automatically
        """
        
        for i, selector in enumerate(selectors, 1):
            try:
                elements = soup_container.select(selector)
                
                if elements:
                    for j, element in enumerate(elements[:3], 1):  # Test only the first 3
                        
                        # Try multiple image attributes
                        for attr in Config.IMAGE_ATTRIBUTES:
                            src = element.get(attr)
                            if src:
                                
                                # If srcset, get the first URL
                                if attr in ['srcset', 'data-srcset']:
                                    src = src.split(',')[0].split(' ')[0]
                                
                                # Validate if it's a valid URL
                                if self._is_valid_image_url(src):
                                    # Try to convert to 2X version (high quality)
                                    if 'mlstatic.com' in src and '_V_' in src and not '_2X_' in src:
                                        src = src.replace('_V_', '_2X_')
                                    
                                    return src
                
            except Exception as e:
                continue
        
        return "N/A"
    
    def _is_valid_image_url(self, url: str) -> bool:
        """
        Validates if URL belongs to a valid image from Mercado Livre domains.
        
        Implements strict validation including:
        - Minimum length verification
        - Protocol normalization (adds https: if needed)
        - HTTP/HTTPS protocol validation
        - Verification against valid ML domain list
        
        Args:
            url (str): Image URL for validation
        
        Returns:
            bool: True if URL is valid and belongs to Mercado Livre, False otherwise
        
        Note:
            Valid domains include: mlstatic.com, mercadolivre.com.br, etc.
            (configured in Config.VALID_IMAGE_DOMAINS)
        """
        if not url or len(url.strip()) < 10:
            return False
        
        url = url.strip()
        
        # Add protocol if necessary
        if url.startswith('//'):
            url = 'https:' + url

        # Check if it starts with http
        if not url.startswith('http'):
            return False

        # Verify valid domains
        return any(domain in url for domain in Config.VALID_IMAGE_DOMAINS)

    def _convert_price_to_cents_string(self, price_text: str) -> str:
        """
       Converts Brazilian price to centavos in string format (.NET compatible).

        Processes Brazilian price format (e.g., "R$ 1.234,56") converting
        to centavos as a string (e.g., "123456") for full compatibility
        with .NET systems that use System.Text.Json with camelCase policy.

        Args:
            price_text (str): Price in Brazilian format (ex: "R$ 1.234,56", "999,99")
        
        Returns:
            str: Price in centavos as a string (ex: "123456") or "N/A" if invalid

        Example:
            >>> converter = MercadoLivreCrawler()
            >>> converter._convert_price_to_cents_string("R$ 99,90")
            "9990"
            >>> converter._convert_price_to_cents_string("1.299,00")  
            "129900"
        
        Note:
            - Removes periods (thousands separators) and converts commas to periods
            - Multiplies by 100 to convert reais to centavos
            - Returns string to avoid JSON serialization issues
        """
        if not price_text or price_text == "N/A":
            return "N/A"
        
        try:
            # Remove periods (thousands separators) and keep comma (decimal)
            price_text = price_text.replace('.', '').replace(',', '.')

            # Extract only numbers and decimal point
            price_clean = re.sub(r'[^\d.]', '', price_text)
            
            if not price_clean:
                return "N/A"

            # Convert to float and then to cents
            price_float = float(price_clean)
            price_cents = int(price_float * 100)

            # Return as string
            return str(price_cents)
            
        except (ValueError, AttributeError):
            return "N/A"

# TEST FUNCTION
async def test_fixed_crawler() -> Dict[str, Any]:
    """
    Test and demonstration function for the refactored crawler.

    Executes a test search for "creatina" with only one page,
    displaying detailed statistics about the data extraction.
    Useful for validation after code changes.

    Returns:
        Dict[str, Any]: Complete search result for analysis

    Example:
        >>> result = await test_fixed_crawler()
        >>> print(f"Taxa de sucesso: {len([p for p in result['products'] if p['title'] != 'N/A'])} / {len(result['products'])}")
    """
    import logging

    # Configure logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    crawler = MercadoLivreCrawler(max_pages=1, delay_between_pages=1)
    result = await crawler.search_products("creatina")
    
    print("\n" + "="*80)
    print("🧪 TEST RESULT")
    print("="*80)
    print(f"Term: {result['search_term']}")
    print(f"Total products: {result['total_products']}")
    print(f"Pages crawled: {result['pages_crawled']}")
    print(f"Execution time: {result['execution_time']}s")
    print(f"Success: {result['success']}")

    if result['products']:
        print(f"\n🎯 FIRST PRODUCT:")
        first = result['products'][0]
        for field, value in first.items():
            emoji = "✅" if value != "N/A" else "❌"
            print(f"  {emoji} {field}: {value}")

    if result['products']:
        fields_ok = sum(1 for v in result['products'][0].values() if v != "N/A")
        total_fields = len(result['products'][0])
        images_found = sum(1 for p in result['products'] if p.get('image_url', 'N/A') != 'N/A')
        total_products = len(result['products'])

        print(f"\n📊 STATISTICS:")
        print(f"  Filled fields: {fields_ok}/{total_fields} ({fields_ok/total_fields*100:.1f}%)")
        print(f"  Products with image: {images_found}/{total_products} ({images_found/total_products*100:.1f}%)")

    return result

if __name__ == "__main__":
    asyncio.run(test_fixed_crawler())