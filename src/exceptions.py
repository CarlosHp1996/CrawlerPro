"""
Custom exceptions for MercadoLivre Crawler.

This module defines specific exceptions for different types of errors
that may occur during the scraping process, allowing for more granular
handling and more informative error messages.
"""

from typing import Optional, Dict, Any


class CrawlerBaseException(Exception):
    """
    Base class for all crawler exceptions.
    
    Attributes:
        message (str): Error message
        error_code (str): Unique error code
        context (Dict[str, Any]): Additional context about the error
    """
    
    def __init__(self, message: str, error_code: str = None, context: Dict[str, Any] = None):
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.context = context or {}
        super().__init__(self.message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Converts the exception to a dictionary for serialization."""
        return {
            "error_type": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            "context": self.context
        }


class NetworkException(CrawlerBaseException):
    """
    Exception for network errors during crawling.

    Includes timeouts, connection failures, HTTP errors, etc.
    """
    
    def __init__(self, message: str, status_code: Optional[int] = None, 
                 url: Optional[str] = None, retry_count: int = 0):
        context = {
            "status_code": status_code,
            "url": url,
            "retry_count": retry_count
        }
        super().__init__(message, "NETWORK_ERROR", context)


class ParsingException(CrawlerBaseException):
    """
    Exception for parsing/extraction errors.

    Occurs when selectors fail or HTML structure changes.
    """
    
    def __init__(self, message: str, selector: Optional[str] = None, 
                 layout_type: Optional[str] = None, page_number: int = 0):
        context = {
            "selector": selector,
            "layout_type": layout_type,
            "page_number": page_number
        }
        super().__init__(message, "PARSING_ERROR", context)


class ValidationException(CrawlerBaseException):
    """
    Exception for data validation errors.

    Occurs when extracted data fails validation checks.
    """
    
    def __init__(self, message: str, field_name: Optional[str] = None, 
                 field_value: Any = None, validation_rule: Optional[str] = None):
        context = {
            "field_name": field_name,
            "field_value": field_value,
            "validation_rule": validation_rule
        }
        super().__init__(message, "VALIDATION_ERROR", context)


class ConfigurationException(CrawlerBaseException):
    """
    Exception for configuration errors.

    Occurs when configurations are invalid or missing.
    """
    
    def __init__(self, message: str, config_key: Optional[str] = None, 
                 config_value: Any = None):
        context = {
            "config_key": config_key,
            "config_value": config_value
        }
        super().__init__(message, "CONFIG_ERROR", context)


class RateLimitException(CrawlerBaseException):
    """
    Exception for when rate limit is reached.

    Indicates that it needs to wait before retrying.
    """
    
    def __init__(self, message: str, retry_after: Optional[int] = None, 
                 requests_made: int = 0, limit: int = 0):
        context = {
            "retry_after": retry_after,
            "requests_made": requests_made,
            "limit": limit
        }
        super().__init__(message, "RATE_LIMIT_ERROR", context)


class BlockedException(CrawlerBaseException):
    """
    Exception for when the crawler is detected/blocked.

    Indicates the need to change anti-blocking strategy.
    """
    
    def __init__(self, message: str, detection_type: Optional[str] = None, 
                 user_agent: Optional[str] = None, ip_address: Optional[str] = None):
        context = {
            "detection_type": detection_type,
            "user_agent": user_agent,
            "ip_address": ip_address
        }
        super().__init__(message, "BLOCKED_ERROR", context)


class DataQualityException(CrawlerBaseException):
    """
    Exception for data quality issues.

    Occurs when many fields are empty or suspicious data is detected.
    """
    
    def __init__(self, message: str, missing_fields: int = 0, 
                 total_fields: int = 0, quality_score: float = 0.0):
        context = {
            "missing_fields": missing_fields,
            "total_fields": total_fields,
            "quality_score": quality_score
        }
        super().__init__(message, "DATA_QUALITY_ERROR", context)