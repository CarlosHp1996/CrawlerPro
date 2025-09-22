"""
Robust retry system for MercadoLivre Crawler.

This module implements advanced retry strategies with exponential 
backoff, jitter, circuit breaker, and different retry policies based on the error type.
"""

import asyncio
import random
import time
from typing import Callable, Any, Optional, List, Type, Dict, Union
from functools import wraps
import logging
from enum import Enum

from .exceptions import (
    NetworkException, 
    BlockedException, 
    RateLimitException,
    CrawlerBaseException
)


class BackoffStrategy(Enum):
    """Available backoff strategies."""
    LINEAR = "linear"
    EXPONENTIAL = "exponential" 
    FIBONACCI = "fibonacci"
    FIXED = "fixed"


class RetryPolicy:
    """Configuration for retry policy.

    Defines when and how to retry based on the type of exception
    and the context of the operation.
    """
    
    def __init__(self,
                 max_attempts: int = 3,
                 base_delay: float = 1.0,
                 max_delay: float = 60.0,
                 backoff_strategy: BackoffStrategy = BackoffStrategy.EXPONENTIAL,
                 jitter: bool = True,
                 retryable_exceptions: Optional[List[Type[Exception]]] = None,
                 non_retryable_exceptions: Optional[List[Type[Exception]]] = None,
                 retry_on_status_codes: Optional[List[int]] = None,
                 circuit_breaker_threshold: int = 5):
        
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_strategy = backoff_strategy
        self.jitter = jitter

        # Exceptions that should be retried by default
        self.retryable_exceptions = retryable_exceptions or [
            NetworkException,
            RateLimitException,
            ConnectionError,
            TimeoutError,
        ]

        # Exceptions that should NOT be retried
        self.non_retryable_exceptions = non_retryable_exceptions or [
            BlockedException,  # Blocking requires a change of strategy, not a retry
            ValueError,
            TypeError,
        ]
        
        # HTTP status codes that should be retried
        self.retry_on_status_codes = retry_on_status_codes or [
            429,  # Too Many Requests
            500,  # Internal Server Error
            502,  # Bad Gateway
            503,  # Service Unavailable
            504,  # Gateway Timeout
        ]
        
        self.circuit_breaker_threshold = circuit_breaker_threshold
        self._failure_count = 0
        self._circuit_open = False
        self._last_failure_time = 0


    def should_retry(self, exception: Exception, attempt: int) -> bool:
        """
        Determines whether to retry based on the exception and current attempt.
        
        Args:
            exception: Occurred exception
            attempt: Current attempt number (1-indexed)

        Returns:
            True if should retry, False otherwise
        """
        # Check circuit breaker
        if self._circuit_open:
            if time.time() - self._last_failure_time > 60:  # Reset after 1 minute
                self._circuit_open = False
                self._failure_count = 0
            else:
                return False
        
        # Check attempt limit
        if attempt >= self.max_attempts:
            return False

        # Check if it's a non-retryable exception
        for exc_type in self.non_retryable_exceptions:
            if isinstance(exception, exc_type):
                return False

        # Check if it's a retryable exception
        for exc_type in self.retryable_exceptions:
            if isinstance(exception, exc_type):
                return True

        # Check HTTP status codes for NetworkException
        if isinstance(exception, NetworkException):
            status_code = exception.context.get('status_code')
            if status_code in self.retry_on_status_codes:
                return True
        
        return False
    
    def calculate_delay(self, attempt: int) -> float:
        """
        Calculates delay for the next attempt.
        
        Args:
            attempt: Current attempt number (1-indexed)

        Returns:
            Delay in seconds
        """
        if self.backoff_strategy == BackoffStrategy.FIXED:
            delay = self.base_delay
        elif self.backoff_strategy == BackoffStrategy.LINEAR:
            delay = self.base_delay * attempt
        elif self.backoff_strategy == BackoffStrategy.EXPONENTIAL:
            delay = self.base_delay * (2 ** (attempt - 1))
        elif self.backoff_strategy == BackoffStrategy.FIBONACCI:
            delay = self.base_delay * self._fibonacci(attempt)
        else:
            delay = self.base_delay

        # Apply jitter to avoid thundering herd
        if self.jitter:
            delay *= (0.5 + random.random() * 0.5)

        # Limit maximum delay
        return min(delay, self.max_delay)
    
    def record_failure(self):
        """Records a failure for the circuit breaker."""
        self._failure_count += 1
        self._last_failure_time = time.time()
        
        if self._failure_count >= self.circuit_breaker_threshold:
            self._circuit_open = True
    
    def record_success(self):
        """Records a success, resetting the circuit breaker."""
        self._failure_count = 0
        self._circuit_open = False
    
    @staticmethod
    def _fibonacci(n: int) -> int:
        """Calculates Fibonacci number for backoff."""
        if n <= 2:
            return 1
        a, b = 1, 1
        for _ in range(3, n + 1):
            a, b = b, a + b
        return b


