# -*- coding: utf-8 -*-
import pandas as pd
import json
import logging
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import List
from .models import CrawlerResult, ProductData

def _get_attr(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)

def _iter_products(result):
    prods = _get_attr(result, 'products', [])
    for p in prods:
        if isinstance(p, dict):
            yield p.copy()
        else:
            # dataclass/object simple
            yield vars(p).copy() if hasattr(p, '__dict__') else p


# Configure encoding UTF-8 for Windows
if sys.platform == "win32":
    os.environ['PYTHONIOENCODING'] = 'utf-8'

class FileExporter:
    """Class for exporting data"""
    
    @staticmethod
    def save_to_json(result: CrawlerResult, output_dir: Path) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        search_term = _get_attr(result, 'search_term', '') or ''
        safe_search_term = ''.join(c for c in search_term.replace(' ', '_') if c.isalnum() or c in ['_', '-'])
        filename = f"mercadolivre_{safe_search_term}_{timestamp}.json"
        filepath = output_dir / filename

        try:
            # Build JSON string according to type
            if hasattr(result, 'to_json'):
                json_str = result.to_json()
            else:
                json_str = json.dumps(result, ensure_ascii=False, indent=2)
            with open(filepath, 'w', encoding='utf-8', errors='replace') as f:
                f.write(json_str)
            return str(filepath)
        except Exception as e:
            print(f"Error saving JSON: {e}")
            # Fallback
            with open(filepath, 'w', encoding='utf-8', errors='replace') as f:
                f.write(json.dumps(result if isinstance(result, dict) else vars(result), ensure_ascii=False, indent=2))
            return str(filepath)

    
    @staticmethod
    def save_to_excel(result: CrawlerResult, output_dir: Path) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        search_term = _get_attr(result, 'search_term', '') or ''
        safe_search_term = ''.join(c for c in search_term.replace(' ', '_') if c.isalnum() or c in ['_', '-'])
        filename = f"mercadolivre_{safe_search_term}_{timestamp}.xlsx"
        filepath = output_dir / filename

        try:
            products_data = []
            for product in _iter_products(result):
                products_data.append(FileExporter._clean_special_chars(product))
            df_products = pd.DataFrame(products_data)

            summary_data = {
                'Search Term': [_get_attr(result, 'search_term', '')],
                'Total Products': [_get_attr(result, 'total_products', 0)],
                'Processed Pages': [_get_attr(result, 'pages_crawled', 0)],
                'Date/Time': [_get_attr(result, 'timestamp', '')],
                'Execution Time (s)': [_get_attr(result, 'execution_time', 0)],
                'Status': ['Success' if _get_attr(result, 'success', False) else 'Error'],
                'Error Message': [_get_attr(result, 'error_message', 'N/A') or 'N/A']
            }
            df_summary = pd.DataFrame(summary_data)

            with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
                df_summary.to_excel(writer, sheet_name='Summary', index=False)
                df_products.to_excel(writer, sheet_name='Products', index=False)
                for sheet_name in writer.sheets:
                    worksheet = writer.sheets[sheet_name]
                    for column in worksheet.columns:
                        max_length = 0
                        column_letter = column[0].column_letter
                        for cell in column:
                            try:
                                max_length = max(max_length, len(str(cell.value)))
                            except:
                                pass
                        worksheet.column_dimensions[column_letter].width = min(max_length + 2, 50)

            return str(filepath)
        except Exception as e:
            print(f"Error saving Excel: {e}")
            df_error = pd.DataFrame({
                'Error': [f'Failed to process data: {str(e)}'],
                'Search Term': [_get_attr(result, 'search_term', '')],
                'Status': ['Error']
            })
            df_error.to_excel(filepath, index=False)
            return str(filepath)

    
    @staticmethod
    def _clean_special_chars(obj):
        """Remove or replace special characters that can cause problems"""
        if isinstance(obj, dict):
            return {key: FileExporter._clean_special_chars(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [FileExporter._clean_special_chars(item) for item in obj]
        elif isinstance(obj, str):
            # Substitute problematic characters
            replacements = {
                'â†’': '->',
                'â†': '<-',
                'â†‘': '^',
                'â†“': 'v',
                'âœ“': 'ok',
                'âœ—': 'x',
                'â˜…': '*',
                'â€¢': '*',
                'â€¦': '...',
                '"': '"',
                '"': '"',
                ''': "'",
                ''': "'",
            }
            cleaned = obj
            for old, new in replacements.items():
                cleaned = cleaned.replace(old, new)
            
            # Remove remaining non-ASCII characters if necessary
            try:
                cleaned.encode('ascii')
                return cleaned
            except UnicodeEncodeError:
                return cleaned.encode('ascii', errors='replace').decode('ascii')
        else:
            return obj

def setup_logging(logs_dir: Path):
    """Configures logging with UTF-8"""
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    log_filename = datetime.now().strftime("crawler_%Y%m%d.log")
    log_filepath = logs_dir / log_filename

    # Configure formatters and handlers with UTF-8
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Handler for file with UTF-8
    file_handler = logging.FileHandler(log_filepath, encoding='utf-8', errors='replace')
    file_handler.setFormatter(formatter)

    # Handler for console with UTF-8
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    # If on Windows, configure console handler for UTF-8
    if sys.platform == "win32":
        try:
            console_handler.stream.reconfigure(encoding='utf-8', errors='replace')
        except:
            pass
    
    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        handlers=[file_handler, console_handler]
    )
    
    return logging.getLogger(__name__)