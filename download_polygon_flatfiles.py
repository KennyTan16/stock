"""
Download Polygon flat files from Massive.com S3 bucket using boto3
Downloads either DAILY or MINUTE aggregates to separate folders

Files are organized as: flatfiles/us_stocks_sip/{day_aggs_v1|minute_aggs_v1}/YYYY/MM/YYYY-MM-DD.csv.gz

Usage:
  python download_polygon_flatfiles.py --days 20                    # Daily aggregates (for stats)
  python download_polygon_flatfiles.py --days 12 --minute-data      # Minute aggregates (for backtest)
"""

import os
import sys
import gzip
import boto3
from datetime import datetime, timedelta
from pathlib import Path
from botocore.config import Config

# Configuration - directories will be set based on data type
OUTPUT_DIR_DAILY = Path("historical_data/polygon_flatfiles_daily")
OUTPUT_DIR_MINUTE = Path("historical_data/polygon_flatfiles_minute")
OUTPUT_DIR_DAILY.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR_MINUTE.mkdir(parents=True, exist_ok=True)

# Massive.com S3 credentials for Polygon flatfiles
ACCESS_KEY_ID = "beea43df-4b8b-4a9a-87e5-2029718458da"
SECRET_ACCESS_KEY = "lODb71RE6pKs8Vd7HVxUo3u2Up26o14S"
S3_ENDPOINT = "https://files.massive.com"
S3_BUCKET = "flatfiles"

def download_flatfile(s3_client, date_obj, output_dir, s3_prefix):
    """Download flatfile for a specific date from S3"""
    year = date_obj.strftime('%Y')
    month = date_obj.strftime('%m')
    date_str = date_obj.strftime('%Y-%m-%d')
    
    # S3 key: us_stocks_sip/{day_aggs_v1|minute_aggs_v1}/YYYY/MM/YYYY-MM-DD.csv.gz
    s3_key = f"{s3_prefix}/{year}/{month}/{date_str}.csv.gz"
    output_file = output_dir / f"{date_str}.csv.gz"
    
    # Skip if already exists and is valid
    if output_file.exists():
        # Verify it's valid
        try:
            with gzip.open(output_file, 'rt') as f:
                f.readline()
            file_size = output_file.stat().st_size / (1024 * 1024)
            print(f"[SKIP] {date_str}: already exists ({file_size:.1f} MB)")
            return True
        except:
            # File exists but is corrupted, delete it
            print(f"[DELETE] {date_str}: corrupted file, re-downloading...")
            output_file.unlink()
    
    print(f"[DOWNLOAD] {date_str}...", end=" ", flush=True)
    
    # Use a temporary file to avoid partial downloads
    temp_file = output_dir / f"{date_str}.csv.gz.tmp"
    
    # Track download progress
    class ProgressTracker:
        def __init__(self):
            self.size = 0
        
        def __call__(self, bytes_amount):
            self.size += bytes_amount
            mb = self.size / (1024 * 1024)
            print(f"\r[DOWNLOAD] {date_str}... {mb:.1f} MB", end="", flush=True)
    
    progress = ProgressTracker()
    
    try:
        # Download from S3 with callback to track progress
        s3_client.download_file(
            S3_BUCKET, 
            s3_key, 
            str(temp_file),
            Callback=progress,
            Config=boto3.s3.transfer.TransferConfig(use_threads=False)
        )
        
        print(" [VERIFYING]...", end="", flush=True)
        
        # Verify it's valid gzip
        try:
            with gzip.open(temp_file, 'rt') as f:
                # Just read first line to verify, don't read the whole file
                first_line = f.readline()
                if not first_line:
                    raise Exception("Empty file")
            
            # Move temp file to final location
            if output_file.exists():
                output_file.unlink()
            temp_file.rename(output_file)
            
            file_size = output_file.stat().st_size / (1024 * 1024)
            print(f"[OK] {file_size:.1f} MB")
            return True
        except Exception as e:
            print(f"[X] Invalid file: {e}")
            if temp_file.exists():
                temp_file.unlink()
            return False
            
    except Exception as e:
        error_msg = str(e)
        if "NoSuchKey" in error_msg or "404" in error_msg:
            print("[X] File not found (weekend/holiday?)")
        else:
            print(f"[X] Error: {error_msg[:50]}")
        if temp_file.exists():
            temp_file.unlink()
        return False

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Download Polygon flatfiles from Massive.com S3")
    parser.add_argument('--days', type=int, default=20, help="Number of days to download (default: 20)")
    parser.add_argument('--minute-data', action='store_true', help="Download minute-level data (for backtesting)")
    args = parser.parse_args()
    
    # Set directories and prefixes based on data type
    if args.minute_data:
        s3_prefix = "us_stocks_sip/minute_aggs_v1"
        output_dir = OUTPUT_DIR_MINUTE
        data_type = "MINUTE-level aggregates (for backtesting, ~20MB/file)"
    else:
        s3_prefix = "us_stocks_sip/day_aggs_v1"
        output_dir = OUTPUT_DIR_DAILY
        data_type = "DAILY aggregates (for historical stats, ~0.2MB/file)"
    
    print("="*80)
    print("POLYGON FLATFILES DOWNLOAD (via Massive.com S3)")
    print("="*80)
    print(f"Data Type: {data_type}")
    print(f"S3 Endpoint: {S3_ENDPOINT}")
    print(f"S3 Bucket: {S3_BUCKET}")
    print(f"S3 Prefix: {s3_prefix}")
    print(f"Output: {output_dir}")
    print(f"Days: {args.days}")
    print("="*80)
    print()
    
    session = boto3.Session(
        aws_access_key_id='beea43df-4b8b-4a9a-87e5-2029718458da',
        aws_secret_access_key='lODb71RE6pKs8Vd7HVxUo3u2Up26o14S',
    )

        # Create a client with your session and specify the endpoint
    s3_client = session.client(
        's3',
        endpoint_url='https://files.massive.com',
        config=Config(signature_version='s3v4'),
    )
    
    # Calculate date range (skip today, start from yesterday)
    end_date = datetime.now() - timedelta(days=1)
    
    successful = 0
    failed = 0
    
    for i in range(args.days):
        date_obj = end_date - timedelta(days=i)
        
        # Skip weekends (5=Saturday, 6=Sunday)
        if date_obj.weekday() >= 5:
            print(f"[SKIP] {date_obj.strftime('%Y-%m-%d')}: Weekend")
            continue
        
        if download_flatfile(s3_client, date_obj, output_dir, s3_prefix):
            successful += 1
        else:
            failed += 1
    
    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"[OK] Successful: {successful}")
    print(f"[X] Failed: {failed}")
    print(f"Total files: {len(list(output_dir.glob('*.csv.gz')))}")
    print(f"Location: {output_dir.resolve()}")
    print("="*80)
    print()
    print("Next step: Run 'python update_historical_stats.py' to generate stats cache")

if __name__ == "__main__":
    main()
