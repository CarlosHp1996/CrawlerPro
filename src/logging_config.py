"""
Configurable logging system for MercadoLivre Crawler.

This module provides advanced logging configuration with different levels,
custom formatters, file rotation, and intelligent filtering.
"""

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
import json


class CrawlerFormatter(logging.Formatter):
    """
    Custom formatter for crawler logs.

    Adds crawling-specific context such as search_term, page_number, etc.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        # Add ISO timestamp
        record.timestamp = datetime.utcnow().isoformat() + 'Z'

        # Extract crawler context if available
        if hasattr(record, 'search_term'):
            record.search_context = f"[{record.search_term}]"
        else:
            record.search_context = ""
            
        if hasattr(record, 'page_number'):
            record.page_context = f"[Página {record.page_number}]"
        else:
            record.page_context = ""
        
        # Standard format
        return super().format(record)


class JSONFormatter(logging.Formatter):
    """
    JSON formatter for structured logs.

    Useful for automated analysis and integration with monitoring systems.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + 'Z',
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }

        # Add extra context if available
        if hasattr(record, 'search_term'):
            log_entry['search_term'] = record.search_term
        if hasattr(record, 'page_number'):
            log_entry['page_number'] = record.page_number
        if hasattr(record, 'products_found'):
            log_entry['products_found'] = record.products_found
        if hasattr(record, 'execution_time'):
            log_entry['execution_time'] = record.execution_time

        # Add exception info if available
        if record.exc_info:
            log_entry['exception'] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info)
            }
        
        return json.dumps(log_entry, ensure_ascii=False)


class CrawlerLogger:
    """
    Main class for configuring the logging system.

    Provides flexible configuration with multiple handlers, levels
    and formatters for different usage scenarios.
    """
    
    def __init__(self, name: str = "crawler", log_dir: Optional[Path] = None):
        self.logger = logging.getLogger(name)
        self.log_dir = log_dir or Path("logs")
        self.log_dir.mkdir(exist_ok=True)

        # Default configuration
        self._setup_default_config()
    
    def _setup_default_config(self):
        """Default logger configuration."""
        self.logger.setLevel(logging.INFO)

        # Remove existing handlers
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        
        # Console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_formatter = CrawlerFormatter(
            fmt='%(timestamp)s - %(levelname)-8s - %(search_context)s%(page_context)s %(message)s'
        )
        console_handler.setFormatter(console_formatter)
        self.logger.addHandler(console_handler)
        
        # File handler with rotation
        file_handler = logging.handlers.RotatingFileHandler(
            self.log_dir / "crawler.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_formatter = CrawlerFormatter(
            fmt='%(timestamp)s - %(levelname)-8s - %(name)s - %(funcName)s:%(lineno)d - %(search_context)s%(page_context)s %(message)s'
        )
        file_handler.setFormatter(file_formatter)
        self.logger.addHandler(file_handler)
    
    def configure(self, level: str = "INFO", 
                 enable_console: bool = True,
                 enable_file: bool = True,
                 enable_json: bool = False,
                 file_max_bytes: int = 10*1024*1024,
                 backup_count: int = 5) -> 'CrawlerLogger':
        """
        Configures the logger with custom parameters.
        
        Args:
            level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            enable_console: Enable console output
            enable_file: Enable file logging
            enable_json: Enable structured logging in JSON
            file_max_bytes: Maximum log file size
            backup_count: NNumber of backups to keep

        Returns:
            Self for method chaining
        """
        # Configure level
        numeric_level = getattr(logging, level.upper())
        self.logger.setLevel(numeric_level)

        # Remove existing handlers
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
        
        # Console handler
        if enable_console:
            console_handler = logging.StreamHandler(sys.stdout)
            console_formatter = CrawlerFormatter(
                fmt='%(timestamp)s - %(levelname)-8s - %(search_context)s%(page_context)s %(message)s'
            )
            console_handler.setFormatter(console_formatter)
            console_handler.setLevel(numeric_level)
            self.logger.addHandler(console_handler)
        
        # File handler
        if enable_file:
            file_handler = logging.handlers.RotatingFileHandler(
                self.log_dir / "crawler.log",
                maxBytes=file_max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            file_formatter = CrawlerFormatter(
                fmt='%(timestamp)s - %(levelname)-8s - %(name)s - %(funcName)s:%(lineno)d - %(search_context)s%(page_context)s %(message)s'
            )
            file_handler.setFormatter(file_formatter)
            file_handler.setLevel(numeric_level)
            self.logger.addHandler(file_handler)

        # JSON handler for structured logs
        if enable_json:
            json_handler = logging.handlers.RotatingFileHandler(
                self.log_dir / "crawler_structured.json",
                maxBytes=file_max_bytes,
                backupCount=backup_count,
                encoding='utf-8'
            )
            json_handler.setFormatter(JSONFormatter())
            json_handler.setLevel(numeric_level)
            self.logger.addHandler(json_handler)
        
        return self
    
    def get_logger(self) -> logging.Logger:
        """Returns the configured logger."""
        return self.logger
    
    def log_crawler_start(self, search_term: str, max_pages: int, **kwargs):
        """Specific log for the start of crawling."""
        extra = {"search_term": search_term, **kwargs}
        self.logger.info(f"Starting crawling: term='{search_term}', pages={max_pages}", extra=extra)

    def log_page_processed(self, page_number: int, products_found: int, 
                          search_term: str, **kwargs):
        """Specific log for processed page."""
        extra = {
            "search_term": search_term,
            "page_number": page_number,
            "products_found": products_found,
            **kwargs
        }
        self.logger.info(f"Page processed: {products_found} products found", extra=extra)
    
    def log_crawler_complete(self, search_term: str, total_products: int, 
                            pages_crawled: int, execution_time: float, **kwargs):
        """Specific log for the completion of crawling."""
        extra = {
            "search_term": search_term,
            "products_found": total_products,
            "pages_crawled": pages_crawled,
            "execution_time": execution_time,
            **kwargs
        }
        self.logger.info(f"Crawling completed: {total_products} products found in {pages_crawled} pages ({execution_time:.2f}s)", extra=extra)

    def log_error_with_context(self, error: Exception, context: Dict[str, Any] = None):
        """Log error with structured context."""
        extra = context or {}

        # If it's a custom exception, use its context
        if hasattr(error, 'to_dict'):
            error_data = error.to_dict()
            extra.update(error_data['context'])
            self.logger.error(f"Error {error_data['error_code']}: {error_data['message']}",
                            exc_info=True, extra=extra)
        else:
            self.logger.error(f"Unhandled error: {str(error)}", exc_info=True, extra=extra)


# Global logger instance
_default_logger: Optional[CrawlerLogger] = None


def get_logger(name: str = "crawler") -> logging.Logger:
    """
    Convenient function to get configured logger.

    Args:
        name: Name of the logger

    Returns:
        Configured logger ready for use
    """
    global _default_logger
    
    if _default_logger is None:
        _default_logger = CrawlerLogger(name)
    
    return _default_logger.get_logger()


def configure_logging(level: str = "INFO", **kwargs) -> CrawlerLogger:
    """
    Convenient function to configure global logging.
    
    Args:
        level: logging level
        **kwargs: Arguments for CrawlerLogger.configure()

    Returns:
        Instance of the configured CrawlerLogger
    """
    global _default_logger
    
    _default_logger = CrawlerLogger()
    _default_logger.configure(level=level, **kwargs)
    
    return _default_logger