import asyncio
import time
import re
from typing import List, Optional, Dict, Any, Union
from urllib.parse import urljoin, quote
from bs4 import BeautifulSoup, Tag
from crawl4ai import AsyncWebCrawler
from datetime import datetime

from config import Config
from src.core.base_crawler import BaseCrawler
from src.core.enums import Platform
from src.core.models import ProductData, CrawlerResult
from src.exceptions import (
    CrawlerBaseException, NetworkException, ParsingException, 
    BlockedException, RateLimitException, ValidationException
)
from src.retry_system import (
    with_retry, get_retry_manager, NETWORK_RETRY_POLICY, 
    RATE_LIMIT_RETRY_POLICY, RetryPolicy
)


class MercadoLivreCrawler(BaseCrawler):
    def __init__(self, max_pages: Optional[int] = None, delay_between_pages: Optional[int] = None) -> None:
        max_pages = max_pages if max_pages is not None else Config.MAX_PAGES
        delay_between_pages = delay_between_pages if delay_between_pages is not None else Config.DELAY_BETWEEN_PAGES
        
        super().__init__(max_pages=max_pages, delay_between_pages=delay_between_pages)
        
        self.base_url = Config.MERCADO_LIVRE_BASE_URL
    
    def get_platform(self) -> Platform:
        return Platform.MERCADOLIVRE
    
    def build_search_url(self, search_term: str, page: int) -> str:
        encoded_term = quote(search_term)
        search_url = f"{self.base_url}/{encoded_term}"
        
        if page == 1:
            return search_url
        else:
            offset = (page - 1) * 50 + 1
            return f"{search_url}_Desde_{offset}_NoIndex_True"
    
    async def extract_products(self, html: str, page: int) -> List[Dict[str, Any]]:
        return self._extract_products_from_html(html, page)
    
    def normalize_product_data(self, raw_product: Dict[str, Any]) -> ProductData:
        return ProductData(
            title=raw_product.get("title", "N/A"),
            price=raw_product.get("price", "N/A"),
            original_price=raw_product.get("original_price", "N/A"),
            discount_percentage=raw_product.get("discount_percentage", "N/A"),
            seller=raw_product.get("seller", "N/A"),
            rating=raw_product.get("rating", "N/A"),
            reviews_count=raw_product.get("reviews_count", "N/A"),
            shipping=raw_product.get("shipping", "N/A"),
            product_url=raw_product.get("product_url", "N/A"),
            image_url=raw_product.get("image_url", "N/A"),
            installments=raw_product.get("installments", "N/A"),
            location=raw_product.get("location", "N/A"),
            page_number=raw_product.get("page_number", 1),
            position_on_page=raw_product.get("position_on_page", 1)
        )
    
    async def _fetch_page(self, url: str) -> Optional[str]:
        async with AsyncWebCrawler(**Config.CRAWL4AI_CONFIG) as crawler:
            await self.rate_limiter.acquire()
            
            try:
                result = await get_retry_manager().execute_with_retry(
                    crawler.arun,
                    url=url,
                    policy=NETWORK_RETRY_POLICY
                )
                
                if not result or not result.html:
                    raise NetworkException(f"No content received from {url}")
                
                if self._is_blocked(result.html):
                    raise BlockedException("Blocking detected")
                
                return result.html
                
            except Exception as e:
                self.logger.error(f"Error fetching page: {str(e)}")
                raise
    
    def _is_blocked(self, html: str) -> bool:
        return False
    
    async def _process_page_with_retry(self, page: int, search_term: str) -> Optional[List[Dict[str, Any]]]:
        current_url = self.build_search_url(search_term, page)
        
        self.logger.debug(f"Processing page {page}: {current_url}", extra={
            "page": page,
            "url": current_url,
            "search_term": search_term
        })
        
        try:
            html = await self._fetch_page(current_url)
            products = self._extract_products_from_html(html, page)
            
            self.logger.debug(f"Page {page} processed successfully: {len(products)} products", extra={
                "page": page,
                "products_count": len(products),
                "search_term": search_term
            })
            
            return products
            
        except CrawlerBaseException:
            raise
        except Exception as e:
            self.logger.warning(f"Converting generic exception to NetworkException: {type(e).__name__}", extra={
                "page": page,
                "original_error": str(e),
                "search_term": search_term
            })
            raise NetworkException(
                f"Unexpected error on page {page}: {str(e)}",
                {"page": page, "url": current_url, "original_error": type(e).__name__}
            )
    
    def _extract_products_from_html(self, html: str, page_number: int) -> List[Dict[str, Any]]:
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
        
        self.logger.info(f"Page {page_number}: Layout detected: {layout_type}")
        self.logger.info(f"Page {page_number}: {len(containers)} containers found")
        
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
                    self.logger.debug(f"Product {index} returned empty data", extra={
                        "page": page_number,
                        "product_index": index,
                        "layout_type": layout_type
                    })
                    
            except ParsingException as e:
                failed_extractions += 1
                self.logger.warning(f"Parsing error on product {index}", extra={
                    "page": page_number,
                    "product_index": index,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "context": e.context
                })
                continue
                
            except Exception as e:
                failed_extractions += 1
                self.logger.warning(f"Unexpected error extracting product {index}", extra={
                    "page": page_number,
                    "product_index": index,
                    "error_type": type(e).__name__,
                    "error_message": str(e)
                })
                continue
        
        # Log extraction statistics
        self.logger.info(f"Extraction completed on page {page_number}", extra={
            "page": page_number,
            "layout_type": layout_type,
            "containers_found": len(containers),
            "successful_extractions": successful_extractions,
            "failed_extractions": failed_extractions,
            "success_rate": round(successful_extractions / len(containers) * 100, 2) if containers else 0
        })
        
        # If no products were successfully extracted, may indicate layout change
        if containers and successful_extractions == 0:
            self.logger.warning(f"No products successfully extracted on page {page_number} - possible layout change", extra={
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
        original_price_raw = self._extract_text_with_selectors(soup_container, selectors['price_original'])
        original_price = self._convert_price_to_cents_string(original_price_raw)
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
            self.logger.warning(f"Error extracting poly-card product: {str(e)}")
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
            self.logger.warning(f"Error extracting classic product: {str(e)}")
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
