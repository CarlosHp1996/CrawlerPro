"""
Metrics and performance monitoring system for MercadoLibre Crawler.

This module implements detailed metrics collection, health checks,
resource monitoring, and real-time performance analysis.
"""

import time
import threading
import psutil
import gc
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque, defaultdict
import asyncio
import logging
from contextlib import asynccontextmanager

from .logging_config import get_logger

logger = get_logger(__name__)


@dataclass
class PerformanceSnapshot:
    """Performance snapshot at a specific moment."""
    timestamp: float
    memory_usage_mb: float
    cpu_percent: float
    open_files: int
    thread_count: int

    # Crawler-specific metrics
    active_requests: int = 0
    response_time_ms: float = 0.0
    success_rate: float = 100.0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert snapshot to dictionary."""
        return {
            "timestamp": self.timestamp,
            "memory_usage_mb": self.memory_usage_mb,
            "cpu_percent": self.cpu_percent,
            "open_files": self.open_files,
            "thread_count": self.thread_count,
            "active_requests": self.active_requests,
            "response_time_ms": self.response_time_ms,
            "success_rate": self.success_rate
        }


@dataclass
class RequestMetric:
    """MMetric for an individual request."""
    url: str
    start_time: float
    end_time: float
    success: bool
    response_size: int = 0
    error_type: Optional[str] = None
    retry_count: int = 0
    
    @property
    def duration_ms(self) -> float:
        """Duration of the request in milliseconds."""
        return (self.end_time - self.start_time) * 1000
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metric to dictionary."""
        return {
            "url": self.url,
            "duration_ms": self.duration_ms,
            "success": self.success,
            "response_size": self.response_size,
            "error_type": self.error_type,
            "retry_count": self.retry_count,
            "timestamp": self.start_time
        }


