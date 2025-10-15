import asyncio
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from bs4 import BeautifulSoup
import urllib.parse
import sys

async def inspect_amazon():
    # Get search term from command line or use default for testing
    search_term = sys.argv[1] if len(sys.argv) > 1 else input("Enter search term: ")
    encoded_term = urllib.parse.quote_plus(search_term)
    url = f"https://www.amazon.com.br/s?k={encoded_term}"
    
    print(f"Fetching: {url}\n")
    
    browser_config = BrowserConfig(
        headless=True,
        verbose=True,
        viewport_width=1920,
        viewport_height=1080
    )
    
    run_config = CrawlerRunConfig(
        js_code=[
            "await new Promise(resolve => setTimeout(resolve, 5000));",
        ],
        page_timeout=60000,
        process_iframes=False
    )
    
    async with AsyncWebCrawler(config=browser_config) as crawler:
        print("Fetching Amazon with 5 second wait for JavaScript rendering...")
        result = await crawler.arun(
            url=url,
            config=run_config
        )
        
        if result.success:
            print(f"\n✓ Fetch successful")
            print(f"✓ HTML Length: {len(result.html):,} bytes")
            
            with open("debug_amazon.html", "w", encoding="utf-8") as f:
                f.write(result.html)
            print("✓ HTML saved to debug_amazon.html\n")
            
            soup = BeautifulSoup(result.html, 'html.parser')
            
            print("=== Testing Common Amazon Selectors ===")
            selectors = {
                "Main container": 'div.s-main-slot',
                "Product card (v1)": 'div[data-component-type="s-search-result"]',
                "Product card (v2)": 'div.s-result-item',
                "Product link": 'h2.s-line-clamp-2 a',
                "Product title": 'h2.s-line-clamp-2',
                "Product price": 'span.a-price-whole',
                "Product image": 'img.s-image',
                "Rating": 'span.a-icon-alt',
                "Reviews count": 'span.a-size-base.s-underline-text',
                "Prime badge": 'i.a-icon-prime',
                "Seller info": 'span.a-size-base-plus',
                "Alternative container": 'div.sg-col-inner',
                "Any product link": 'a[href*="/dp/"]',
            }
            
            found_any = False
            products_found = 0
            
            for name, selector in selectors.items():
                try:
                    elements = soup.select(selector)
                    count = len(elements)
                    status = "✓" if count > 0 else "✗"
                    print(f"{status} {name:30}: {count:4} found")
                    
                    if count > 0:
                        found_any = True
                        if 'product' in name.lower() or 'container' in name.lower():
                            products_found = max(products_found, count)
                except Exception as e:
                    print(f"✗ {name:30}: Error - {str(e)[:50]}")
            
            if found_any:
                print(f"\n✓ SUCCESS! Found {products_found} potential product containers")
                
                product_selectors = [
                    'div[data-component-type="s-search-result"]',
                    'div.s-result-item[data-asin]',
                ]
                
                products = []
                for selector in product_selectors:
                    products = soup.select(selector)
                    if products:
                        products = [p for p in products if p.get('data-asin')][:3]
                        if products:
                            print(f"\n✓ Using selector: {selector}")
                            print(f"✓ Found {len(products)} products with ASIN")
                            break
                
                if products:
                    print(f"\n=== Sample Product Data (first {len(products)}) ===")
                    for i, product in enumerate(products, 1):
                        asin = product.get('data-asin', 'N/A')
                        
                        title_elem = product.select_one('h2.s-line-clamp-2')
                        title = title_elem.get_text(strip=True) if title_elem else 'N/A'
                        
                        price_whole = product.select_one('span.a-price-whole')
                        price_fraction = product.select_one('span.a-price-fraction')
                        if price_whole:
                            price = price_whole.get_text(strip=True)
                            if price_fraction:
                                price += price_fraction.get_text(strip=True)
                        else:
                            price = 'N/A'
                        
                        rating_elem = product.select_one('span.a-icon-alt')
                        rating = rating_elem.get_text(strip=True) if rating_elem else 'N/A'
                        
                        reviews_elem = product.select_one('span.a-size-base.s-underline-text')
                        reviews = reviews_elem.get_text(strip=True) if reviews_elem else 'N/A'
                        
                        link_elem = product.select_one('h2.s-line-clamp-2 a')
                        link = link_elem.get('href', 'N/A') if link_elem else 'N/A'
                        
                        prime = "✓" if product.select_one('i.a-icon-prime') else "✗"
                        
                        print(f"\nProduct {i} (ASIN: {asin}):")
                        print(f"  Title: {title[:80]}...")
                        print(f"  Price: R$ {price}")
                        print(f"  Rating: {rating}")
                        print(f"  Reviews: {reviews}")
                        print(f"  Prime: {prime}")
                        print(f"  Link: {link[:80]}...")
                else:
                    print("\n⚠ No products with ASIN found, but HTML elements detected")
            else:
                print("\n✗ NO PRODUCTS FOUND - Checking HTML structure...")
                
                all_divs = soup.find_all('div', limit=50)
                print(f"\nTotal div elements (first 50): {len(all_divs)}")
                
                print("\nChecking for captcha or anti-bot messages:")
                captcha_indicators = [
                    'captcha',
                    'robot',
                    'automated',
                    'unusual traffic'
                ]
                
                page_text = soup.get_text().lower()
                for indicator in captcha_indicators:
                    if indicator in page_text:
                        print(f"  ⚠ Found '{indicator}' in page - possible bot detection")
        else:
            print(f"✗ Failed: {result.error_message}")

if __name__ == "__main__":
    asyncio.run(inspect_amazon())
