#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Main script to run the crawler
        if not args.json_output:
            print("\n" + "="*60)
            print("EXECUTION SUMMARY")
            print("="*60)
            print(f"Search term: {result['search_term']}")
            print(f"Total products: {result['total_products']}")
            print(f"Pages crawled: {result['pages_crawled']}")
            print(f"Execution time: {result['execution_time']}s")
            print(f"Status: {'✅ Success' if result['success'] else '❌ Error'}")

            if result.get('error_message'):
                print(f"Error: {result['error_message']}")

            # Show retry metrics if available
            if result.get('retry_metrics'):
                metrics = result['retry_metrics']
                print(f"\nRetry Metrics:")
                print(f"  - Success rate: {metrics.get('success_rate_percent', 0)}%")
                print(f"  - Total attempts: {metrics.get('total_attempts', 0)}")
                print(f"  - Successful retries: {metrics.get('successful_retries', 0)}")

            # Show performance metrics if available
            if result.get('performance_metrics'):
                perf = result['performance_metrics']
                requests_data = perf.get('requests', {})
                system_data = perf.get('system', {})

                print(f"\nPerformance Metrics:")
                print(f"  - Total requests: {requests_data.get('total', 0)}")
                print(f"  - Success rate: {requests_data.get('success_rate_percent', 0):.1f}%")
                print(f"  - Average response time: {requests_data.get('avg_response_time_ms', 0):.0f}ms")
                print(f"  - Memory usage: {system_data.get('memory_usage_mb', 0):.1f}MB")
                print(f"  - CPU usage: {system_data.get('cpu_percent', 0):.1f}%")

            # Show rate limiter status if available
            if result.get('rate_limiter_status'):
                rate_status = result['rate_limiter_status']
                print(f"\nRate Limiter:")
                print(f"  - Current delay: {rate_status.get('current_delay', 0):.2f}s")
                print(f"  - Max concurrent: {rate_status.get('max_concurrent', 0)}")
                recent_perf = rate_status.get('recent_performance', {})
                if recent_perf:
                    print(f"  - Recent performance: {recent_perf.get('success_rate', 0):.1%} success")

            print(f"\nSaved files:")
            for file in saved_files:
                print(f"  - {file}")
            print(f"Pages processed: {getattr(result, 'pages_crawled', getattr(result, 'get', lambda k, d=None: d)('pages_crawled', 0))}")
            print(f"Execution time: {getattr(result, 'execution_time', getattr(result, 'get', lambda k, d=None: d)('execution_time', 0))}s")
            print(f"Status: {'✅ Success' if getattr(result, 'success', getattr(result, 'get', lambda k, d=None: d)('success', False)) else '❌ Error'}")
            print(f"Execution time: {result.execution_time}s")
            print(f"Status: {'✅ Success' if result.success else '❌ Error'}")
            print(f"Can be run standalone or called by the .NET backend")
