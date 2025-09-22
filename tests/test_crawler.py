"""
Testes completos para o MercadoLivreCrawler
"""
import pytest
import asyncio
import sys
from pathlib import Path
from bs4 import BeautifulSoup
from unittest.mock import Mock, patch, MagicMock

# pytest-asyncio configuration
pytest_plugins = ('pytest_asyncio',)

# Add src to path for import
sys.path.append(str(Path(__file__).parent.parent / "src"))
sys.path.append(str(Path(__file__).parent.parent))

from crawler import MercadoLivreCrawler
from config import Config


class TestMercadoLivreCrawler:
    """Tests for the MercadoLivreCrawler class"""
    
    def setup_method(self):
        """Setup for each test"""
        self.crawler = MercadoLivreCrawler(max_pages=1, delay_between_pages=0)
    
    def test_init_with_config(self):
        """Tests initialization of the crawler with Config"""
        crawler = MercadoLivreCrawler()
        assert crawler.max_pages == Config.MAX_PAGES
        assert crawler.delay_between_pages == Config.DELAY_BETWEEN_PAGES
        assert crawler.base_url == Config.MERCADO_LIVRE_BASE_URL
    
    def test_init_with_custom_params(self):
        """Tests initialization with custom parameters"""
        assert self.crawler.max_pages == 1
        assert self.crawler.delay_between_pages == 0
        assert self.crawler.base_url == Config.MERCADO_LIVRE_BASE_URL


class TestPriceConversion:
    """Tests for price conversion"""
    
    def setup_method(self):
        """Setup for each test"""
        self.crawler = MercadoLivreCrawler(max_pages=1, delay_between_pages=0)
    
    def test_convert_price_to_centavos_string_basic(self):
        """Tests basic price conversion to centavos"""
        assert self.crawler._convert_price_to_centavos_string("R$ 100,50") == "10050"
        assert self.crawler._convert_price_to_centavos_string("1.500,00") == "150000"
        assert self.crawler._convert_price_to_centavos_string("N/A") == "N/A"
        assert self.crawler._convert_price_to_centavos_string("") == "N/A"

        # Tests for Brazilian format
        assert self.crawler._convert_price_to_centavos_string("R$ 1.234,56") == "123456"
        assert self.crawler._convert_price_to_centavos_string("999,99") == "99999"
        
    def test_convert_price_edge_cases(self):
        """Tests edge cases for price conversion"""
        assert self.crawler._convert_price_to_centavos_string("0,01") == "1"
        assert self.crawler._convert_price_to_centavos_string("0,00") == "0"
        assert self.crawler._convert_price_to_centavos_string("10.000,00") == "1000000"
        assert self.crawler._convert_price_to_centavos_string("texto inválido") == "N/A"


class TestImageValidation:
    """Tests for image URL validation"""
    
    def setup_method(self):
        """Setup for each test"""
        self.crawler = MercadoLivreCrawler()
    
    def test_is_valid_image_url_valid_cases(self):
        """Tests valid image URLs"""
        valid_urls = [
            "https://http2.mlstatic.com/image.jpg",
            "https://mlstatic.com/image.png", 
            "//mlstatic.com/image.gif",
            "https://mla-s1-p.mlstatic.com/product.webp",
            "https://mercadolivre.com.br/assets/image.jpg"
        ]
        for url in valid_urls:
            assert self.crawler._is_valid_image_url(url), f"Valid URL rejected: {url}"
    
    def test_is_valid_image_url_invalid_cases(self):
        """Tests invalid image URLs"""
        invalid_urls = [
            "",
            "   ",
            "invalid",
            "http://google.com/image.jpg",
            "ftp://test.com/image.png",
            None,
            "short"
        ]
        for url in invalid_urls:
            assert not self.crawler._is_valid_image_url(url), f"Invalid URL accepted: {url}"


