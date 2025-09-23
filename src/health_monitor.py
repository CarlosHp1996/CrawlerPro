"""
Health check and resource optimization system for MercadoLibre Crawler.

This module implements automatic health checks, memory optimization, 
intelligent rate limiting, and system resource monitoring.
"""

import asyncio
import gc
import threading
import time
import sys
from typing import Dict, Any, List, Optional, Callable, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
import psutil
import logging

# Import resource module only on Unix systems
if sys.platform != "win32":
    import resource
else:
    resource = None

from .logging_config import get_logger
from .metrics import get_metrics_collector, MetricsCollector

logger = get_logger(__name__)


@dataclass
class ResourceLimits:
    """Resource limits configuration."""
    max_memory_mb: float = 512.0  # 512MB by default
    max_cpu_percent: float = 80.0  # 80% CPU by default
    max_open_files: int = 100
    max_concurrent_requests: int = 10

    # Thresholds for alerts
    memory_warning_threshold: float = 0.75  # 75% of the limit
    cpu_warning_threshold: float = 0.75     # 75% of the limit

    def to_dict(self) -> Dict[str, Any]:
        """Converts to dictionary."""
        return {
            "max_memory_mb": self.max_memory_mb,
            "max_cpu_percent": self.max_cpu_percent,
            "max_open_files": self.max_open_files,
            "max_concurrent_requests": self.max_concurrent_requests,
            "memory_warning_threshold": self.memory_warning_threshold,
            "cpu_warning_threshold": self.cpu_warning_threshold
        }


