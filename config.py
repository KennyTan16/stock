"""
Batch Processing Configuration

Adjust these settings based on your needs and API limits.
"""

# API Configuration
API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"

# Rate Limiting Configuration
BATCH_SIZE = 50 # Tickers per batch (stay under 100 req/sec limit)
DELAY_SECONDS = 5  # Seconds between batches (allows for 100 req/sec)

# File Configuration
TICKERS_FILE = "tickers.csv"  # Input file with tickers (change to "tickers_7000.csv" for full dataset)
OUTPUT_DIR = "batch_results"  # Directory to save results

# Processing Configuration
TARGET_TIME = "15:59"  # Target time to retrieve data (3:59 PM - just before market close)
SAVE_FREQUENCY = 5  # Save intermediate results every N batches

# API Endpoint Configuration
USE_PREVIOUS_DAY = True  # Use previous day endpoint (recommended for closing prices)