class TestDataExtraction:
    """Tests for data extraction functions"""

    def setup_method(self):
        """Setup for each test"""
        self.crawler = MercadoLivreCrawler()

        # Sample HTML for tests
        self.poly_card_html = """
        <li class="ui-search-layout__item">
            <h2 class="poly-component__title">
                <a href="https://produto.mercadolivre.com.br/MLB123">Creatina Monohidratada</a>
            </h2>
            <div class="poly-price__current">
                <span class="andes-money-amount__fraction">89</span>
            </div>
            <div class="poly-component__seller">Vendedor Oficial</div>
            <img src="https://http2.mlstatic.com/D_NQ_NP_123-MLA123_V.webp" alt="produto">
            <div class="poly-component__shipping">Frete grátis</div>
        </li>
        """
        
        self.classic_html = """
        <div class="ui-search-result__wrapper">
            <h2 class="ui-search-item__title">Produto Teste</h2>
            <span class="andes-money-amount__fraction">150</span>
            <a href="https://produto.mercadolivre.com.br/MLB456">Link do produto</a>
            <img src="https://mlstatic.com/image456.jpg" alt="produto">
        </div>
        """
    
    def test_extract_text_with_selectors(self):
        """Test text extraction with selectors"""
        soup = BeautifulSoup(self.poly_card_html, 'html.parser')

        # Test with valid selector
        result = self.crawler._extract_text_with_selectors(soup, ['.poly-component__title'])
        assert "Creatina Monohidratada" in result

        # Test with invalid selectors
        result = self.crawler._extract_text_with_selectors(soup, ['.nao-existe'])
        assert result == "N/A"

        # Test with multiple selectors (first invalid, second valid)
        result = self.crawler._extract_text_with_selectors(soup, ['.nao-existe', '.poly-component__title'])
        assert "Creatina Monohidratada" in result
    
    def test_extract_link_with_selectors(self):
        """Test link extraction with selectors"""
        soup = BeautifulSoup(self.poly_card_html, 'html.parser')

        # Test with valid selector
        result = self.crawler._extract_link_with_selectors(soup, ['a[href]'])
        assert result.startswith('https://produto.mercadolivre.com.br')

        # Test with invalid selector
        result = self.crawler._extract_link_with_selectors(soup, ['.nao-existe'])
        assert result == "N/A"
    
    def test_extract_title_poly_card(self):
        """Test title extraction in poly-card layout"""
        soup = BeautifulSoup(self.poly_card_html, 'html.parser')
        result = self.crawler._extract_title(soup, "poly-card")
        assert "Creatina Monohidratada" in result
    
    def test_extract_title_classic(self):
        """Test title extraction in classic layout"""
        soup = BeautifulSoup(self.classic_html, 'html.parser')
        result = self.crawler._extract_title(soup, "classic")
        assert "Produto Teste" in result
    
    def test_extract_price_data_poly_card(self):
        """Test price data extraction in poly-card layout"""
        soup = BeautifulSoup(self.poly_card_html, 'html.parser')
        result = self.crawler._extract_price_data(soup, "poly-card")
        
        assert "price" in result
        assert "original_price" in result
        assert "discount_percentage" in result
        assert result["price"] == "8900"  # 89.00 * 100
    
    def test_extract_price_data_classic(self):
        """Test price data extraction in classic layout"""
        soup = BeautifulSoup(self.classic_html, 'html.parser')
        result = self.crawler._extract_price_data(soup, "classic")
        
        assert "price" in result
        assert result["price"] == "15000"  # 150.00 * 100


class TestProductExtraction:
    """Test product extraction"""
    def setup_method(self):
        """Setup for each test"""
        self.crawler = MercadoLivreCrawler()

        # Mock complete HTML
        self.complete_poly_card = """
        <li class="ui-search-layout__item">
            <div class="poly-card">
                <h2 class="poly-component__title">
                    <a href="https://produto.mercadolivre.com.br/MLB789">Produto Completo Teste</a>
                </h2>
                <div class="poly-price__current">
                    <span class="andes-money-amount__fraction">199</span>
                </div>
                <div class="poly-component__seller">Loja Oficial</div>
                <div class="poly-reviews__rating">4.5</div>
                <div class="poly-reviews__total">(250 avaliações)</div>
                <div class="poly-component__shipping">Frete grátis</div>
                <div class="poly-component__location">São Paulo</div>
                <img class="poly-component__picture" src="https://http2.mlstatic.com/D_789_V.jpg" alt="produto">
            </div>
        </li>
        """
    
    def test_extract_poly_card_product_complete(self):
        """Test complete product extraction in poly-card layout"""
        container = BeautifulSoup(self.complete_poly_card, 'html.parser').find('li')
        result = self.crawler._extract_poly_card_product(container, 1, 1)
        
        assert result is not None
        assert "Produto Completo Teste" in result["title"]
        assert result["price"] == "19900"
        assert result["seller"] == "Loja Oficial"
        assert result["rating"] == "4.5"
        assert "250 avaliações" in result["reviews_count"]
        assert result["shipping"] == "Frete grátis"
        assert result["location"] == "São Paulo"
        assert result["product_url"].startswith("https://produto.mercadolivre.com.br")
        assert result["page_number"] == 1
        assert result["position_on_page"] == 1


