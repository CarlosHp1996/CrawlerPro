from typing import List, Optional, Dict, Any
import re
import urllib.parse
from bs4 import BeautifulSoup, Tag
from crawl4ai import AsyncWebCrawler

from src.core.base_crawler import BaseCrawler
from src.core.enums import Platform
from src.core.models import ProductData
from src.exceptions import NetworkException, BlockedException
from src.retry_system import get_retry_manager, NETWORK_RETRY_POLICY
from config import Config


class AmazonCrawler(BaseCrawler):
    """
    Amazon Brasil crawler implementation
    Extracts product data from Amazon search results
    """

    def __init__(self, max_pages: Optional[int] = None, delay_between_pages: Optional[int] = None) -> None:
        max_pages = max_pages if max_pages is not None else Config.MAX_PAGES
        delay_between_pages = delay_between_pages if delay_between_pages is not None else Config.DELAY_BETWEEN_PAGES
        
        super().__init__(max_pages=max_pages, delay_between_pages=delay_between_pages)

    def get_platform(self) -> Platform:
        """Return Amazon platform identifier"""
        return Platform.AMAZON

    async def _fetch_page(self, url: str) -> Optional[str]:
        """
        Fetch page HTML with retry logic
        
        Args:
            url: Page URL to fetch
            
        Returns:
            HTML content or None on failure
        """
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
                self.logger.error(f"Error fetching Amazon page: {str(e)}")
                raise
    
    def _is_blocked(self, html: str) -> bool:
        """
        Check if page is blocked/captcha
        
        Args:
            html: Page HTML content
            
        Returns:
            True if blocking detected
        """
        # Check for common Amazon blocking indicators
        blocking_indicators = [
            'api-services-support@amazon.com',
            'Sorry, we just need to make sure you',
            'Enter the characters you see below'
        ]
        
        return any(indicator in html for indicator in blocking_indicators)

    def build_search_url(self, search_term: str, page: int = 1) -> str:
        """
        Build Amazon search URL
        
        Args:
            search_term: Product to search
            page: Page number (default: 1)
            
        Returns:
            Complete search URL
            
        Examples:
            >>> build_search_url("creatina", 1)
            'https://www.amazon.com.br/s?k=creatina&page=1'
        """
        encoded_term = urllib.parse.quote(search_term)
        base_url = f"https://www.amazon.com.br/s?k={encoded_term}"
        
        if page > 1:
            base_url += f"&page={page}"
        
        return base_url

    async def extract_products(self, html_content: str, page: int = 1) -> List[Dict[str, Any]]:
        """
        Extract product data from HTML as raw dictionaries
        
        Args:
            html_content: HTML from Amazon search page
            page: Page number (for logging)
            
        Returns:
            List of dictionaries with raw product data
        """
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Main container
        container = soup.select_one(Config.SELECTORS['AMAZON']['CONTAINER'])
        
        if not container:
            self.logger.warning(f"Amazon main container not found on page {page}")
            return []
        
        # Find all product cards
        product_elements = container.select(Config.SELECTORS['AMAZON']['PRODUCT_CARD'])
        
        self.logger.info(f"Found {len(product_elements)} Amazon products on page {page}")
        
        # Extract raw data from each product
        products = []
        for position, element in enumerate(product_elements, start=1):
            product_dict = self._extract_product_dict(element, page, position)
            if product_dict:
                products.append(product_dict)
        
        self.logger.info(f"Extracted {len(products)} Amazon products on page {page}")
        return products

    def _extract_product_dict(self, element: Tag, page: int, position: int) -> Optional[Dict[str, Any]]:
        """
        Extract raw product data from BeautifulSoup element
        
        Args:
            element: Product card element
            page: Page number
            position: Position on page (1-indexed)
            
        Returns:
            Dictionary with raw product data or None if critical data missing
        """
        try:
            selectors = Config.SELECTORS['AMAZON']
            
            # ASIN (required)
            asin = element.get('data-asin')
            if not asin:
                return None
            
            # Title (required)
            title_elem = element.select_one(selectors['TITLE'])
            title = title_elem.get_text(strip=True) if title_elem else None
            
            if not title:
                self.logger.warning(f"Product {asin} has no title, skipping")
                return None
            
            # Price
            price_value = None
            price_whole = element.select_one(selectors['PRICE_WHOLE'])
            price_fraction = element.select_one(selectors['PRICE_FRACTION'])
            
            if price_whole and price_fraction:
                # Amazon format: whole="859" fraction="90" -> 859.90
                whole_text = price_whole.get_text(strip=True).replace('.', '').replace(',', '')
                fraction_text = price_fraction.get_text(strip=True)
                # Combine with decimal point and convert directly
                try:
                    price_value = float(f"{whole_text}.{fraction_text}")
                except (ValueError, AttributeError):
                    price_value = None
            else:
                # Try alternative selector for sponsored/different layout products
                price_symbol = element.select_one('span.a-price > span.a-offscreen')
                if price_symbol:
                    price_text = price_symbol.get_text(strip=True)
                    # Format: "R$ 3.998,00" -> convert to float
                    price_text = price_text.replace('R$', '').replace('.', '').replace(',', '.').strip()
                    try:
                        price_value = float(price_text)
                    except (ValueError, AttributeError):
                        self.logger.debug(f"Product {asin} - Could not extract price from alternative selector")
                        price_value = None
            
            # Link
            link_elem = element.select_one(selectors['LINK'])
            link = None
            if link_elem and link_elem.get('href'):
                href = link_elem.get('href')
                # Clean relative URLs
                if href.startswith('/'):
                    link = f"https://www.amazon.com.br{href}"
                else:
                    link = href
                
                # Remove tracking parameters for cleaner URLs
                if '?' in link:
                    link = link.split('?')[0]
            
            # If no link found, try multiple alternative selectors
            if not link:
                # Try 1: Any link with /dp/ (product page)
                alt_link = element.select_one('a[href*="/dp/"]')
                if not alt_link:
                    # Try 2: Link inside h2
                    alt_link = element.select_one('h2 > a')
                if not alt_link:
                    # Try 3: Any a.a-link-normal
                    alt_link = element.select_one('a.a-link-normal')
                
                if alt_link and alt_link.get('href'):
                    href = alt_link.get('href')
                    if href.startswith('/'):
                        link = f"https://www.amazon.com.br{href}"
                    else:
                        link = href
                    if '?' in link:
                        link = link.split('?')[0]
            
            # If link is a sponsored redirect (/sspa/click), build URL from ASIN
            if link and '/sspa/click' in link:
                if asin:
                    link = f"https://www.amazon.com.br/dp/{asin}"
            
            # If still no valid link, build from ASIN as last resort
            if not link and asin:
                link = f"https://www.amazon.com.br/dp/{asin}"
            
            # Image
            img_elem = element.select_one(selectors['IMAGE'])
            image_url = img_elem.get('src') if img_elem else None
            
            # Rating
            rating_value = None
            rating_elem = element.select_one(selectors['RATING'])
            if rating_elem:
                rating_text = rating_elem.get_text(strip=True)
                # Extract first number (e.g., "4,8 de 5 estrelas" -> 4.8)
                match = re.search(r'(\d+[,.]?\d*)', rating_text)
                if match:
                    rating_str = match.group(1).replace(',', '.')
                    try:
                        rating_value = float(rating_str)
                    except ValueError:
                        rating_value = None
            
            # Reviews count
            reviews_count = None
            reviews_elem = element.select_one(selectors['REVIEWS_COUNT'])
            if reviews_elem:
                reviews_text = reviews_elem.get_text(strip=True)
                # Extract numbers (e.g., "(20.154)" or "20,1 mil" -> 20154)
                reviews_text = reviews_text.replace('.', '').replace(',', '')
                match = re.search(r'(\d+)', reviews_text)
                if match:
                    try:
                        reviews_count = int(match.group(1))
                        # Handle "mil" notation (e.g., "20mil" -> 20000)
                        if 'mil' in reviews_text.lower():
                            reviews_count = reviews_count * 1000
                    except ValueError:
                        pass
            
            # Prime badge
            has_prime = bool(element.select_one(selectors['PRIME_BADGE']))
            
            # Original price (if discounted)
            original_price = None
            original_elem = element.select_one(selectors['ORIGINAL_PRICE'])
            if original_elem:
                original_text = original_elem.get_text(strip=True)
                # Amazon format: "R$ 5.599,00" -> remove R$, thousands separator, convert comma to dot
                original_text = original_text.replace('R$', '').replace('.', '').replace(',', '.').strip()
                try:
                    original_price = float(original_text)
                except (ValueError, AttributeError):
                    original_price = None
            
            # Calculate discount percentage
            discount_percentage = None
            if price_value and original_price and original_price > price_value:
                discount_percentage = round(((original_price - price_value) / original_price) * 100, 2)
            
            # Seller - try multiple selectors
            seller = None
            # Try 1: Standard seller selector
            seller_elem = element.select_one(selectors['SELLER'])
            if seller_elem:
                seller_text = seller_elem.get_text(strip=True)
                # Filter out statistics and payment info (not seller names)
                if not any(word in seller_text.lower() for word in ['compras', 'mil', 'passado', 'vendidos', 'pix', 'vista', 'até', 'parcela', 'x de']):
                    seller = seller_text
            
            # Try 2: Look for "vendido por" or "de:" patterns
            if not seller:
                seller_candidates = element.select('span.a-size-base') + element.select('div.a-row span')
                for candidate in seller_candidates:
                    text = candidate.get_text(strip=True)
                    text_lower = text.lower()
                    
                    # Skip statistics, payment info, and common non-seller text
                    skip_words = ['compras', 'mil', 'passado', 'vendidos', 'estrela', 'avaliação', 
                                 'entrega', 'frete', 'pix', 'vista', 'até', 'parcela', 'x de', 'r$']
                    if any(word in text_lower for word in skip_words):
                        continue
                    
                    # Look for "vendido por" or "de:" patterns
                    if any(pattern in text_lower for pattern in ['vendido por', 'de:', 'por:']):
                        seller = text.replace('Vendido por', '').replace('vendido por', '') \
                                   .replace('de:', '').replace('De:', '') \
                                   .replace('por:', '').replace('Por:', '').strip()
                        if seller and len(seller) > 2:
                            break
            
            # If seller is still suspicious text, reset to None
            if seller:
                seller_lower = seller.lower()
                if any(word in seller_lower for word in ['vista', 'pix', 'parcela', 'compras', 'vendidos']):
                    seller = None
            
            # Shipping - try multiple patterns
            shipping = None
            # Check for Prime first
            if element.select_one(selectors['PRIME_BADGE']):
                shipping = "Prime"
            
            if not shipping:
                # Look for shipping-related text in all spans and divs
                shipping_candidates = element.select('span.a-size-base') + \
                                    element.select('span.a-color-base') + \
                                    element.select('div.a-row')
                
                for candidate in shipping_candidates:
                    text = candidate.get_text(strip=True)
                    text_lower = text.lower()
                    
                    # Check for free shipping patterns
                    if any(pattern in text_lower for pattern in ['frete grátis', 'frete gratis', 'entrega grátis', 'entrega gratis']):
                        shipping = "Frete Grátis"
                        break
                    # Check for fast delivery patterns
                    elif any(pattern in text_lower for pattern in ['receba amanhã', 'receba hoje', 'entrega hoje']):
                        shipping = text
                        break
                    # General shipping info (but not seller stats or prices)
                    elif 'frete' in text_lower and len(text) < 100:
                        if not any(word in text_lower for word in ['compras', 'vendidos', 'r$', 'reais']):
                            shipping = text
                            break
            
            # Return as dictionary with string values (prices in centavos)
            return {
                'title': title,
                'price': self._convert_price_to_cents_string(price_value),
                'original_price': self._convert_price_to_cents_string(original_price),
                'discount_percentage': f"{discount_percentage}%" if discount_percentage else "N/A",
                'seller': seller or "N/A",
                'rating': str(rating_value) if rating_value else "N/A",
                'reviews_count': str(reviews_count) if reviews_count else "0",
                'shipping': shipping or "N/A",
                'product_url': link or "N/A",
                'image_url': image_url or "N/A",
                'installments': "N/A",
                'location': "N/A",
                'page_number': page,
                'position_on_page': position
            }
            
        except Exception as e:
            self.logger.error(f"Error extracting Amazon product: {e}", exc_info=True)
            return None

    def _convert_price_to_cents_string(self, price_value: Optional[float]) -> str:
        """
        Converts price to centavos in string format (.NET compatible).

        Processes price converting to centavos as a string (e.g., 479.01 -> "47901")
        for full compatibility with .NET systems that use System.Text.Json.

        Args:
            price_value: Price as float (e.g., 479.01)
        
        Returns:
            str: Price in centavos as string (e.g., "47901") or "N/A" if invalid

        Example:
            >>> converter = AmazonCrawler()
            >>> converter._convert_price_to_cents_string(99.90)
            "9990"
            >>> converter._convert_price_to_cents_string(1299.00)
            "129900"
        
        Note:
            - Multiplies by 100 to convert reais to centavos
            - Returns string to avoid JSON serialization issues
        """
        if price_value is None:
            return "N/A"
        
        try:
            price_cents = int(price_value * 100)
            return str(price_cents)
        except (ValueError, TypeError):
            return "N/A"

    def normalize_product_data(self, raw_product: Dict[str, Any]) -> ProductData:
        """
        Convert raw product dictionary to ProductData
        
        Args:
            raw_product: Dictionary with product data from _extract_product_dict
            
        Returns:
            ProductData object
        """
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

    def get_total_pages(self, html_content: str) -> int:
        """
        Extract total pages from pagination
        
        Args:
            html_content: HTML from search results
            
        Returns:
            Total pages available (default: 1)
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Try pagination selector
            pagination = soup.select_one(Config.SELECTORS['AMAZON'].get('PAGINATION', 'span.s-pagination-item'))
            
            if pagination:
                # Find all page numbers
                page_links = soup.select('span.s-pagination-item:not(.s-pagination-disabled)')
                if page_links:
                    # Get highest page number
                    page_numbers = []
                    for link in page_links:
                        text = link.get_text(strip=True)
                        if text.isdigit():
                            page_numbers.append(int(text))
                    
                    if page_numbers:
                        return max(page_numbers)
            
            # Default: assume at least 1 page exists
            return 1
            
        except Exception as e:
            self.logger.warning(f"Error getting total pages: {e}")
            return 1
