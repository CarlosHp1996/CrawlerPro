# CrawlerPro - Mercado Livre Scraper

## Description

Web scraping system to extract product data from Mercado Livre, developed with Crawl4ai.

## Project Structure

```
CrawlerPro/
├── src/                    # Main source code
│   ├── __init__.py
│   ├── crawler.py          # Main Crawler
│   ├── utils.py            # Utilities and export
│   └── models.py           # Data models
├── tests/                  # Automated tests
├── docs/                   # Documentation
├── scripts/                # Helper scripts
├── logs/                   # Log files
├── output/                 # JSON/Excel outputs
├── main.py                 # Main script
├── config.py               # Configurations
├── requirements.txt        # Dependencies
└── README.md               # This file

```

## Installation

### Prerequisites

- Python 3.8+
- pip

### Install dependencies

```bash
pip install -r requirements.txt
```

## Usage

### Basic usage

```bash
python main.py "iphone 15"
```

### Available parameters

- `search_term`: Search term (required)
- `--pages`: Number of pages to process (default: 3)
- `--output`: Output format: json, excel, both (default: both)
- `--json-output`: JSON output to stdout for .NET integration

### Examples

```bash
# Search 5 pages, save JSON only
python main.py "creatina" --pages 5 --output json

# .NET integration (JSON to stdout)
python main.py "whey protein" --json-output
```

## .NET Backend Integration

The crawler can be called from the .NET backend using the --json-output parameter:

```csharp
var process = new Process
{
    StartInfo = new ProcessStartInfo
    {
        FileName = "python",
        Arguments = $"main.py \"{searchTerm}\" --json-output",
        RedirectStandardOutput = true,
        UseShellExecute = false
    }
};
```

## Extracted Fields

Each product contains the following fields:

- `title`: Product title
- `price`: Price in cents (string for .NET compatibility)
- `original_price`: Original price (if discounted)
- `discount_percentage`: Discount percentage
- `seller`: Seller name
- `rating`: Rating (score)
- `reviews_count`: Number of reviews
- `shipping`: Shipping information
- `product_url`: Product URL
- `image_url`: High-quality image URL
- `installments`: Installment options
- `location`: Seller location

## Professional Features

### Advanced Error Handling System

The crawler implements a robust error handling system with:

- `Custom Exceptions`: Specific error types (NetworkException, BlockedException, etc.)
- `Automatic Retry`: Smart retry with exponential backoff and circuit breaker
- `Structured Logging`: JSON logs with detailed context and automatic rotation

```python
from src.exceptions import NetworkException, BlockedException
from src.retry_system import with_retry, NETWORK_RETRY_POLICY

@with_retry(NETWORK_RETRY_POLICY)
async def robust_request():
    # Sua lógica aqui
    pass
```

### Metrics and Monitoring System

Automatic collection of performance and system metrics:

- `System Metrics`: Memory usage, CPU, open files
- `Request Metrics`: Response time, success rate, throughput
- `Automatic Alerts`: Notifications under critical conditions
- `Performance Reports`: Detailed statistical analysis

```python
from src.metrics import get_metrics_collector

metrics = get_metrics_collector()
current_metrics = metrics.get_current_metrics()
performance_report = metrics.get_performance_report(last_minutes=10)
```

### Health Monitoring and Self-Optimization

Smart health monitoring system:

- `Automatic Health Checks`: Continuous system verification
- `Adaptive Rate Limiting`: Auto-adjust based on performance
- `Memory Optimization`: Automatic cleanup with configurable thresholds
- `Corrective Actions`: Automatic recovery from critical conditions

```python
from src.health_monitor import setup_health_monitoring, ResourceLimits

# Configure custom limits
limits = ResourceLimits(
    max_memory_mb=512.0,
    max_cpu_percent=80.0,
    max_concurrent_requests=10
)
setup_health_monitoring(limits)
```

### Advanced Logging Configuration

Professional logging system with multiple outputs:

```bash
# Run with custom log level
python main.py "creatina" --log-level DEBUG

# Logs are automatically saved in logs/ with daily rotation
# Console output can be disabled for integration
```

### Advanced Example

Run the demo script to see all functionalities:

```bash
python advanced_example.py
```

This script demonstrates:

- `Real-time monitoring`
- `Performance metrics`
- `Automatic health checks`
- `Adaptive rate limiting`
- `Memory optimization`

## Architecture

### Main Classes

- `MercadoLivreCrawler`: Main crawler class with integrated systems
- `FileExporter`: Utilities for JSON/Excel export
- `MetricsCollector`: Metrics collection and analysis
- `HealthMonitor`: Health monitoring and self-optimization
- `RetryManager`: Smart retry system
- `AdaptiveRateLimiter`: Rate limiting that adapts to performance

### Extraction Strategies

- `Support for multiple layouts (Poly-Card and Classic)`
- `Robust CSS selectors with fallbacks`
- `Image validation and processing`
- `Automatic price conversion to cents`
- `Automatic detection of blocking and rate limiting`

## Logs and Monitoring

Logs are automatically saved in the logs/ folder with daily rotation.
Outputs are saved in the output/ folder organized by format.

## Contribution

1. `Fork the project`
2. `Create a feature branch (git checkout -b feature/AmazingFeature)`
3. `Commit your changes (git commit -m 'Add some AmazingFeature')`
4. `Push to the branch (git push origin feature/AmazingFeature)`
5. `Open a Pull Request`

## License

This project is under the MIT license. See the LICENSE file for more details.

## Troubleshooting

### Common Issues

**Encoding error on Windows:**

- Make sure to use a UTF-8 compatible terminal
- Set PYTHONIOENCODING=utf-8

**Products not found:**

- Check if the search term is correct
- Mercado Livre may have changed the HTML structure

**Dependency errors:**

- Run pip install -r requirements.txt
- Use a virtual environment: python -m venv venv

## Contact

For questions or suggestions, open an issue in the repository.
