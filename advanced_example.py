#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Example script demonstrating advanced use of MercadoLivre Crawler
with a complete metrics, health monitoring, and performance system.

This script shows how to use all the professional features
implemented in the crawler.
"""

import asyncio
import time
from pathlib import Path
import sys

# Add src to path
sys.path.append(str(Path(__file__).parent / "src"))

from src.logging_config import setup_logging, get_logger
from src.health_monitor import (
    get_health_monitor, setup_health_monitoring, 
    ResourceLimits, get_adaptive_rate_limiter
)
from src.metrics import get_metrics_collector, setup_default_alerts
from src.crawler import MercadoLivreCrawler
from config import Config


async def advanced_crawler_example():
    """Advanced example of using the crawler with all systems."""
    # 1. Set up advanced logging
    setup_logging(
        log_level="INFO",
        log_dir=Config.LOGS_DIR,
        enable_console=True
    )
    logger = get_logger(__name__)

    logger.info("=== Starting advanced crawler example ===")

    # 2. Set up custom resource limits
    resource_limits = ResourceLimits(
        max_memory_mb=256.0,      # 256MB limit
        max_cpu_percent=70.0,     # 70% CPU max
        max_open_files=50,
        max_concurrent_requests=3  # Low concurrency for testing
    )

    # 3. Initialize health monitoring
    setup_health_monitoring(resource_limits)
    health_monitor = get_health_monitor()

    logger.info("Health monitor configured", extra={
        "resource_limits": resource_limits.to_dict()
    })

    # 4. Set up custom alerts
    setup_default_alerts()

    # Add custom alert callback
    metrics_collector = get_metrics_collector()
    
    def custom_alert_handler(alert_type: str, context: dict):
        logger.warning(f"🚨 CUSTOM ALERT: {alert_type}", extra={
            "alert_type": alert_type,
            "context": context
        })
    
    metrics_collector.add_alert_callback(custom_alert_handler)

    # 5. Execute search with monitoring
    search_terms = ["creatina", "whey protein"]
    
    for term in search_terms:
        logger.info(f"Starting search: {term}")

        try:
            # Check system health before search
            health_status = health_monitor.run_health_checks()
            logger.info("Health status before search", extra={
                "overall_status": health_status["overall_status"],
                "checks": len(health_status["checks"])
            })

            # Execute crawler with limited pages for example
            crawler = MercadoLivreCrawler(max_pages=2, delay_between_pages=1)
            result = await crawler.search_products(term)

            # Show basic results
            logger.info(f"Search completed: {term}", extra={
                "success": result["success"],
                "total_products": result["total_products"],
                "execution_time": result["execution_time"]
            })

            # Show detailed metrics
            current_metrics = metrics_collector.get_current_metrics()
            logger.info("Current metrics", extra=current_metrics)

            # Adaptive rate limiter status
            rate_limiter = get_adaptive_rate_limiter()
            limiter_status = rate_limiter.get_current_limits()
            logger.info("Adaptive rate limiter status", extra=limiter_status)

            # Performance report for the last 5 minutes
            perf_report = metrics_collector.get_performance_report(last_minutes=5)
            if "error" not in perf_report:
                logger.info("Performance report", extra={
                    "period_minutes": perf_report["period_minutes"],
                    "requests_analyzed": perf_report["requests_analyzed"],
                    "success_rate": perf_report["requests"]["success_rate_percent"],
                    "avg_response_time": perf_report["requests"]["response_times"]["avg_ms"]
                })
            
            print("\n" + "="*60)
            print(f"SEARCH RESULTS: {term.upper()}")
            print("="*60)
            print(f"✅ Products found: {result['total_products']}")
            print(f"⏱️ Execution time: {result['execution_time']}s")
            print(f"📊 Status: {'Success' if result['success'] else 'Error'}")

            if result.get("performance_metrics"):
                perf = result["performance_metrics"]
                req_data = perf.get("requests", {})
                sys_data = perf.get("system", {})

                print(f"\n📈 PERFORMANCE METRICS:")
                print(f"  • Total requests: {req_data.get('total', 0)}")
                print(f"  • Success rate: {req_data.get('success_rate_percent', 0):.1f}%")
                print(f"  • Average time: {req_data.get('avg_response_time_ms', 0):.0f}ms")
                print(f"  • Memory usage: {sys_data.get('memory_usage_mb', 0):.1f}MB")
                print(f"  • CPU: {sys_data.get('cpu_percent', 0):.1f}%")
            
            if result.get("rate_limiter_status"):
                rate_status = result["rate_limiter_status"]
                print(f"\n⚡ RATE LIMITER:")
                print(f"  • Current delay: {rate_status.get('current_delay', 0):.2f}s")
                print(f"  • MMax concurrent: {rate_status.get('max_concurrent', 0)}")

        except Exception as e:
            logger.error(f"Search error {term}: {str(e)}", extra={
                "search_term": term,
                "error_type": type(e).__name__
            })
        
        # Short break between searches
        await asyncio.sleep(3)
    
    # 6. Final health check
    print("\n" + "="*60)
    print("FINAL HEALTH CHECK")
    print("="*60)
    
    final_health = health_monitor.run_health_checks()
    overall_status = final_health["overall_status"]
    
    status_emoji = {
        "healthy": "✅",
        "warning": "⚠️", 
        "critical": "❌"
    }

    print(f"{status_emoji.get(overall_status, '❓')} Overall status: {overall_status.upper()}")

    for check_name, check_result in final_health["checks"].items():
        status = check_result["status"]
        message = check_result["message"]
        emoji = status_emoji.get(status, "❓")
        
        print(f"  {emoji} {check_name}: {message}")
    
    # 7. Force memory cleanup for demo
    memory_optimizer = health_monitor.get_memory_optimizer()
    
    should_cleanup, reason = memory_optimizer.should_cleanup()
    if should_cleanup:
        print(f"\n🧹 Executando limpeza de memória: {reason}")
        cleanup_result = memory_optimizer.cleanup_memory()

        print(f"  • Memory before: {cleanup_result['before_memory_mb']:.1f}MB")
        print(f"  • Memory after: {cleanup_result['after_memory_mb']:.1f}MB")
        print(f"  • Memory freed: {cleanup_result['freed_mb']:.1f}MB")
    else:
        print("\n✨ Memory usage normal - no cleanup needed")

    # 8. Final metrics
    final_metrics = metrics_collector.get_current_metrics()

    print(f"\n📊 FINAL METRICS:")
    print(f"  • Total requests: {final_metrics['requests'].get('total', 0)}")
    print(f"  • Successful requests: {final_metrics['requests'].get('successful', 0)}")
    print(f"  • Success rate: {final_metrics['requests'].get('success_rate_percent', 0):.1f}%")
    print(f"  • Bytes downloaded: {final_metrics['requests'].get('total_bytes_downloaded', 0):,}")

    logger.info("=== Advanced example completed ===")


async def health_check_demo():
    """Demonstration of the health check system."""
    
    print("\n" + "="*60)
    print("HEALTH CHECKS DEMONSTRATION")
    print("="*60)
    
    health_monitor = get_health_monitor()

    # Run full health check
    health_status = health_monitor.run_health_checks()

    print(f"Overall status: {health_status['overall_status'].upper()}")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(health_status['timestamp']))}")
    print(f"Checks executed: {len(health_status['checks'])}")

    print(f"\nCheck details:")
    for check_name, result in health_status["checks"].items():
        status = result["status"]
        message = result["message"]
        
        status_symbols = {"ok": "✅", "warning": "⚠️", "critical": "❌"}
        symbol = status_symbols.get(status, "❓")
        
        print(f"  {symbol} {check_name}: {message}")

        # Show additional details for specific checks
        if check_name == "memory_usage" and "details" in result:
            details = result["details"]
            print(f"      └─ RSS: {details.get('rss_mb', 0):.1f}MB, VMS: {details.get('vms_mb', 0):.1f}MB")
        
        elif check_name == "request_performance" and "details" in result:
            details = result["details"]
            print(f"      └─ Avg: {details.get('avg_response_time_ms', 0):.0f}ms, Total: {details.get('total', 0)}")


async def metrics_demo():
    """Demonstration of the metrics system."""
    
    print("\n" + "="*60)
    print("METRICS DEMONSTRATION")
    print("="*60)
    
    metrics = get_metrics_collector()
    
    # Simulate some requests to get data
    print("Simulating requests to collect metrics...")

    for i in range(5):
        request_id = metrics.start_request(f"https://example.com/test_{i}")

        # Simulate processing time
        await asyncio.sleep(0.1 + (i * 0.05))

        # Finalize request with simulated data
        success = i < 4  # One failure to demonstrate
        response_size = 1024 * (i + 1)  # Increasing sizes
        error_type = None if success else "SimulatedError"
        
        metrics.end_request(request_id, success, response_size, error_type)

    # Wait a bit for metrics to be processed
    await asyncio.sleep(1)

    # Show current metrics
    current_metrics = metrics.get_current_metrics()

    print(f"\nSystem Metrics:")
    system = current_metrics.get("system", {})
    print(f"  • Memory: {system.get('memory_usage_mb', 0):.1f}MB")
    print(f"  • CPU: {system.get('cpu_percent', 0):.1f}%")
    print(f"  • Open Files: {system.get('open_files', 0)}")
    print(f"  • Threads: {system.get('thread_count', 0)}")

    print(f"\nRequest Metrics:")
    requests_data = current_metrics.get("requests", {})
    print(f"  • Total: {requests_data.get('total', 0)}")
    print(f"  • Successful: {requests_data.get('successful', 0)}")
    print(f"  • Failed: {requests_data.get('failed', 0)}")
    print(f"  • Success Rate: {requests_data.get('success_rate_percent', 0):.1f}%")
    print(f"  • Avg Response Time: {requests_data.get('avg_response_time_ms', 0):.2f}ms")
    print(f"  • Total Bytes Downloaded: {requests_data.get('total_bytes_downloaded', 0):,}")

    # Performance report
    perf_report = metrics.get_performance_report(last_minutes=1)
    
    if "error" not in perf_report:
        print(f"\nPerformance Report (last minute):")
        req_analysis = perf_report.get("requests", {})
        print(f"  • Requests analyzed: {req_analysis.get('total_requests', 0)}")
        print(f"  • Success Rate: {req_analysis.get('success_rate_percent', 0):.1f}%")

        response_times = req_analysis.get("response_times", {})
        print(f"  • Avg: {response_times.get('avg_ms', 0):.2f}ms")
        print(f"  • P95: {response_times.get('p95_ms', 0):.2f}ms")
        print(f"  • P99: {response_times.get('p99_ms', 0):.2f}ms")


if __name__ == "__main__":
    async def main():
        # Configure directories
        Config.ensure_directories()

        # Demonstrations
        await advanced_crawler_example()
        await health_check_demo()
        await metrics_demo()

        print("\n🎉 All demonstrations completed!")
        print("Check the logs in 'logs/' for detailed analysis.")

    asyncio.run(main())