@dataclass 
class HealthCheckResult:
    """Individual health check result."""
    name: str
    status: str  # "ok", "warning", "critical"
    message: str
    details: Dict[str, Any]
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Converts to dictionary."""
        return {
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp
        }


class AdaptiveRateLimiter:
    """
    Intelligent rate limiter that adapts based on system performance and health.

    Automatically adjusts delays and concurrency limits based on:
    - Memory and CPU usage
    - Request success rates
    - Response times
    - Server rate limiting detection
    """
    
    def __init__(self,
                 initial_delay: float = 1.0,
                 min_delay: float = 0.1,
                 max_delay: float = 30.0,
                 max_concurrent: int = 5):
        """
        Initializes the adaptive rate limiter.
        
        Args:
            initial_delay: Initial delay between requests
            min_delay: Minimum allowed delay
            max_delay: Maximum allowed delay
            max_concurrent: Maximum concurrent requests
        """
        self.current_delay = initial_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_concurrent = max_concurrent
        
        self._current_concurrent = 0
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrent)
        
        # Background for adaptive analysis
        self._recent_response_times = []
        self._recent_success_rates = []
        self._last_adjustment = 0

        logger.info("Adaptive rate limiter initialized", extra={
            "initial_delay": initial_delay,
            "max_concurrent": max_concurrent
        })
    
    async def acquire(self) -> None:
        """Acquire permission to make a request."""
        await self._semaphore.acquire()
        
        async with self._lock:
            self._current_concurrent += 1

        # Apply adaptive delay
        if self.current_delay > 0:
            await asyncio.sleep(self.current_delay)
    
    async def release(self, success: bool, response_time_ms: float):
        """
        Releases a request and updates metrics for adaptation.
        
        Args:
            success: Whether the request was successful
            response_time_ms: Response time in milliseconds
        """
        self._semaphore.release()
        
        async with self._lock:
            self._current_concurrent -= 1

            # Update history for analysis
            self._recent_response_times.append(response_time_ms)
            self._recent_success_rates.append(1.0 if success else 0.0)

            # Keep only latest 50 measurements
            if len(self._recent_response_times) > 50:
                self._recent_response_times.pop(0)
                self._recent_success_rates.pop(0)

            # Adjust rate limiting if necessary
            await self._maybe_adjust_limits()
    
    async def _maybe_adjust_limits(self):
        """Adjusts limits based on recent performance."""
        current_time = time.time()

        # Only adjust every 30 seconds
        if current_time - self._last_adjustment < 30:
            return
        
        if len(self._recent_response_times) < 10:
            return  # Insufficient data

        # Calculate recent metrics
        avg_response_time = sum(self._recent_response_times) / len(self._recent_response_times)
        success_rate = sum(self._recent_success_rates) / len(self._recent_success_rates)
        
        old_delay = self.current_delay
        adjustment_made = False

        # Adjustment logic
        if success_rate < 0.7:  # Low success rate
            # Increase delay to reduce pressure
            self.current_delay = min(self.current_delay * 1.5, self.max_delay)
            adjustment_made = True
            reason = f"low success rate ({success_rate:.1%})"

        elif avg_response_time > 5000:  # High response time (>5s)
            # Increase delay to reduce load
            self.current_delay = min(self.current_delay * 1.2, self.max_delay)
            adjustment_made = True
            reason = f"high response time ({avg_response_time:.0f}ms)"

        elif success_rate > 0.95 and avg_response_time < 2000:
            # Performance good - can decrease delay
            self.current_delay = max(self.current_delay * 0.9, self.min_delay)
            adjustment_made = True
            reason = f"good performance (success: {success_rate:.1%}, time: {avg_response_time:.0f}ms)"
        
        if adjustment_made:
            self._last_adjustment = current_time

            logger.info("Rate limiting adjusted", extra={
                "old_delay": old_delay,
                "new_delay": self.current_delay,
                "reason": reason,
                "avg_response_time_ms": avg_response_time,
                "success_rate": success_rate
            })
    
    def get_current_limits(self) -> Dict[str, Any]:
        """Returns current limits."""
        return {
            "current_delay": self.current_delay,
            "max_concurrent": self.max_concurrent,
            "current_concurrent": self._current_concurrent,
            "recent_performance": {
                "avg_response_time_ms": (
                    sum(self._recent_response_times) / len(self._recent_response_times) 
                    if self._recent_response_times else 0
                ),
                "success_rate": (
                    sum(self._recent_success_rates) / len(self._recent_success_rates)
                    if self._recent_success_rates else 1.0
                )
            }
        }


class MemoryOptimizer:
    """
    Memory optimizer that automatically monitors and cleans up resources.

    Implements memory cleaning strategies based on current usage
    and configurable thresholds.
    """
    
    def __init__(self, 
                 cleanup_threshold_mb: float = 400,
                 aggressive_cleanup_threshold_mb: float = 600):
        """
        Initializes the memory optimizer.

        Args:
            cleanup_threshold_mb: Threshold for basic cleanup
            aggressive_cleanup_threshold_mb: Threshold for aggressive cleanup
        """
        self.cleanup_threshold = cleanup_threshold_mb
        self.aggressive_threshold = aggressive_cleanup_threshold_mb
        
        self._process = psutil.Process()
        self._cleanup_callbacks: List[Callable[[], None]] = []

        logger.info("Memory optimizer initialized", extra={
            "cleanup_threshold_mb": cleanup_threshold_mb,
            "aggressive_threshold_mb": aggressive_cleanup_threshold_mb
        })
    
    def add_cleanup_callback(self, callback: Callable[[], None]):
        """
        Adds callback to be executed during memory cleanup.
        
            Args:
                callback: Função de limpeza customizada
        """
        self._cleanup_callbacks.append(callback)
    
    def get_memory_usage(self) -> Dict[str, float]:
        """Returns detailed memory usage information."""
        memory_info = self._process.memory_info()

        return {
            "rss_mb": memory_info.rss / 1024 / 1024,  # Resident Set Size
            "vms_mb": memory_info.vms / 1024 / 1024,  # Virtual Memory Size
            "percent": self._process.memory_percent(),
            "available_mb": psutil.virtual_memory().available / 1024 / 1024
        }
    
    def should_cleanup(self) -> Tuple[bool, str]:
        """
        Checks if memory cleanup should be performed.
        
        Returns:
            (should_cleanup, reason)
        """
        memory = self.get_memory_usage()
        current_mb = memory["rss_mb"]
        
        if current_mb > self.aggressive_threshold:
            return True, f"aggressive_cleanup (use: {current_mb:.1f}MB > {self.aggressive_threshold}MB)"
        elif current_mb > self.cleanup_threshold:
            return True, f"basic_cleanup (use: {current_mb:.1f}MB > {self.cleanup_threshold}MB)"

        return False, ""
    
    def cleanup_memory(self, aggressive: bool = False) -> Dict[str, Any]:
        """
        Performs memory cleanup.
        
        Args:
            aggressive: If aggressive cleanup should be performed

        Returns:
            Statistics of the performed cleanup
        """
        before_memory = self.get_memory_usage()
        cleanup_actions = []

        logger.info(f"Starting memory cleanup ({'aggressive' if aggressive else 'basic'})",
                   extra={"before_memory_mb": before_memory["rss_mb"]})

        # 1. Execute custom callbacks
        for callback in self._cleanup_callbacks:
            try:
                callback()
                cleanup_actions.append("custom_callback")
            except Exception as e:
                logger.warning(f"Error in cleanup callback: {e}")

        # 2. Force garbage collection
        collected = gc.collect()
        cleanup_actions.append(f"gc_collect ({collected} cycles)")
        
        if aggressive:
            # 3. Aggressive cleanup - multiple garbage collection
            for generation in range(3):
                gc.collect(generation)
            cleanup_actions.append("aggressive_gc")

            # 4. Try to compact objects
            try:
                gc.set_threshold(700, 10, 10)  # More aggressive thresholds
                cleanup_actions.append("gc_threshold_adjustment")
            except Exception as e:
                logger.warning(f"Error adjusting GC thresholds: {e}")
        
        after_memory = self.get_memory_usage()
        freed_mb = before_memory["rss_mb"] - after_memory["rss_mb"]
        
        result = {
            "before_memory_mb": before_memory["rss_mb"],
            "after_memory_mb": after_memory["rss_mb"],
            "freed_mb": freed_mb,
            "cleanup_actions": cleanup_actions,
            "aggressive": aggressive,
            "timestamp": time.time()
        }

        logger.info("Memory cleanup completed", extra=result)

        return result


class HealthMonitor:
    """
    Main system health monitor.

    Coordinates health checks, resource optimization, and corrective actions.
    """
    
    def __init__(self, 
                 resource_limits: Optional[ResourceLimits] = None,
                 check_interval: float = 30.0):
        """
        Initializes the health monitor.
        
        Args:
            resource_limits: Custom resource limits
            check_interval: Interval between checks in seconds
        """
        self.limits = resource_limits or ResourceLimits()
        self.check_interval = check_interval
        
        self.metrics_collector = get_metrics_collector()
        self.memory_optimizer = MemoryOptimizer(
            cleanup_threshold_mb=self.limits.max_memory_mb * 0.7,
            aggressive_cleanup_threshold_mb=self.limits.max_memory_mb * 0.9
        )
        self.rate_limiter = AdaptiveRateLimiter()
        
        # Threading
        self._monitoring_thread = None
        self._stop_monitoring = threading.Event()
        
        # Health check registry
        self._health_checks: Dict[str, Callable[[], HealthCheckResult]] = {}
        self._register_default_checks()

        # Corrective actions
        self._corrective_actions: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        self._register_default_actions()

        logger.info("Health monitor initialized", extra={
            "resource_limits": self.limits.to_dict(),
            "check_interval": check_interval
        })
    
    def _register_default_checks(self):
        """Registers default health checks."""
        self._health_checks.update({
            "memory_usage": self._check_memory_usage,
            "cpu_usage": self._check_cpu_usage,
            "request_performance": self._check_request_performance,
            "error_rates": self._check_error_rates,
            "system_resources": self._check_system_resources
        })
    
    def _register_default_actions(self):
        """Registers default corrective actions."""
        self._corrective_actions.update({
            "high_memory": self._action_cleanup_memory,
            "high_error_rate": self._action_adjust_rate_limiting,
            "poor_performance": self._action_optimize_requests
        })
    
    def start_monitoring(self):
        """Start automatic monitoring."""
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            return
        
        self._stop_monitoring.clear()
        self._monitoring_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True,
            name="HealthMonitor"
        )
        self._monitoring_thread.start()

        logger.info("Health monitoring started")

    def stop_monitoring(self):
        """Stop automatic monitoring."""
        self._stop_monitoring.set()
        
        if self._monitoring_thread:
            self._monitoring_thread.join(timeout=2.0)

        logger.info("Health monitoring stopped")

    def _monitoring_loop(self):
        """Main monitoring loop."""
        while not self._stop_monitoring.wait(self.check_interval):
            try:
                health_report = self.run_health_checks()
                self._evaluate_and_act(health_report)
            except Exception as e:
                logger.error(f"Error in health monitoring loop: {e}")

    def run_health_checks(self) -> Dict[str, Any]:
        """
        Executes all registered health checks.

        Returns:
            Full health report
        """
        results = {}
        overall_status = "healthy"
        
        for check_name, check_func in self._health_checks.items():
            try:
                result = check_func()
                results[check_name] = result.to_dict()
                
                # Determine overall status
                if result.status == "critical":
                    overall_status = "critical"
                elif result.status == "warning" and overall_status == "healthy":
                    overall_status = "warning"
                    
            except Exception as e:
                logger.error(f"Error in health check {check_name}: {e}")
                results[check_name] = {
                    "name": check_name,
                    "status": "critical",
                    "message": f"Error in health check: {str(e)}",
                    "details": {},
                    "timestamp": time.time()
                }
                overall_status = "critical"
        
        return {
            "overall_status": overall_status,
            "timestamp": time.time(),
            "checks": results,
            "resource_limits": self.limits.to_dict()
        }
    
    def _check_memory_usage(self) -> HealthCheckResult:
        """Health check for memory usage."""
        memory_info = self.memory_optimizer.get_memory_usage()
        current_mb = memory_info["rss_mb"]
        
        if current_mb > self.limits.max_memory_mb:
            return HealthCheckResult(
                name="memory_usage",
                status="critical",
                message=f"Memory usage exceeded limit: {current_mb:.1f}MB > {self.limits.max_memory_mb}MB",
                details=memory_info,
                timestamp=time.time()
            )
        elif current_mb > self.limits.max_memory_mb * self.limits.memory_warning_threshold:
            return HealthCheckResult(
                name="memory_usage", 
                status="warning",
                message=f"High memory usage: {current_mb:.1f}MB (limit: {self.limits.max_memory_mb}MB)",
                details=memory_info,
                timestamp=time.time()
            )
        else:
            return HealthCheckResult(
                name="memory_usage",
                status="ok",
                message=f"Normal memory usage: {current_mb:.1f}MB",
                details=memory_info,
                timestamp=time.time()
            )
    
    def _check_cpu_usage(self) -> HealthCheckResult:
        """Health check for CPU usage."""
        try:
            process = psutil.Process()
            cpu_percent = process.cpu_percent()
            
            if cpu_percent > self.limits.max_cpu_percent:
                return HealthCheckResult(
                    name="cpu_usage",
                    status="critical",
                    message=f"CPU usage exceeded limit: {cpu_percent:.1f}% > {self.limits.max_cpu_percent}%",
                    details={"cpu_percent": cpu_percent, "limit": self.limits.max_cpu_percent},
                    timestamp=time.time()
                )
            elif cpu_percent > self.limits.max_cpu_percent * self.limits.cpu_warning_threshold:
                return HealthCheckResult(
                    name="cpu_usage",
                    status="warning",
                    message=f"High CPU usage: {cpu_percent:.1f}%",
                    details={"cpu_percent": cpu_percent, "limit": self.limits.max_cpu_percent},
                    timestamp=time.time()
                )
            else:
                return HealthCheckResult(
                    name="cpu_usage",
                    status="ok",
                    message=f"Normal CPU usage: {cpu_percent:.1f}%",
                    details={"cpu_percent": cpu_percent},
                    timestamp=time.time()
                )
        except Exception as e:
            return HealthCheckResult(
                name="cpu_usage",
                status="critical",
                message=f"Error checking CPU: {str(e)}",
                details={"error": str(e)},
                timestamp=time.time()
            )
    
    def _check_request_performance(self) -> HealthCheckResult:
        """Health check for request performance."""
        metrics = self.metrics_collector.get_current_metrics()
        request_metrics = metrics.get("requests", {})
        
        avg_response_time = request_metrics.get("avg_response_time_ms", 0)
        success_rate = request_metrics.get("success_rate_percent", 100)
        
        if success_rate < 50 or avg_response_time > 15000:
            return HealthCheckResult(
                name="request_performance",
                status="critical",
                message=f"Critical performance - Success: {success_rate:.1f}%, Time: {avg_response_time:.0f}ms",
                details=request_metrics,
                timestamp=time.time()
            )
        elif success_rate < 80 or avg_response_time > 8000:
            return HealthCheckResult(
                name="request_performance",
                status="warning",
                message=f"Degraded performance - Success: {success_rate:.1f}%, Time: {avg_response_time:.0f}ms",
                details=request_metrics,
                timestamp=time.time()
            )
        else:
            return HealthCheckResult(
                name="request_performance",
                status="ok",
                message=f"Good performance - Success: {success_rate:.1f}%, Time: {avg_response_time:.0f}ms",
                details=request_metrics,
                timestamp=time.time()
            )
    
    def _check_error_rates(self) -> HealthCheckResult:
        """Health check for error rates."""
        metrics = self.metrics_collector.get_current_metrics()
        request_metrics = metrics.get("requests", {})
        
        total_requests = request_metrics.get("total", 0)
        failed_requests = request_metrics.get("failed", 0)
        
        if total_requests == 0:
            return HealthCheckResult(
                name="error_rates",
                status="ok",
                message="No requests have been executed yet",
                details={"total": 0, "failed": 0},
                timestamp=time.time()
            )
        
        error_rate = (failed_requests / total_requests) * 100
        
        if error_rate > 50:
            return HealthCheckResult(
                name="error_rates",
                status="critical",
                message=f"High error rate: {error_rate:.1f}%",
                details={"error_rate": error_rate, "failed": failed_requests, "total": total_requests},
                timestamp=time.time()
            )
        elif error_rate > 20:
            return HealthCheckResult(
                name="error_rates", 
                status="warning",
                message=f"Elevated error rate: {error_rate:.1f}%",
                details={"error_rate": error_rate, "failed": failed_requests, "total": total_requests},
                timestamp=time.time()
            )
        else:
            return HealthCheckResult(
                name="error_rates",
                status="ok",
                message=f"Low error rate: {error_rate:.1f}%",
                details={"error_rate": error_rate, "failed": failed_requests, "total": total_requests},
                timestamp=time.time()
            )
    
    def _check_system_resources(self) -> HealthCheckResult:
        """Health check for system resources."""
        try:
            process = psutil.Process()
            open_files = len(process.open_files())
            
            details = {
                "open_files": open_files,
                "max_open_files": self.limits.max_open_files
            }
            
            if open_files > self.limits.max_open_files:
                return HealthCheckResult(
                    name="system_resources",
                    status="warning",
                    message=f"Too many open files: {open_files} > {self.limits.max_open_files}",
                    details=details,
                    timestamp=time.time()
                )
            else:
                return HealthCheckResult(
                    name="system_resources",
                    status="ok",
                    message=f"Normal system resources: {open_files} open files",
                    details=details,
                    timestamp=time.time()
                )
        except Exception as e:
            return HealthCheckResult(
                name="system_resources",
                status="warning",
                message=f"Error checking resources: {str(e)}",
                details={"error": str(e)},
                timestamp=time.time()
            )
    
    def _evaluate_and_act(self, health_report: Dict[str, Any]):
        """Evaluate health report and take corrective actions."""
        checks = health_report.get("checks", {})

        # Check conditions that require action
        for check_name, check_result in checks.items():
            status = check_result.get("status")
            
            if status == "critical":
                self._handle_critical_condition(check_name, check_result)
            elif status == "warning":
                self._handle_warning_condition(check_name, check_result)
    
    def _handle_critical_condition(self, check_name: str, check_result: Dict[str, Any]):
        """Handle critical conditions."""
        logger.error(f"Critical condition detected: {check_name}", extra={
            "check": check_name,
            "message": check_result.get("message"),
            "details": check_result.get("details")
        })

        # Map check to corrective action
        action_map = {
            "memory_usage": "high_memory",
            "request_performance": "poor_performance", 
            "error_rates": "high_error_rate"
        }
        
        action_key = action_map.get(check_name)
        if action_key and action_key in self._corrective_actions:
            try:
                self._corrective_actions[action_key](check_result)
            except Exception as e:
                logger.error(f"Error executing corrective action {action_key}: {e}")

    def _handle_warning_condition(self, check_name: str, check_result: Dict[str, Any]):
        """Handle warning conditions."""
        logger.warning(f"Warning condition detected: {check_name}", extra={
            "check": check_name,
            "message": check_result.get("message"),
            "details": check_result.get("details")
        })
    
    def _action_cleanup_memory(self, check_result: Dict[str, Any]):
        """Corrective action: memory cleanup."""
        details = check_result.get("details", {})
        current_mb = details.get("rss_mb", 0)

        # Determine if aggressive cleanup is needed
        aggressive = current_mb > self.limits.max_memory_mb * 0.95

        logger.info(f"Executing memory cleanup ({'aggressive' if aggressive else 'basic'})")

        cleanup_result = self.memory_optimizer.cleanup_memory(aggressive=aggressive)

        logger.info("Memory cleanup corrective action executed", extra=cleanup_result)

    def _action_adjust_rate_limiting(self, check_result: Dict[str, Any]):
        """Corrective action: adjust rate limiting."""
        logger.info("Adjusting rate limiting due to high error rate")

        # Increase rate limiter delay to reduce pressure
        current_limits = self.rate_limiter.get_current_limits()
        new_delay = min(current_limits["current_delay"] * 2, 30.0)
        
        self.rate_limiter.current_delay = new_delay
        
        logger.info("Rate limiting ajustado", extra={
            "old_delay": current_limits["current_delay"],
            "new_delay": new_delay,
            "reason": "high_error_rate_action"
        })
    
    def _action_optimize_requests(self, check_result: Dict[str, Any]):
        """Corrective action: optimize requests."""
        logger.info("Optimizing requests due to degraded performance")

        # Reduce concurrency and increase delays
        if hasattr(self.rate_limiter, '_semaphore'):
            # We cannot change the semaphore dynamically, but we can adjust delay
            current_limits = self.rate_limiter.get_current_limits() 
            new_delay = min(current_limits["current_delay"] * 1.5, 20.0)
            self.rate_limiter.current_delay = new_delay

            logger.info("Requests optimized", extra={
                "new_delay": new_delay,
                "reason": "poor_performance_action"
            })
    
    def get_rate_limiter(self) -> AdaptiveRateLimiter:
        """Return instance of the rate limiter for use in other modules."""
        return self.rate_limiter
    
    def get_memory_optimizer(self) -> MemoryOptimizer:
        """Return instance of the memory optimizer."""
        return self.memory_optimizer


# Global instance of the health monitor
_default_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor(resource_limits: Optional[ResourceLimits] = None) -> HealthMonitor:
    """Return global instance of the health monitor."""
    global _default_health_monitor
    
    if _default_health_monitor is None:
        _default_health_monitor = HealthMonitor(resource_limits)
        _default_health_monitor.start_monitoring()
    
    return _default_health_monitor


def get_adaptive_rate_limiter() -> AdaptiveRateLimiter:
    """Return adaptive rate limiter from the health monitor."""
    return get_health_monitor().get_rate_limiter()


def setup_health_monitoring(resource_limits: Optional[ResourceLimits] = None):
    """Set up health monitoring with custom limits."""
    monitor = get_health_monitor(resource_limits)

    logger.info("Health monitoring system set up", extra={
        "resource_limits": monitor.limits.to_dict()
    })