class RetryManager:
    """
    Main manager for the retry system.

    Coordinates retry policies, logging, and metrics.
    """
    
    def __init__(self, default_policy: Optional[RetryPolicy] = None):
        self.default_policy = default_policy or RetryPolicy()
        self.logger = logging.getLogger(__name__)
        self.metrics = {
            "total_attempts": 0,
            "successful_retries": 0,
            "failed_after_retries": 0,
            "circuit_breaker_activations": 0
        }
    
    async def execute_with_retry(self,
                                func: Callable,
                                *args,
                                policy: Optional[RetryPolicy] = None,
                                context: Optional[Dict[str, Any]] = None,
                                **kwargs) -> Any:
        """
        Executes a function with automatic retry.
        
        Args:
            func: Function to execute (can be sync or async)
            *args: Positional arguments for the function
            policy: Specific retry policy (uses default if None)
            context: Additional context for logging
            **kwargs: Keyword arguments for the function

        Returns:
            Result of the function

        Raises:
            Exception: Last exception if all attempts fail
        """
        policy = policy or self.default_policy
        context = context or {}
        last_exception = None
        
        for attempt in range(1, policy.max_attempts + 1):
            try:
                self.metrics["total_attempts"] += 1
                
                # Execute function (async or sync)
                if asyncio.iscoroutinefunction(func):
                    result = await func(*args, **kwargs)
                else:
                    result = func(*args, **kwargs)
                
                # Success - reset circuit breaker and return
                policy.record_success()
                
                if attempt > 1:
                    self.metrics["successful_retries"] += 1
                    self.logger.info(f"Sucesso após {attempt} tentativas", extra=context)
                
                return result
                
            except Exception as e:
                last_exception = e
                policy.record_failure()

                # Log error
                self.logger.warning(
                    f"Attempt {attempt}/{policy.max_attempts} failed: {str(e)}",
                    extra={**context, "attempt": attempt, "exception_type": type(e).__name__}
                )

                # Check if should retry
                if not policy.should_retry(e, attempt):
                    self.logger.error(
                        f"Not retrying - Non-retryable exception or limit reached",
                        extra={**context, "exception_type": type(e).__name__}
                    )
                    break

                # Calculate and wait for delay
                if attempt < policy.max_attempts:
                    delay = policy.calculate_delay(attempt)
                    self.logger.info(
                        f"Waiting {delay:.2f}s before next attempt",
                        extra={**context, "delay": delay, "next_attempt": attempt + 1}
                    )
                    await asyncio.sleep(delay)

        # All attempts failed
        self.metrics["failed_after_retries"] += 1
        
        if policy._circuit_open:
            self.metrics["circuit_breaker_activations"] += 1
            self.logger.error("Circuit breaker activated", extra=context)

        # Re-raise last exception
        raise last_exception
    
    def get_metrics(self) -> Dict[str, Any]:
        """Returns metrics from the retry system."""
        total = self.metrics["total_attempts"]
        if total > 0:
            success_rate = (total - self.metrics["failed_after_retries"]) / total * 100
            retry_rate = self.metrics["successful_retries"] / total * 100
        else:
            success_rate = retry_rate = 0.0
        
        return {
            **self.metrics,
            "success_rate_percent": round(success_rate, 2),
            "retry_success_rate_percent": round(retry_rate, 2)
        }


# Global instance of the retry manager
_default_retry_manager: Optional[RetryManager] = None


def get_retry_manager() -> RetryManager:
    """Gets global instance of the retry manager."""
    global _default_retry_manager
    
    if _default_retry_manager is None:
        _default_retry_manager = RetryManager()
    
    return _default_retry_manager


def with_retry(policy: Optional[RetryPolicy] = None,
               context: Optional[Dict[str, Any]] = None):
    """
    Decorator to add automatic retry to functions.
    
    Args:
        policy: Specific retry policy
        context: Additional context for logging

    Example:
        @with_retry(RetryPolicy(max_attempts=5))
        async def fetch_data():
            # Code that may fail
            pass
    """ 
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            retry_manager = get_retry_manager()
            return await retry_manager.execute_with_retry(
                func, *args, policy=policy, context=context, **kwargs
            )
        return wrapper
    return decorator


# Predefined policies for common scenarios
NETWORK_RETRY_POLICY = RetryPolicy(
    max_attempts=5,
    base_delay=2.0,
    max_delay=60.0,
    backoff_strategy=BackoffStrategy.EXPONENTIAL,
    retryable_exceptions=[NetworkException, ConnectionError, TimeoutError]
)

RATE_LIMIT_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    base_delay=30.0,  # Higher delay for rate limit
    max_delay=300.0,
    backoff_strategy=BackoffStrategy.LINEAR,
    retryable_exceptions=[RateLimitException]
)

GENTLE_RETRY_POLICY = RetryPolicy(
    max_attempts=2,
    base_delay=1.0,
    max_delay=10.0,
    backoff_strategy=BackoffStrategy.FIXED,
    jitter=False
)