"""

import asyncio
import sys
import argparse
import json
import os
from pathlib import Path

# Configure UTF-8 encoding for Windows
if sys.platform == "win32":
    # Force UTF-8 for all I/O operations
    import locale
    os.environ['PYTHONIOENCODING'] = 'utf-8'
    # Reconfigure stdout and stderr to UTF-8
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

# Add src to path
sys.path.append(str(Path(__file__).parent / "src"))

from src.logging_config import setup_logging, get_logger
from src.health_monitor import setup_health_monitoring, ResourceLimits

from config import Config
from src.crawler import MercadoLivreCrawler
from src.utils import FileExporter
from src.exceptions import CrawlerBaseException

async def main():
    # Configure command line arguments
    parser = argparse.ArgumentParser(description='Crawler Mercado Livre')
    parser.add_argument('search_term', help='Search term')
    parser.add_argument('--pages', type=int, default=3, help='Number of pages (default: 3)')
    parser.add_argument('--output', choices=['json', 'excel', 'both'], default='both', 
                       help='Output format (default: both)')
    parser.add_argument('--json-output', action='store_true', 
                       help='Print JSON result to standard output (for .NET integration)')
    parser.add_argument('--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], 
                       default='INFO', help='Logging level (default: INFO)')

    args = parser.parse_args()

    # Configure environment and professional logging
    Config.ensure_directories()
    setup_logging(
        log_level=args.log_level,
        log_dir=Config.LOGS_DIR,
        enable_console=(not args.json_output)  # Disable console in integration mode
    )
    logger = get_logger(__name__)

    # Configure health monitoring
    resource_limits = ResourceLimits(
        max_memory_mb=512.0,  # 512MB
        max_cpu_percent=80.0,  # 80% CPU
        max_concurrent_requests=args.pages * 2  # Based on the number of pages
    )
    setup_health_monitoring(resource_limits)
    
    try:
        logger.info(f"Starting crawler for: {args.search_term}", extra={
            "search_term": args.search_term,
            "max_pages": args.pages,
            "output_format": args.output,
            "json_output": args.json_output
        })
        
        # Execute crawler
        crawler = MercadoLivreCrawler(max_pages=args.pages)
        result = await crawler.search_products(args.search_term)

        # Save results
        saved_files = []
        
        if args.output in ['json', 'both']:
            json_file = FileExporter.save_to_json(result, Config.JSON_OUTPUT_DIR)
            saved_files.append(json_file)
            logger.info(f"JSON saved to: {json_file}")

        if args.output in ['excel', 'both']:
            excel_file = FileExporter.save_to_excel(result, Config.EXCEL_OUTPUT_DIR)
            saved_files.append(excel_file)
            logger.info(f"Excel saved to: {excel_file}")

        # For .NET integration, print JSON to standard output BEFORE the summary
        if args.json_output:
            print("=== JSON OUTPUT ===")
            print(json.dumps(result, ensure_ascii=False))
            print("=== END JSON OUTPUT ===")
            # Flush to ensure output is sent immediately
            sys.stdout.flush()

        # Show summary (only if not called by .NET to avoid polluting output)
        if not args.json_output:
            print("\n" + "="*60)
            print("EXECUTION SUMMARY")
            print("="*60)
            print(f"Search term: {result.search_term}")
            print(f"Total products: {result.total_products}")
            print(f"Pages crawled: {result.pages_crawled}")
            print(f"Execution time: {result.execution_time}s")
            print(f"Status: {'✔️ Success' if result.success else '❌ Error'}")

            if result.error_message:
                print(f"Error: {result.error_message}")

            print(f"\nSaved files:")
            for file in saved_files:
                print(f"  - {file}")

        logger.info(f"Crawler executed successfully", extra={
            "search_term": args.search_term,
            "total_products": result['total_products'],
            "pages_crawled": result['pages_crawled'],
            "execution_time": result['execution_time'],
            "files_saved": len(saved_files)
        })
        
        return result['success']
        
    except CrawlerBaseException as e:
        logger.error(f"Specific crawler error: {str(e)}", extra={
            "search_term": args.search_term,
            "error_type": type(e).__name__,
            "error_message": str(e),
            "context": e.context
        })
        
        # Create structured error output
        error_result = {
            "search_term": args.search_term,
            "total_products": 0,
            "pages_crawled": 0,
            "timestamp": "",
            "execution_time": 0,
            "products": [],
            "success": False,
            "error_message": str(e),
            "error_type": type(e).__name__
        }
        
        if args.json_output:
            print("=== JSON OUTPUT ===")
            print(json.dumps(error_result, ensure_ascii=False))
            print("=== END JSON OUTPUT ===")
            sys.stdout.flush()
            
        return False
        
    except Exception as e:
        logger.error(f"Unexpected error occurred: {str(e)}", extra={
            "search_term": args.search_term,
            "error_type": type(e).__name__,
            "error_message": str(e)
        })

        # Create structured error output
        error_result = {
            "search_term": args.search_term,
            "total_products": 0,
            "pages_crawled": 0,
            "timestamp": "",
            "execution_time": 0,
            "products": [],
            "success": False,
            "error_message": str(e),
            "error_type": type(e).__name__
        }
        
        if args.json_output:
            print("=== JSON OUTPUT ===")
            print(json.dumps(error_result, ensure_ascii=False))
            print("=== END JSON OUTPUT ===")
            sys.stdout.flush()

        saved_files = []
        try:
            if args.output in ['json', 'both']:
                json_file = FileExporter.save_to_json(result, Config.JSON_OUTPUT_DIR)
                saved_files.append(json_file)
                logger.info(f"JSON saved to: {json_file}")

            if args.output in ['excel', 'both']:
                excel_file = FileExporter.save_to_excel(result, Config.EXCEL_OUTPUT_DIR)
                saved_files.append(excel_file)
                logger.info(f"Excel saved to: {excel_file}")
        except Exception as e:
            logger.error(f"Failed to save files: {e}")
            # Do NOT crash the process if in integration mode
            if not args.json_output:
                raise

        # A good summary is only when it is NOT an integration.
        if not args.json_output:
            print("\n" + "="*60)
            print("EXECUTION SUMMARY")
            print("="*60)
            print(f"Search term: {getattr(result, 'search_term', getattr(result, 'get', lambda k, d=None: d)('search_term', ''))}")
            print(f"Total products: {getattr(result, 'total_products', getattr(result, 'get', lambda k, d=None: d)('total_products', 0))}")
            print(f"Processed pages: {getattr(result, 'pages_crawled', getattr(result, 'get', lambda k, d=None: d)('pages_crawled', 0))}")
            print(f"Execution time: {getattr(result, 'execution_time', getattr(result, 'get', lambda k, d=None: d)('execution_time', 0))}s")
            print(f"Status: {'✔ Success' if getattr(result, 'success', getattr(result, 'get', lambda k, d=None: d)('success', False)) else '✖ Error'}")
            if getattr(result, 'error_message', getattr(result, 'get', lambda k, d=None: d)('error_message', '')):
                print(f"Error: {getattr(result, 'error_message', getattr(result, 'get', lambda k, d=None: d)('error_message', ''))}")
            print(f"\nSaved files:")
            for file in saved_files:
                print(f"  - {file}")

        return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)