class TestAsyncMethods:
    """Test asynchronous methods (mocked)"""
    
    def setup_method(self):
        """Setup for each test"""
        self.crawler = MercadoLivreCrawler(max_pages=1, delay_between_pages=0)
    
    @patch('crawler.AsyncWebCrawler')
    @pytest.mark.asyncio
    async def test_search_products_mock_success(self, mock_crawler_class):
        """Test search_products with mock (success)"""
        # Setup mock
        mock_crawler = MagicMock()
        mock_crawler_class.return_value.__aenter__.return_value = mock_crawler

        # Mock successful response
        mock_result = Mock()
        mock_result.success = True
        mock_result.html = """
        <div class="ui-search-results">
            <li class="ui-search-layout__item">
                <h2 class="poly-component__title">Produto Mock</h2>
                <span class="andes-money-amount__fraction">100</span>
            </li>
        </div>
        """
        mock_crawler.arun.return_value = mock_result
        
        # Run test
        result = await self.crawler.search_products("teste")
        
        # Checks
        assert result["success"] == True
        assert result["search_term"] == "teste"
        assert isinstance(result["total_products"], int)
        assert isinstance(result["products"], list)
        assert "timestamp" in result
        assert "execution_time" in result
    
    @patch('crawler.AsyncWebCrawler')
    @pytest.mark.asyncio
    async def test_search_products_mock_failure(self, mock_crawler_class):
        """Test search_products with mock (failure)"""
        # Setup mock
        mock_crawler = MagicMock()
        mock_crawler_class.return_value.__aenter__.return_value = mock_crawler

        # Mock failed response
        mock_result = Mock()
        mock_result.success = False
        mock_result.error_message = "Erro de teste"
        mock_crawler.arun.return_value = mock_result

        # Run test
        result = await self.crawler.search_products("teste")

        # Checks
        assert result["search_term"] == "teste"
        assert result["total_products"] == 0
        assert result["products"] == []
        assert isinstance(result["success"], bool)


class TestConfigIntegration:
    """Test integration with Config"""
    
    def setup_method(self):
        """Setup for each test"""
        self.crawler = MercadoLivreCrawler()
    
    def test_config_selectors_access(self):
        """Test if Config selectors are accessible"""
        assert hasattr(Config, 'SELECTORS')
        assert 'POLY_CARD' in Config.SELECTORS
        assert 'CLASSIC' in Config.SELECTORS

        # Check if essential selectors exist
        poly_selectors = Config.SELECTORS['POLY_CARD']
        assert 'title' in poly_selectors
        assert 'price_current' in poly_selectors
        assert 'image' in poly_selectors
        assert 'product_link' in poly_selectors
    
    def test_config_constants_access(self):
        """Test if Config constants are accessible"""
        assert hasattr(Config, 'VALID_IMAGE_DOMAINS')
        assert hasattr(Config, 'IMAGE_ATTRIBUTES')
        assert hasattr(Config, 'CRAWL4AI_CONFIG')
        assert hasattr(Config, 'MERCADO_LIVRE_BASE_URL')

        # Check expected values
        assert 'mlstatic.com' in Config.VALID_IMAGE_DOMAINS
        assert 'src' in Config.IMAGE_ATTRIBUTES
        assert 'data-src' in Config.IMAGE_ATTRIBUTES


if __name__ == "__main__":
    # Run basic tests if executed directly
    pytest.main([__file__])