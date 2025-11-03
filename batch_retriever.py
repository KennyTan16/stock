"""
Polygon.io Batch Data Retriever with Rate Limiting

This script retrieves previous day closing data for large numbers of tickers
while respecting API rate limits (100 requests per second).

Features:
- Processes tickers in batches of 100 every 15 seconds
- Uses previous day bar endpoint for closing prices
- Saves results to CSV with timestamps
- Resumes from where it left off if interrupted
- Progress tracking and error handling
"""

import requests
import csv
import time
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional
import json

class PolygonBatchRetriever:
    def __init__(self, api_key: str, batch_size: int = 100, delay_seconds: int = 15):
        self.api_key = api_key
        self.batch_size = batch_size
        self.delay_seconds = delay_seconds
        self.base_url = "https://api.polygon.io/v2/aggs/ticker"
        self.results = []
        self.processed_count = 0
        self.failed_tickers = []
        
    def read_tickers_from_csv(self, filepath: str) -> List[str]:
        """Read ticker symbols from CSV file"""
        tickers = []
        try:
            with open(filepath, 'r', encoding='utf-8') as file:
                csv_reader = csv.reader(file)
                for row in csv_reader:
                    if row and row[0].strip():
                        ticker = row[0].strip().upper()
                        if ticker != "SYMBOL":  # Skip header
                            tickers.append(ticker)
            print(f"✅ Loaded {len(tickers)} tickers from {filepath}")
            return tickers
        except Exception as e:
            print(f"❌ Error reading {filepath}: {e}")
            return []
    
    def get_previous_day_bar(self, ticker: str, target_date: str = None) -> Optional[Dict]:
        """
        Get previous day bar data for a single ticker
        Uses the previous day bar endpoint: /v2/aggs/ticker/{ticker}/prev
        """
        try:
            # Use previous day endpoint
            url = f"{self.base_url}/{ticker}/prev"
            
            params = {
                'adjusted': 'true',
                'apikey': self.api_key
            }
            
            # Add date parameter if specified
            if target_date:
                params['date'] = target_date
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if 'results' in data and data['results'] and len(data['results']) > 0:
                    result = data['results'][0]  # Get first result
                    
                    # Extract the data we need
                    return {
                        'ticker': ticker,
                        'open': result.get('o', 0),
                        'high': result.get('h', 0),
                        'low': result.get('l', 0),
                        'close': result.get('c', 0),
                        'volume': result.get('v', 0),
                        'timestamp': result.get('t', 0),
                        'date': datetime.fromtimestamp(result.get('t', 0) / 1000).strftime('%Y-%m-%d') if result.get('t') else '',
                        'status': 'success'
                    }
                else:
                    print(f"⚠️  No data found for {ticker}")
                    return {
                        'ticker': ticker,
                        'status': 'no_data',
                        'error': 'No results returned'
                    }
            
            elif response.status_code == 429:  # Rate limited
                print(f"⏳ Rate limited for {ticker}, will retry...")
                return {
                    'ticker': ticker,
                    'status': 'rate_limited',
                    'error': f'HTTP {response.status_code}'
                }
            
            else:
                print(f"❌ API error for {ticker}: HTTP {response.status_code}")
                return {
                    'ticker': ticker,
                    'status': 'error',
                    'error': f'HTTP {response.status_code}: {response.text[:100]}'
                }
                
        except Exception as e:
            print(f"❌ Exception for {ticker}: {e}")
            return {
                'ticker': ticker,
                'status': 'exception',
                'error': str(e)
            }
    
    def process_batch(self, tickers_batch: List[str], batch_num: int, total_batches: int) -> List[Dict]:
        """Process a batch of tickers"""
        print(f"\n📦 Processing batch {batch_num}/{total_batches}")
        print(f"   Tickers: {len(tickers_batch)} ({tickers_batch[0]} to {tickers_batch[-1]})")
        
        batch_results = []
        success_count = 0
        
        for i, ticker in enumerate(tickers_batch, 1):
            print(f"   🔄 [{i:3d}/{len(tickers_batch)}] {ticker}...", end=" ")
            
            result = self.get_previous_day_bar(ticker)
            batch_results.append(result)
            
            if result and result.get('status') == 'success':
                print(f"✅ ${result['close']:.2f}")
                success_count += 1
            else:
                print(f"❌ {result.get('error', 'Failed') if result else 'No result'}")
                if result:
                    self.failed_tickers.append(result)
            
            # Small delay between individual requests to be respectful
            time.sleep(0.01)  # 10ms delay
        
        print(f"   📊 Batch complete: {success_count}/{len(tickers_batch)} successful")
        return batch_results
    
    def save_results_to_csv(self, results: List[Dict], output_file: str):
        """Save results to CSV file"""
        try:
            # Create output directory if needed
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                # Define fieldnames
                fieldnames = ['ticker', 'date', 'open', 'high', 'low', 'close', 'volume', 
                             'timestamp', 'status', 'error', 'retrieved_at']
                
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                # Add timestamp to each record
                retrieved_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                for result in results:
                    if result:  # Only write non-None results
                        result['retrieved_at'] = retrieved_at
                        # Fill missing fields with empty strings
                        for field in fieldnames:
                            if field not in result:
                                result[field] = ''
                        writer.writerow(result)
            
            print(f"💾 Saved {len(results)} results to {output_file}")
            
        except Exception as e:
            print(f"❌ Error saving to CSV: {e}")
    
    def save_progress(self, processed_count: int, total_count: int, output_dir: str):
        """Save progress to a JSON file for resuming"""
        progress_file = Path(output_dir) / "batch_progress.json"
        progress_data = {
            'processed_count': processed_count,
            'total_count': total_count,
            'timestamp': datetime.now().isoformat(),
            'completed_percentage': (processed_count / total_count) * 100 if total_count > 0 else 0
        }
        
        try:
            with open(progress_file, 'w') as f:
                json.dump(progress_data, f, indent=2)
        except Exception as e:
            print(f"⚠️  Could not save progress: {e}")
    
    def load_progress(self, output_dir: str) -> int:
        """Load previous progress if available"""
        progress_file = Path(output_dir) / "batch_progress.json"
        
        try:
            if progress_file.exists():
                with open(progress_file, 'r') as f:
                    progress_data = json.load(f)
                processed_count = progress_data.get('processed_count', 0)
                print(f"📂 Resuming from previous progress: {processed_count} tickers processed")
                return processed_count
        except Exception as e:
            print(f"⚠️  Could not load progress: {e}")
        
        return 0
    
    def run_batch_processing(self, tickers_file: str, output_dir: str = "batch_results"):
        """Main batch processing function"""
        
        print("🚀 Starting Polygon.io Batch Data Retrieval")
        print("=" * 50)
        
        # Load tickers
        all_tickers = self.read_tickers_from_csv(tickers_file)
        
        if not all_tickers:
            print("❌ No tickers to process")
            return
        
        # Load previous progress
        start_index = self.load_progress(output_dir)
        
        # Skip already processed tickers
        remaining_tickers = all_tickers[start_index:]
        
        print(f"📊 Processing Configuration:")
        print(f"   Total tickers: {len(all_tickers)}")
        print(f"   Already processed: {start_index}")
        print(f"   Remaining: {len(remaining_tickers)}")
        print(f"   Batch size: {self.batch_size}")
        print(f"   Delay between batches: {self.delay_seconds} seconds")
        
        if not remaining_tickers:
            print("✅ All tickers already processed!")
            return
        
        # Calculate batches
        total_batches = (len(remaining_tickers) + self.batch_size - 1) // self.batch_size
        
        print(f"   Total batches: {total_batches}")
        print(f"   Estimated time: {total_batches * self.delay_seconds / 60:.1f} minutes")
        
        # Create output directory
        Path(output_dir).mkdir(exist_ok=True)
        
        # Generate output filename with timestamp
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = Path(output_dir) / f"previous_day_data_{timestamp}.csv"
        
        print(f"\n📁 Output file: {output_file}")
        print(f"⏰ Starting at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        input("\n⏳ Press Enter to start batch processing...")
        
        all_results = []
        
        try:
            for batch_num in range(1, total_batches + 1):
                start_idx = (batch_num - 1) * self.batch_size
                end_idx = min(start_idx + self.batch_size, len(remaining_tickers))
                
                batch_tickers = remaining_tickers[start_idx:end_idx]
                
                # Process this batch
                batch_results = self.process_batch(batch_tickers, batch_num, total_batches)
                all_results.extend(batch_results)
                
                # Update progress
                self.processed_count = start_index + end_idx
                self.save_progress(self.processed_count, len(all_tickers), output_dir)
                
                # Save intermediate results
                if batch_num % 5 == 0 or batch_num == total_batches:  # Save every 5 batches or at the end
                    temp_output = Path(output_dir) / f"temp_results_batch_{batch_num}.csv"
                    self.save_results_to_csv(all_results, temp_output)
                
                # Show progress
                progress_pct = (batch_num / total_batches) * 100
                print(f"\n📈 Progress: {batch_num}/{total_batches} batches ({progress_pct:.1f}%)")
                print(f"   Processed: {self.processed_count}/{len(all_tickers)} tickers")
                
                # Wait before next batch (except for the last one)
                if batch_num < total_batches:
                    print(f"⏳ Waiting {self.delay_seconds} seconds before next batch...")
                    time.sleep(self.delay_seconds)
        
        except KeyboardInterrupt:
            print(f"\n⏹️  Batch processing interrupted by user")
            print(f"📊 Processed {len(all_results)} tickers before interruption")
        
        # Save final results
        print(f"\n💾 Saving final results...")
        self.save_results_to_csv(all_results, output_file)
        
        # Summary
        successful_results = [r for r in all_results if r and r.get('status') == 'success']
        
        print(f"\n🎉 BATCH PROCESSING COMPLETE!")
        print("=" * 50)
        print(f"📊 Summary:")
        print(f"   Total processed: {len(all_results)}")
        print(f"   Successful: {len(successful_results)}")
        print(f"   Failed: {len(self.failed_tickers)}")
        print(f"   Success rate: {len(successful_results)/len(all_results)*100:.1f}%" if all_results else "0%")
        print(f"📁 Results saved to: {output_file}")
        
        # Show sample of successful results
        if successful_results:
            print(f"\n📋 Sample Results:")
            for result in successful_results[:5]:
                print(f"   {result['ticker']}: ${result['close']:.2f} ({result['date']})")
            if len(successful_results) > 5:
                print(f"   ... and {len(successful_results) - 5} more")

def main():
    """Main function"""
    
    # Configuration
    API_KEY = "3z93jv2EOJ9d7KrEbdnXzCaBfUQJBBoW"  # Your Polygon API key
    TICKERS_FILE = "tickers.csv"  # Input CSV file with tickers
    BATCH_SIZE = 100  # Process 100 tickers per batch (respects rate limit)
    DELAY_SECONDS = 15  # Wait 15 seconds between batches
    OUTPUT_DIR = "batch_results"  # Output directory
    
    # Create batch retriever
    retriever = PolygonBatchRetriever(
        api_key=API_KEY,
        batch_size=BATCH_SIZE,
        delay_seconds=DELAY_SECONDS
    )
    
    # Run batch processing
    retriever.run_batch_processing(TICKERS_FILE, OUTPUT_DIR)

if __name__ == "__main__":
    main()