class MetricsCollector:
    """
    Main metrics collector for the system.

    Collects system, performance, and crawler metrics in a thread-safe manner
    and provides real-time statistical analysis.
    """
    
    def __init__(self, 
                 max_snapshots: int = 1000,
                 max_requests: int = 10000,
                 snapshot_interval: float = 5.0):
        """
        Initializes the metrics collector.
        
        Args:
            max_snapshots: Maximum number of snapshots to keep
            max_requests: Maximum number of request metrics to keep
            snapshot_interval: Interval between snapshots in seconds
        """
        self.max_snapshots = max_snapshots
        self.max_requests = max_requests
        self.snapshot_interval = snapshot_interval
        
        # Thread-safe collections
        self._snapshots = deque(maxlen=max_snapshots)
        self._requests = deque(maxlen=max_requests)
        self._active_requests: Dict[str, float] = {}

        # Global counters
        self._total_requests = 0
        self._successful_requests = 0
        self._failed_requests = 0
        self._total_bytes_downloaded = 0
        
        # Threading
        self._lock = threading.RLock()
        self._monitoring_thread = None
        self._stop_monitoring = threading.Event()
        self._process = psutil.Process()

        # Alert system
        self._alert_callbacks: List[Callable] = []
        self._last_alert_time = defaultdict(float)

        logger.info("Metrics collector initialized", extra={
            "max_snapshots": max_snapshots,
            "max_requests": max_requests,
            "snapshot_interval": snapshot_interval
        })
    
    def start_monitoring(self):
        """Starts automatic background monitoring."""
        if self._monitoring_thread and self._monitoring_thread.is_alive():
            return
        
        self._stop_monitoring.clear()
        self._monitoring_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True,
            name="MetricsMonitor"
        )
        self._monitoring_thread.start()

        logger.info("Automatic monitoring started")

    def stop_monitoring(self):
        """Stops automatic monitoring."""
        self._stop_monitoring.set()
        
        if self._monitoring_thread:
            self._monitoring_thread.join(timeout=2.0)

        logger.info("Automatic monitoring stopped")

    def _monitoring_loop(self):
        """Main monitoring loop."""
        while not self._stop_monitoring.wait(self.snapshot_interval):
            try:
                self._collect_system_snapshot()
                self._check_alerts()
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
    
    def _collect_system_snapshot(self):
        """Collects a snapshot of the system metrics."""
        try:
            # System metrics
            memory_info = self._process.memory_info()
            memory_mb = memory_info.rss / 1024 / 1024
            
            cpu_percent = self._process.cpu_percent()
            open_files = len(self._process.open_files())
            thread_count = self._process.num_threads()

            # Crawler-specific metrics
            with self._lock:
                active_requests = len(self._active_requests)

                # Calculate average response time of the last 10 requests
                recent_requests = list(self._requests)[-10:]
                avg_response_time = (
                    sum(r.duration_ms for r in recent_requests) / len(recent_requests)
                    if recent_requests else 0.0
                )

                # Calculate success rate of the last 50 requests
                recent_success = list(self._requests)[-50:]
                success_rate = (
                    sum(1 for r in recent_success if r.success) / len(recent_success) * 100
                    if recent_success else 100.0
                )

            # Create snapshot
            snapshot = PerformanceSnapshot(
                timestamp=time.time(),
                memory_usage_mb=memory_mb,
                cpu_percent=cpu_percent,
                open_files=open_files,
                thread_count=thread_count,
                active_requests=active_requests,
                response_time_ms=avg_response_time,
                success_rate=success_rate
            )
            
            with self._lock:
                self._snapshots.append(snapshot)
            
            logger.debug("System snapshot collected", extra={
                "memory_mb": memory_mb,
                "cpu_percent": cpu_percent,
                "active_requests": active_requests,
                "avg_response_time_ms": avg_response_time
            })
            
        except Exception as e:
            logger.error(f"Error collecting system snapshot: {e}")
    
    def start_request(self, url: str) -> str:
        """
        Marks the start of a request.

        Args:
            url: URL of the request

        Returns:
            Unique request ID to use in end_request
        """
        request_id = f"{url}_{time.time()}_{threading.get_ident()}"
        
        with self._lock:
            self._active_requests[request_id] = time.time()
            self._total_requests += 1
        
        logger.debug(f"Requisição iniciada: {url}", extra={
            "request_id": request_id,
            "url": url
        })
        
        return request_id
    
    def end_request(self, 
                   request_id: str, 
                   success: bool, 
                   response_size: int = 0,
                   error_type: Optional[str] = None,
                   retry_count: int = 0):
        """
        Marks the end of a request and collects metrics.

        Args:
            request_id: ID of the request returned by start_request
            success: Whether the request was successful
            response_size: Size of the response in bytes
            error_type: Type of error if success=False
            retry_count: NNumber of retries executed
        """
        end_time = time.time()
        
        with self._lock:
            start_time = self._active_requests.pop(request_id, end_time)

            # Extract URL from request_id
            url = request_id.split('_')[0] if '_' in request_id else "unknown"

            # Create request metric
            metric = RequestMetric(
                url=url,
                start_time=start_time,
                end_time=end_time,
                success=success,
                response_size=response_size,
                error_type=error_type,
                retry_count=retry_count
            )
            
            self._requests.append(metric)
            
            # Update global counters
            if success:
                self._successful_requests += 1
            else:
                self._failed_requests += 1
            
            self._total_bytes_downloaded += response_size
        
        logger.debug(f"Requisição finalizada: {url}", extra={
            "request_id": request_id,
            "success": success,
            "duration_ms": metric.duration_ms,
            "response_size": response_size,
            "retry_count": retry_count
        })
    
    @asynccontextmanager
    async def track_request(self, url: str):
        """
        Context manager to track requests easily.
        
        Example:
            async with metrics.track_request("https://example.com") as tracker:
                response = await make_request()
                tracker.set_response_size(len(response))
        """
        request_id = self.start_request(url)
        
        class RequestTracker:
            def __init__(self, metrics_collector, req_id):
                self.collector = metrics_collector
                self.request_id = req_id
                self.success = False
                self.response_size = 0
                self.error_type = None
                self.retry_count = 0
            
            def mark_success(self):
                self.success = True
            
            def mark_error(self, error_type: str):
                self.success = False
                self.error_type = error_type
            
            def set_response_size(self, size: int):
                self.response_size = size
            
            def set_retry_count(self, count: int):
                self.retry_count = count
        
        tracker = RequestTracker(self, request_id)
        
        try:
            yield tracker
            if not tracker.success:  # If not marked as success explicitly
                tracker.mark_success()
        except Exception as e:
            tracker.mark_error(type(e).__name__)
            raise
        finally:
            self.end_request(
                request_id,
                tracker.success,
                tracker.response_size,
                tracker.error_type,
                tracker.retry_count
            )
    
    def get_current_metrics(self) -> Dict[str, Any]:
        """Gets current system metrics."""
        with self._lock:
            latest_snapshot = self._snapshots[-1] if self._snapshots else None

            # Request statistics
            recent_requests = list(self._requests)[-100:]  # Last 100 requests
            
            if recent_requests:
                avg_response_time = sum(r.duration_ms for r in recent_requests) / len(recent_requests)
                success_rate = sum(1 for r in recent_requests if r.success) / len(recent_requests) * 100
                p95_response_time = sorted([r.duration_ms for r in recent_requests])[int(len(recent_requests) * 0.95)]
            else:
                avg_response_time = success_rate = p95_response_time = 0
            
            return {
                "system": latest_snapshot.to_dict() if latest_snapshot else {},
                "requests": {
                    "total": self._total_requests,
                    "successful": self._successful_requests,
                    "failed": self._failed_requests,
                    "success_rate_percent": success_rate,
                    "avg_response_time_ms": avg_response_time,
                    "p95_response_time_ms": p95_response_time,
                    "active_requests": len(self._active_requests),
                    "total_bytes_downloaded": self._total_bytes_downloaded
                },
                "timestamp": time.time()
            }
    
    def get_performance_report(self, 
                             last_minutes: int = 10) -> Dict[str, Any]:
        """
        Generates a detailed performance report.
        
        Args:
            last_minutes: Analyze last N minutes

        Returns:
            Complete performance report
        """
        cutoff_time = time.time() - (last_minutes * 60)
        
        with self._lock:
            # Filter snapshots and requests from the period
            recent_snapshots = [s for s in self._snapshots if s.timestamp >= cutoff_time]
            recent_requests = [r for r in self._requests if r.start_time >= cutoff_time]
        
        if not recent_snapshots or not recent_requests:
            return {"error": "Insufficient data for the requested period"}

        # System analysis
        memory_values = [s.memory_usage_mb for s in recent_snapshots]
        cpu_values = [s.cpu_percent for s in recent_snapshots]
        
        system_analysis = {
            "memory": {
                "avg_mb": sum(memory_values) / len(memory_values),
                "max_mb": max(memory_values),
                "min_mb": min(memory_values)
            },
            "cpu": {
                "avg_percent": sum(cpu_values) / len(cpu_values),
                "max_percent": max(cpu_values),
                "min_percent": min(cpu_values)
            }
        }

        # Request analysis
        response_times = [r.duration_ms for r in recent_requests]
        successful_requests = [r for r in recent_requests if r.success]
        failed_requests = [r for r in recent_requests if not r.success]
        
        if response_times:
            response_times.sort()
            p50 = response_times[len(response_times) // 2]
            p95 = response_times[int(len(response_times) * 0.95)]
            p99 = response_times[int(len(response_times) * 0.99)]
        else:
            p50 = p95 = p99 = 0
        
        request_analysis = {
            "total_requests": len(recent_requests),
            "successful_requests": len(successful_requests),
            "failed_requests": len(failed_requests),
            "success_rate_percent": len(successful_requests) / len(recent_requests) * 100 if recent_requests else 0,
            "response_times": {
                "avg_ms": sum(response_times) / len(response_times) if response_times else 0,
                "p50_ms": p50,
                "p95_ms": p95,
                "p99_ms": p99,
                "min_ms": min(response_times) if response_times else 0,
                "max_ms": max(response_times) if response_times else 0
            }
        }

        # Error analysis
        error_analysis = defaultdict(int)
        for request in failed_requests:
            error_type = request.error_type or "Unknown"
            error_analysis[error_type] += 1
        
        return {
            "period_minutes": last_minutes,
            "timestamp": time.time(),
            "system": system_analysis,
            "requests": request_analysis,
            "errors": dict(error_analysis),
            "snapshots_analyzed": len(recent_snapshots),
            "requests_analyzed": len(recent_requests)
        }
    
    def add_alert_callback(self, callback: Callable[[str, Dict[str, Any]], None]):
        """
        Adds a callback to be called when alerts are triggered.
        
        Args:
            callback: Function that receives (alert_type, context)
        """
        self._alert_callbacks.append(callback)
    
    def _check_alerts(self):
        """Checks alert conditions and triggers callbacks."""
        current_time = time.time()
        
        with self._lock:
            if not self._snapshots:
                return
            
            latest = self._snapshots[-1]

            # Alert: High memory usage (> 500MB)
            if latest.memory_usage_mb > 500:
                if current_time - self._last_alert_time["high_memory"] > 300:  # Max 1 alert per 5min
                    self._trigger_alert("high_memory", {
                        "memory_mb": latest.memory_usage_mb,
                        "threshold_mb": 500
                    })
                    self._last_alert_time["high_memory"] = current_time
            
            # Alert: CPU alto (> 80%)
            if latest.cpu_percent > 80:
                if current_time - self._last_alert_time["high_cpu"] > 300:
                    self._trigger_alert("high_cpu", {
                        "cpu_percent": latest.cpu_percent,
                        "threshold_percent": 80
                    })
                    self._last_alert_time["high_cpu"] = current_time

            # Alert: Low success rate (< 70%)
            if latest.success_rate < 70:
                if current_time - self._last_alert_time["low_success_rate"] > 300:
                    self._trigger_alert("low_success_rate", {
                        "success_rate": latest.success_rate,
                        "threshold_percent": 70
                    })
                    self._last_alert_time["low_success_rate"] = current_time
    
    def _trigger_alert(self, alert_type: str, context: Dict[str, Any]):
        """Triggers alerts for all registered callbacks."""
        logger.warning(f"Alert triggered: {alert_type}", extra={
            "alert_type": alert_type,
            "context": context
        })
        
        for callback in self._alert_callbacks:
            try:
                callback(alert_type, context)
            except Exception as e:
                logger.error(f"Error in alert callback: {e}")

    def force_garbage_collection(self):
        """Forces garbage collection and returns statistics."""
        before_objects = len(gc.get_objects())
        
        collected = gc.collect()
        
        after_objects = len(gc.get_objects())
        freed_objects = before_objects - after_objects
        
        logger.info("Coleta de lixo executada", extra={
            "collected_cycles": collected,
            "freed_objects": freed_objects,
            "remaining_objects": after_objects
        })
        
        return {
            "collected_cycles": collected,
            "freed_objects": freed_objects,
            "remaining_objects": after_objects
        }
    
    def get_health_status(self) -> Dict[str, Any]:
        """
        Checks overall health status of the system.
        
        Returns:
            Health status with indicators and recommendations
        """
        metrics = self.get_current_metrics()
        
        health_checks = []
        overall_status = "healthy"

        # Check 1: Memory usage
        memory_mb = metrics["system"].get("memory_usage_mb", 0)
        if memory_mb > 1000:
            health_checks.append({
                "check": "memory_usage",
                "status": "critical",
                "message": f"Memory usage very high: {memory_mb:.1f}MB",
                "recommendation": "Consider restarting the process or increasing resources"
            })
            overall_status = "critical"
        elif memory_mb > 500:
            health_checks.append({
                "check": "memory_usage",
                "status": "warning",
                "message": f"Memory usage moderate: {memory_mb:.1f}MB",
                "recommendation": "Monitor memory growth"
            })
            if overall_status == "healthy":
                overall_status = "warning"
        else:
            health_checks.append({
                "check": "memory_usage",
                "status": "ok",
                "message": f"Memory usage normal: {memory_mb:.1f}MB"
            })

        # Check 2: Success rate
        success_rate = metrics["requests"].get("success_rate_percent", 100)
        if success_rate < 50:
            health_checks.append({
                "check": "success_rate",
                "status": "critical",
                "message": f"Success rate very low: {success_rate:.1f}%",
                "recommendation": "Check connectivity and possible blocking"
            })
            overall_status = "critical"
        elif success_rate < 80:
            health_checks.append({
                "check": "success_rate",
                "status": "warning",
                "message": f"Success rate low: {success_rate:.1f}%",
                "recommendation": "Investigate recent errors and adjust settings"
            })
            if overall_status == "healthy":
                overall_status = "warning"
        else:
            health_checks.append({
                "check": "success_rate",
                "status": "ok",
                "message": f"Success rate good: {success_rate:.1f}%"
            })
        
        # Check 3: Response time
        avg_response = metrics["requests"].get("avg_response_time_ms", 0)
        if avg_response > 10000:  # 10s
            health_checks.append({
                "check": "response_time",
                "status": "warning",
                "message": f"Response time high: {avg_response:.0f}ms",
                "recommendation": "Check network latency and optimize requests"
            })
            if overall_status == "healthy":
                overall_status = "warning"
        else:
            health_checks.append({
                "check": "response_time",
                "status": "ok",
                "message": f"Response time good: {avg_response:.0f}ms"
            })
        
        return {
            "overall_status": overall_status,
            "timestamp": time.time(),
            "checks": health_checks,
            "metrics_summary": metrics,
            "uptime_seconds": time.time() - (self._snapshots[0].timestamp if self._snapshots else time.time())
        }


#Global Metrics Collector Instance
_default_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Gets global instance of metrics collector."""
    global _default_metrics_collector
    
    if _default_metrics_collector is None:
        _default_metrics_collector = MetricsCollector()
        _default_metrics_collector.start_monitoring()
    
    return _default_metrics_collector


def setup_default_alerts():
    """Configures default alerts for logging."""
    def alert_logger(alert_type: str, context: Dict[str, Any]):
        logger.warning(f"ALERT {alert_type.upper()}: {context}")

    get_metrics_collector().add_alert_callback(alert_logger)