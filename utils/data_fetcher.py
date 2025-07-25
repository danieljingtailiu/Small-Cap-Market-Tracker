"""
Data Fetcher for stock and options data
"""

import logging
import json
import time
import os
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
import numpy as np
from functools import lru_cache
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import pickle
from pathlib import Path
from scipy.stats import norm
import math
import random

logger = logging.getLogger(__name__)


class RateLimiter:
    """Rate limiter for API calls"""
    
    def __init__(self, max_requests_per_minute: int = 60):
        self.max_requests = max_requests_per_minute
        self.requests = []
        
    def wait_if_needed(self):
        """Wait if rate limit reached"""
        now = time.time()
        
        # Remove requests older than 1 minute
        self.requests = [req_time for req_time in self.requests if now - req_time < 60]
        
        if len(self.requests) >= self.max_requests:
            sleep_time = 60 - (now - self.requests[0]) + 1
            logger.info(f"Rate limit reached, sleeping for {sleep_time:.1f} seconds")
            time.sleep(sleep_time)
            self.requests = []
        
        self.requests.append(now)
        
    def add_jitter(self):
        """Add random jitter to requests"""
        jitter = random.uniform(0.1, 0.5)
        time.sleep(jitter)


class DataFetcher:
    """Data fetcher for stocks and options"""
    
    def __init__(self, config):
        self.config = config
        self.cache = {}
        self.cache_expiry = {}
        self.cache_dir = Path("data/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.fundamentals_cache_file = self.cache_dir / "fundamentals.pkl"
        self.fundamentals_cache = self._load_fundamentals_cache()
        self.fundamentals_cache_expiry_hours = 24  # Cache expiry in hours
        self.rate_limiter = RateLimiter(max_requests_per_minute=10)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        self.min_option_volume = 500
        self.min_option_oi = 1000
        self.max_bid_ask_spread = 0.25
        self.max_retries = 3
        self.retry_delay = 2

    def _load_fundamentals_cache(self):
        try:
            import pickle
            if self.fundamentals_cache_file.exists():
                with open(self.fundamentals_cache_file, 'rb') as f:
                    return pickle.load(f)
        except Exception:
            pass
        return {}

    def _save_fundamentals_cache(self):
        try:
            import pickle
            with open(self.fundamentals_cache_file, 'wb') as f:
                pickle.dump(self.fundamentals_cache, f)
        except Exception as e:
            logger.warning(f"Error saving fundamentals cache: {e}")

    def _load_pickle_cache(self, cache_file):
        try:
            if cache_file.exists():
                with open(cache_file, 'rb') as f:
                    return pickle.load(f)
        except Exception:
            pass
        return {}

    def _save_pickle_cache(self, cache_file, cache_dict):
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(cache_dict, f)
        except Exception as e:
            logger.warning(f"Error saving cache {cache_file}: {e}")

    def get_fundamentals(self, symbol: str) -> Dict:
        """Get fundamental data with defaults for missing values, using persistent cache"""
        try:
            now = time.time()
            cache_entry = self.fundamentals_cache.get(symbol)
            if cache_entry:
                data, ts = cache_entry
                if now - ts < self.fundamentals_cache_expiry_hours * 3600:
                    return data
            # Not cached or stale, fetch from yfinance
            ticker = yf.Ticker(symbol)
            info = ticker.info
            # Get financial data with error handling
            try:
                financials = ticker.quarterly_financials
                revenue_growth = None
                if not financials.empty and len(financials.columns) >= 2:
                    recent_revenue = financials.iloc[0, 0]
                    previous_revenue = financials.iloc[0, 1]
                    if previous_revenue and previous_revenue != 0:
                        revenue_growth = (recent_revenue - previous_revenue) / previous_revenue
            except:
                revenue_growth = None
            data = {
                'pe_ratio': info.get('forwardPE', info.get('trailingPE', 25)),
                'peg_ratio': info.get('pegRatio', 1.5),
                'price_to_book': info.get('priceToBook', 2),
                'revenue_growth': revenue_growth if revenue_growth else 0.10,
                'earnings_growth': info.get('earningsQuarterlyGrowth', 0.10),
                'profit_margin': info.get('profitMargins', 0.10),
                'institutional_ownership': info.get('heldPercentInstitutions', 0.20),
                'insider_ownership': info.get('heldPercentInsiders', 0.10),
                'short_ratio': info.get('shortRatio', 2),
                'beta': info.get('beta', 1.2)
            }
            self.fundamentals_cache[symbol] = (data, now)
            # Save cache every 100 updates to avoid excessive disk writes
            if len(self.fundamentals_cache) % 100 == 0:
                self._save_fundamentals_cache()
            return data
        except Exception as e:
            logger.error(f"Error getting fundamentals for {symbol}: {e}")
            # Return reasonable defaults
            data = {
                'pe_ratio': 25,
                'peg_ratio': 1.5,
                'price_to_book': 2,
                'revenue_growth': 0.10,
                'earnings_growth': 0.10,
                'profit_margin': 0.10,
                'institutional_ownership': 0.20,
                'insider_ownership': 0.10,
                'short_ratio': 2,
                'beta': 1.2
            }
            self.fundamentals_cache[symbol] = (data, time.time())
            return data

    # Save fundamentals cache at the end of enrichment (call this from market_scanner after enrichment)
    
    def _safe_yfinance_call(self, func, *args, **kwargs):
        """Safely call yfinance functions"""
        for attempt in range(self.max_retries):
            try:
                self.rate_limiter.wait_if_needed()
                result = func(*args, **kwargs)
                self.rate_limiter.add_jitter()
                return result
            except Exception as e:
                error_str = str(e).lower()
                
                # Suppress "possibly delisted" errors
                if "possibly delisted" in error_str:
                    return None
                    
                if "rate limit" in error_str or "429" in error_str:
                    wait_time = (attempt + 1) * self.retry_delay * 2
                    logger.warning(f"Rate limit hit, waiting {wait_time} seconds (attempt {attempt + 1})")
                    time.sleep(wait_time)
                    continue
                elif attempt == self.max_retries - 1:
                    raise
                else:
                    logger.warning(f"yfinance call failed, retrying: {e}")
                    time.sleep(self.retry_delay)
        
        return None
    
    def get_stocks_by_market_cap(self, min_cap: float, max_cap: float, min_volume: int) -> List[Dict]:
        """Get stocks filtered by market cap and volume using bulk data sources or CSV"""
        # Try CSV import first
        csv_file = Path('tickers.csv')
        if csv_file.exists():
            logger.info("Loading tickers from tickers.csv...")
            import pandas as pd
            df = pd.read_csv(csv_file)
            tickers = df['symbol'].dropna().unique().tolist()
            stocks = []
            for symbol in tickers:
                try:
                    quote = self.get_quote(symbol)
                    # Try to get market cap from yfinance info if available
                    try:
                        ticker_obj = yf.Ticker(symbol)
                        info = ticker_obj.info
                        market_cap = info.get('marketCap', quote.get('price', 0) * quote.get('volume', 0))
                    except Exception:
                        market_cap = quote.get('price', 0) * quote.get('volume', 0)
                    stock_data = {
                        'symbol': symbol,
                        'name': symbol,
                        'market_cap': market_cap,
                        'price': quote.get('price', 0),
                        'volume': quote.get('volume', 0),
                        'avg_volume': quote.get('avg_volume', 0),
                        'sector': 'Unknown',
                        'industry': 'Unknown',
                        'exchange': 'Unknown',
                        'pe_ratio': None,
                        'has_options': True,
                        'market_cap_category': self._get_market_cap_category(market_cap)
                    }
                    if min_cap <= market_cap <= max_cap and stock_data['volume'] >= min_volume:
                        stocks.append(stock_data)
                except Exception as e:
                    logger.warning(f"Error loading {symbol} from CSV: {e}")
            logger.info(f"Loaded {len(stocks)} stocks from CSV universe")
            return stocks
        # If no CSV, use the normal logic
        cache_file = self.cache_dir / "market_cap_universe.pkl"
        cache_age_hours = 24
        def filter_stocks(stocks):
            filtered = []
            logger.info(f"Applying lenient filters (min_cap: {min_cap}, max_cap: {max_cap})")
            logger.info(f"Found {len(stocks)} stocks to filter")
            for s in stocks:
                # Only filter out stocks with missing/zero symbol, price, or market cap
                if not s.get('symbol') or s.get('market_cap', 0) <= 0 or s.get('price', 0) <= 0:
                    continue
                if min_cap <= s.get('market_cap', 0) <= max_cap:
                    filtered.append(s)
            logger.info(f"Found {len(filtered)} stocks after filtering")
            return filtered
        # Try cache first
        if cache_file.exists():
            cache_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
            if (datetime.now() - cache_time).total_seconds() < cache_age_hours * 3600:
                logger.info("Loading stocks from cache")
                with open(cache_file, 'rb') as f:
                    all_stocks = pickle.load(f)
                    filtered = filter_stocks(all_stocks)
                    if filtered:
                        return filtered
                    else:
                        logger.info("Cache empty after filtering, fetching fresh data...")
        # Fetch fresh data if cache is empty or stale
        logger.info("Fetching stock universe using bulk data sources...")
        stocks = self._fetch_bulk_stock_data(min_cap, max_cap)
        with open(cache_file, 'wb') as f:
            pickle.dump(stocks, f)
        filtered_stocks = filter_stocks(stocks)
        logger.info(f"Returning {len(filtered_stocks)} stocks after filters")
        return filtered_stocks
    
    def _fetch_additional_screeners(self, min_cap: float, max_cap: float) -> List[Dict]:
        """Fetch from additional Yahoo Finance screeners for more variety, maximizing count."""
        stocks = []
        # Additional valid screener IDs for more variety
        additional_ids = [
            "undervalued_large_caps",
            "aggressive_small_caps",
            "small_cap_gainers",
            "mid_cap_movers"
        ]
        for scrid in additional_ids:
            for count in [250, 200, 100]:
                url = f"https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds={scrid}&count={count}"
                try:
                    response = self.session.get(url, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        if 'finance' in data:
                            results = data.get('finance', {}).get('result', [])
                            if results and 'quotes' in results[0]:
                                for quote in results[0]['quotes']:
                                    market_cap = quote.get('marketCap', 0)
                                    if min_cap <= market_cap <= max_cap:
                                        stock_data = {
                                            'symbol': quote.get('symbol', ''),
                                            'name': quote.get('shortName', quote.get('symbol', '')),
                                            'market_cap': market_cap,
                                            'price': quote.get('regularMarketPrice', 0),
                                            'volume': quote.get('volume', 0),
                                            'avg_volume': quote.get('averageVolume', 0),
                                            'sector': quote.get('sector', 'Unknown'),
                                            'industry': quote.get('industry', 'Unknown'),
                                            'exchange': quote.get('exchange', 'Unknown'),
                                            'pe_ratio': quote.get('forwardPE'),
                                            'has_options': True,  # Assume major stocks have options
                                            'market_cap_category': self._get_market_cap_category(market_cap)
                                        }
                                        stocks.append(stock_data)
                        break
                    elif response.status_code == 400:
                        continue
                    else:
                        break
                except Exception as e:
                    logger.warning(f"Error with Yahoo screener {scrid} count={count}: {e}")
                    continue
        logger.info(f"Additional Yahoo screeners returned {len(stocks)} stocks")
        return stocks

    def _fetch_yahoo_bulk_screener(self, min_cap: float, max_cap: float) -> List[Dict]:
        """Fetch stocks using Yahoo Finance bulk screener, maximizing count and using all valid IDs."""
        stocks = []
        # List of valid Yahoo screener IDs (no 404s)
        screener_ids = [
            "most_actives",
            "day_gainers",
            "day_losers",
            "growth_technology_stocks",
            "undervalued_growth_stocks"
        ]
        for scrid in screener_ids:
            for count in [250, 200, 100]:  # Try largest first, fallback if needed
                url = f"https://query2.finance.yahoo.com/v1/finance/screener/predefined/saved?scrIds={scrid}&count={count}"
                try:
                    response = self.session.get(url, timeout=10)
                    if response.status_code == 200:
                        data = response.json()
                        if 'finance' in data:
                            results = data.get('finance', {}).get('result', [])
                            if results and 'quotes' in results[0]:
                                quotes = results[0]['quotes']
                                for quote in quotes:
                                    market_cap = quote.get('marketCap', 0)
                                    if min_cap <= market_cap <= max_cap:
                                        stock_data = {
                                            'symbol': quote.get('symbol', ''),
                                            'name': quote.get('shortName', quote.get('symbol', '')),
                                            'market_cap': market_cap,
                                            'price': quote.get('regularMarketPrice', 0),
                                            'volume': quote.get('volume', 0),
                                            'avg_volume': quote.get('averageVolume', 0),
                                            'sector': quote.get('sector', 'Unknown'),
                                            'industry': quote.get('industry', 'Unknown'),
                                            'exchange': quote.get('exchange', 'Unknown'),
                                            'pe_ratio': quote.get('forwardPE'),
                                            'has_options': True,  # Assume major stocks have options
                                            'market_cap_category': self._get_market_cap_category(market_cap)
                                        }
                                        stocks.append(stock_data)
                        break  # Success, don't try lower counts
                    elif response.status_code == 400:
                        continue  # Try next lower count
                    else:
                        break  # Don't retry for other errors
                except Exception as e:
                    logger.warning(f"Error with Yahoo screener {scrid} count={count}: {e}")
                    continue
        logger.info(f"Yahoo Finance returned {len(stocks)} stocks")
        return stocks

    def _fetch_nasdaq_bulk_data(self, min_cap: float, max_cap: float) -> List[Dict]:
        """Fetch stocks using NASDAQ bulk data"""
        stocks = []
        try:
            url = "https://api.nasdaq.com/api/screener/stocks"
            params = {
                'tableonly': 'true',
                'limit': 5000,
                'offset': 0,
                'download': 'true'
            }
            logger.debug(f"Fetching from NASDAQ: {url} with params {params}")
            response = self.session.get(url, params=params, timeout=15)
            logger.debug(f"NASDAQ response status: {response.status_code}")
            if response.status_code != 200:
                logger.warning(f"NASDAQ API call failed: {url} | Status: {response.status_code} | Body: {response.text[:300]}")
            else:
                data = response.json()
                for row in data.get('data', {}).get('rows', []):
                    try:
                        market_cap_str = row.get('marketCap', '0')
                        market_cap = self._parse_market_cap(market_cap_str)
                        if min_cap <= market_cap <= max_cap:
                            volume_str = row.get('volume', '0')
                            volume = self._parse_volume(volume_str)
                            stock_data = {
                                'symbol': row.get('symbol', ''),
                                'name': row.get('name', row.get('symbol', '')),
                                'market_cap': market_cap,
                                'price': float(row.get('lastsale', 0)),
                                'volume': volume,
                                'avg_volume': volume,
                                'sector': row.get('sector', 'Unknown'),
                                'industry': row.get('industry', 'Unknown'),
                                'exchange': row.get('exchange', 'NASDAQ'),
                                'pe_ratio': None,
                                'has_options': True,
                                'market_cap_category': self._get_market_cap_category(market_cap)
                            }
                            stocks.append(stock_data)
                    except Exception as e:
                        logger.debug(f"Error parsing NASDAQ row: {e}")
                        continue
        except Exception as e:
            logger.error(f"Error fetching NASDAQ bulk data: {e}")
        logger.info(f"NASDAQ returned {len(stocks)} stocks")
        return stocks

    # Remove IEX Cloud related code and add Finnhub support
    def _fetch_finnhub_symbols(self, api_token: str) -> list:
        """Fetch all US tickers from Finnhub (requires API token)"""
        url = f"https://finnhub.io/api/v1/stock/symbol?exchange=US&token={api_token}"
        try:
            response = self.session.get(url, timeout=30)
            if response.status_code == 200:
                data = response.json()
                stocks = []
                for item in data:
                    # Only include common stocks (type 'Common Stock')
                    if item.get('type') == 'Common Stock':
                        stocks.append({
                            'symbol': item['symbol'],
                            'name': item.get('description', item['symbol']),
                            'exchange': item.get('exchange', 'US'),
                            'has_options': True  # You can refine this if needed
                        })
                logger.info(f"Finnhub returned {len(stocks)} US common stocks")
                return stocks
            else:
                logger.warning(f"Finnhub API call failed: {response.status_code}")
                return []
        except Exception as e:
            logger.error(f"Error fetching Finnhub symbols: {e}")
            return []

    def _enrich_finnhub_tickers(self, tickers: list) -> list:
        """Enrich Finnhub tickers with price and market cap using yfinance (batch)."""
        import yfinance as yf
        import time
        enriched = []
        batch_size = 100
        total = len(tickers)
        for i in range(0, total, batch_size):
            batch = tickers[i:i+batch_size]
            symbols = [t['symbol'] for t in batch]
            try:
                yf_tickers = yf.Tickers(' '.join(symbols))
                for symbol in symbols:
                    t = next((item for item in batch if item['symbol'] == symbol), None)
                    if not t:
                        continue
                    info = None
                    try:
                        info = yf_tickers.tickers[symbol].info
                    except Exception:
                        continue
                    price = info.get('regularMarketPrice')
                    market_cap = info.get('marketCap')
                    if price and market_cap:
                        t['price'] = price
                        t['market_cap'] = market_cap
                        t['volume'] = info.get('volume', 0)
                        t['avg_volume'] = info.get('averageVolume', 0)
                        t['sector'] = info.get('sector', 'Unknown')
                        t['industry'] = info.get('industry', 'Unknown')
                        t['exchange'] = info.get('exchange', t.get('exchange', 'US'))
                        t['pe_ratio'] = info.get('forwardPE')
                        t['has_options'] = info.get('options', []) != []
                        t['market_cap_category'] = self._get_market_cap_category(market_cap)
                        enriched.append(t)
                self.rate_limiter.add_jitter()
            except Exception as e:
                logger.warning(f"Error enriching batch {i}-{i+batch_size}: {e}")
            logger.info(f"Enriched {min(i+batch_size, total)}/{total} Finnhub tickers...")
            time.sleep(1)  # avoid rate limits
        logger.info(f"Total enriched Finnhub tickers: {len(enriched)}")
        return enriched

    def _fetch_bulk_stock_data(self, min_cap: float, max_cap: float) -> List[Dict]:
        """Fetch stock data using bulk sources to avoid individual API calls (Yahoo + Finnhub if available)."""
        stocks = []
        logger.info(f"Fetching stocks in range ${min_cap/1e8:.1f}B - ${max_cap/1e9:.0f}B")
        # Yahoo Finance bulk screener
        logger.info("Fetching from Yahoo Finance screeners...")
        yahoo_stocks = self._fetch_yahoo_bulk_screener(min_cap, max_cap)
        logger.info(f"Found {len(yahoo_stocks)} stocks from Yahoo Finance")
        stocks.extend(yahoo_stocks)
        # Additional Yahoo screeners
        logger.info("Fetching from additional screeners...")
        additional_stocks = self._fetch_additional_screeners(min_cap, max_cap)
        logger.info(f"Found {len(additional_stocks)} stocks from additional screeners")
        stocks.extend(additional_stocks)
        # Finnhub (if API key is set in config or use provided default)
        api_token = getattr(self.config.data, 'finnhub_api_token', None)
        if api_token:
            logger.info("Fetching from Finnhub symbols...")
            finnhub_tickers = self._fetch_finnhub_symbols(api_token)
            logger.info(f"Found {len(finnhub_tickers)} stocks from Finnhub (unenriched)")
            enriched_finnhub = self._enrich_finnhub_tickers(finnhub_tickers)
            logger.info(f"Found {len(enriched_finnhub)} enriched Finnhub stocks")
            stocks.extend(enriched_finnhub)
        # Remove duplicates
        seen_symbols = set()
        unique_stocks = []
        for stock in stocks:
            if stock['symbol'] not in seen_symbols:
                seen_symbols.add(stock['symbol'])
                unique_stocks.append(stock)
        logger.info(f"Found {len(unique_stocks)} unique stocks in range ${min_cap} - ${max_cap}")
        if len(unique_stocks) == 0:
            logger.error("No stocks found from any data source. This indicates an issue with the APIs or market hours.")
            logger.error("Check if it's a weekend/holiday or if the APIs have changed.")
        return unique_stocks
    
    def _parse_market_cap(self, market_cap_str: str) -> float:
        """Parse market cap string to float value"""
        try:
            if not market_cap_str or market_cap_str == 'N/A':
                return 0
            
            # Remove common suffixes and convert
            market_cap_str = market_cap_str.upper().replace(',', '')
            
            if 'B' in market_cap_str:
                value = float(market_cap_str.replace('B', '')) * 1e9
            elif 'M' in market_cap_str:
                value = float(market_cap_str.replace('M', '')) * 1e6
            elif 'T' in market_cap_str:
                value = float(market_cap_str.replace('T', '')) * 1e12
            else:
                value = float(market_cap_str)
                
            return value
        except:
            return 0
    
    def _parse_volume(self, volume_str: str) -> int:
        """Parse volume string to integer"""
        try:
            if not volume_str or volume_str == 'N/A':
                return 0
            
            # Remove commas and convert
            volume_str = volume_str.replace(',', '')
            return int(float(volume_str))
        except:
            return 0
    
    def update_stock_data_with_current_prices(self, stocks: List[Dict]) -> List[Dict]:
        """Update stock data with current prices and volumes using batch processing"""
        updated_stocks = []
        logger.info(f"Updating current data for {len(stocks)} stocks using batch processing...")
        
        # Process in large batches using yf.Tickers (much more efficient)
        batch_size = 200  # yfinance's optimal batch size
        total_batches = (len(stocks) + batch_size - 1) // batch_size
        
        for i in range(0, len(stocks), batch_size):
            batch = stocks[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            
            try:
                # Get symbols for this batch
                symbols = [stock['symbol'] for stock in batch]
                symbols_str = ' '.join(symbols)
                
                # Use yf.Tickers for batch processing (much more efficient)
                yf_tickers = yf.Tickers(symbols_str)
                
                for stock in batch:
                    symbol = stock['symbol']
                    try:
                        # Get ticker info from batch
                        ticker = yf_tickers.tickers[symbol]
                        info = ticker.info
                        
                        # Update stock data with current info
                        price = info.get('regularMarketPrice')
                        volume = info.get('volume', 0)
                        avg_volume = info.get('averageVolume', 0)
                        
                        if price is not None and price > 0:
                            stock['price'] = price
                        if volume is not None:
                            stock['volume'] = volume
                        if avg_volume is not None:
                            stock['avg_volume'] = avg_volume
                            
                        updated_stocks.append(stock)
                        
                    except Exception as e:
                        # Silently skip stocks that fail (no error logging)
                        updated_stocks.append(stock)
                        continue
                
                # Progress logging
                if batch_num % 5 == 0 or batch_num == total_batches:
                    logger.info(f"Processed batch {batch_num}/{total_batches} ({min(i + batch_size, len(stocks))}/{len(stocks)} stocks)")
                
                # Rate limiting between batches
                if i + batch_size < len(stocks):
                    time.sleep(1)  # 1 second between batches
                    
            except Exception as e:
                logger.warning(f"Error processing batch {batch_num}: {e}")
                # Add stocks from failed batch without updates
                updated_stocks.extend(batch)
                continue
        
        logger.info(f"Updated data for {len(updated_stocks)} stocks")
        return updated_stocks
    
    def _get_market_cap_category(self, market_cap: float) -> str:
        """Get market cap category for filtering"""
        if market_cap < 1e9:
            return 'small_cap'
        elif market_cap < 10e9:
            return 'mid_cap'
        elif market_cap < 100e9:
            return 'large_cap'
        else:
            return 'mega_cap'
    
    def get_options_chain(self, symbol: str) -> List[Dict]:
        """Get options chain with IMPROVED analysis for low-volume options"""
        try:
            ticker = yf.Ticker(symbol)
            
            # Get available expiration dates
            expirations = ticker.options
            if not expirations:
                logger.warning(f"No options available for {symbol}")
                return []
                
            options_data = []
            current_price = self.get_quote(symbol)['price']
            
            # Sort expirations by days to expiration for better selection
            expirations_with_days = []
            for exp_date in expirations:
                exp_datetime = datetime.strptime(exp_date, '%Y-%m-%d')
                days_to_exp = (exp_datetime - datetime.now()).days
                if 20 <= days_to_exp <= 70:  # Keep the same range
                    expirations_with_days.append((exp_date, days_to_exp))
            
            # Sort by days to expiration to get variety
            expirations_with_days.sort(key=lambda x: x[1])
            
            # Take a variety of expiration dates (not just the first one)
            selected_expirations = []
            if len(expirations_with_days) >= 3:
                # Take first, middle, and last expiration for variety
                selected_expirations = [
                    expirations_with_days[0][0],  # Shortest
                    expirations_with_days[len(expirations_with_days)//2][0],  # Middle
                    expirations_with_days[-1][0]  # Longest
                ]
            else:
                selected_expirations = [exp[0] for exp in expirations_with_days]
            
            logger.debug(f"Selected {len(selected_expirations)} expiration dates for {symbol}: {selected_expirations}")
            
            for exp_date in selected_expirations:
                # Convert expiration to datetime
                exp_datetime = datetime.strptime(exp_date, '%Y-%m-%d')
                days_to_exp = (exp_datetime - datetime.now()).days
                    
                # Get options data
                opt_chain = ticker.option_chain(exp_date)
                calls = opt_chain.calls
                
                # Process calls with RELAXED criteria
                for _, call in calls.iterrows():
                    strike = call['strike']
                    
                    # RELAXED: Allow wider range (85% to 120% of current price)
                    if strike < current_price * 0.85 or strike > current_price * 1.20:
                        continue
                    
                    # Get option data
                    bid = call['bid']
                    ask = call['ask']
                    volume = call['volume'] if pd.notna(call['volume']) else 0
                    open_interest = call['openInterest'] if pd.notna(call['openInterest']) else 0
                    
                    # Calculate spread
                    if ask > 0:
                        spread_pct = (ask - bid) / ask
                    else:
                        spread_pct = 1.0
                    
                    # STRICT: Must meet higher liquidity requirements
                    acceptable = False
                    liquidity_score = 0
                    
                    # Condition 1: Must have significant volume
                    if volume >= self.min_option_volume:
                        acceptable = True
                        liquidity_score += 40
                    
                    # Condition 2: Must have significant open interest
                    if open_interest >= self.min_option_oi:
                        acceptable = True
                        liquidity_score += 40
                    
                    # Condition 3: Tight spread requirement
                    if spread_pct <= self.max_bid_ask_spread and ask > 0:
                        acceptable = True
                        liquidity_score += 20
                    
                    # Condition 4: Near the money options (more liquid)
                    moneyness = abs(strike - current_price) / current_price
                    if moneyness <= 0.05:  # Within 5% of current price
                        liquidity_score += 20
                    
                    if not acceptable:
                        continue
                    
                    # Calculate IMPLIED volatility if missing
                    iv = call.get('impliedVolatility', 0)
                    if iv == 0 or pd.isna(iv):
                        # Estimate IV based on bid-ask spread and time
                        iv = 0.3 + (spread_pct * 0.5)  # Higher spread = higher IV estimate
                    
                    option_data = {
                        'symbol': symbol,
                        'type': 'CALL',
                        'strike': strike,
                        'expiration': exp_date,
                        'days_to_expiration': days_to_exp,
                        'bid': bid,
                        'ask': ask,
                        'mid': (bid + ask) / 2 if ask > 0 else call.get('lastPrice', 0),
                        'last': call.get('lastPrice', 0),
                        'volume': int(volume),
                        'open_interest': int(open_interest),
                        'implied_volatility': iv,
                        'in_the_money': call.get('inTheMoney', False),
                        'contract_symbol': call.get('contractSymbol', ''),
                        'spread_pct': spread_pct,
                        'liquidity_score': liquidity_score,
                        # Greeks estimates
                        'delta': self._estimate_delta(current_price, strike, days_to_exp, iv),
                        'theta': self._estimate_theta(current_price, strike, days_to_exp, iv, ask if ask > 0 else 0.01),
                        'gamma': self._estimate_gamma(current_price, strike, days_to_exp, iv),
                        'vega': self._estimate_vega(current_price, strike, days_to_exp, iv),
                        'iv_percentile': min(95, max(5, iv * 150))  # Rough estimate
                    }
                    
                    options_data.append(option_data)
                    
            # Silent processing - no verbose output
            return options_data
            
        except Exception as e:
            logger.error(f"Error getting options chain for {symbol}: {e}")
            return []
    
    @lru_cache(maxsize=100)
    def get_quote(self, symbol: str) -> Dict:
        """Get current quote for a symbol"""
        try:
            ticker = yf.Ticker(symbol)
            
            # Try to get intraday data first
            data = ticker.history(period='1d', interval='5m')
            
            if data.empty:
                # Fall back to daily data
                data = ticker.history(period='5d')
                if data.empty:
                    raise ValueError(f"No data available for {symbol}")
                    
            current_price = data['Close'].iloc[-1]
            volume = data['Volume'].iloc[-1] if len(data) == 1 else data['Volume'].sum()
            
            # Get additional info
            info = ticker.info
            
            return {
                'symbol': symbol,
                'price': current_price,
                'volume': volume,
                'avg_volume': info.get('averageVolume', volume),
                'bid': info.get('bid', current_price * 0.995),  # Estimate if missing
                'ask': info.get('ask', current_price * 1.005),  # Estimate if missing
                'day_high': data['High'].max(),
                'day_low': data['Low'].min(),
                'prev_close': info.get('previousClose', current_price),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting quote for {symbol}: {e}")
            raise
    
    def get_price_history(self, symbol: str, days: int = 100) -> List[Dict]:
        """Get price history for technical analysis (no persistent cache, just lru_cache if needed)"""
        try:
            ticker = yf.Ticker(symbol)
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
            data = ticker.history(start=start_date, end=end_date)
            if data.empty:
                data = ticker.history(period="1mo")
                if data.empty:
                    return []
            history = []
            for date, row in data.iterrows():
                history.append({
                    'date': date.strftime('%Y-%m-%d'),
                    'open': row['Open'],
                    'high': row['High'],
                    'low': row['Low'],
                    'close': row['Close'],
                    'volume': row['Volume']
                })
            return history
        except Exception as e:
            logger.error(f"Error getting price history for {symbol}: {e}")
            return []

    def get_options_chain(self, symbol: str) -> List[Dict]:
        """Get options chain with improved analysis for low-volume options (no persistent cache)"""
        try:
            ticker = yf.Ticker(symbol)
            expirations = ticker.options
            if not expirations:
                logger.warning(f"No options available for {symbol}")
                return []
            options_data = []
            current_price = self.get_quote(symbol)['price']
            expirations_with_days = []
            for exp_date in expirations:
                exp_datetime = datetime.strptime(exp_date, '%Y-%m-%d')
                days_to_exp = (exp_datetime - datetime.now()).days
                if 20 <= days_to_exp <= 70:
                    expirations_with_days.append((exp_date, days_to_exp))
            expirations_with_days.sort(key=lambda x: x[1])
            selected_expirations = []
            if len(expirations_with_days) >= 3:
                selected_expirations = [
                    expirations_with_days[0][0],
                    expirations_with_days[len(expirations_with_days)//2][0],
                    expirations_with_days[-1][0]
                ]
            else:
                selected_expirations = [exp[0] for exp in expirations_with_days]
            for exp_date in selected_expirations:
                exp_datetime = datetime.strptime(exp_date, '%Y-%m-%d')
                days_to_exp = (exp_datetime - datetime.now()).days
                opt_chain = ticker.option_chain(exp_date)
                calls = opt_chain.calls
                for _, call in calls.iterrows():
                    strike = call['strike']
                    if strike < current_price * 0.85 or strike > current_price * 1.20:
                        continue
                    bid = call['bid']
                    ask = call['ask']
                    volume = call['volume'] if pd.notna(call['volume']) else 0
                    open_interest = call['openInterest'] if pd.notna(call['openInterest']) else 0
                    if ask > 0:
                        spread_pct = (ask - bid) / ask
                    else:
                        spread_pct = 1.0
                    acceptable = False
                    liquidity_score = 0
                    if volume >= self.min_option_volume:
                        acceptable = True
                        liquidity_score += 40
                    if open_interest >= self.min_option_oi:
                        acceptable = True
                        liquidity_score += 40
                    if spread_pct <= self.max_bid_ask_spread and ask > 0:
                        acceptable = True
                        liquidity_score += 20
                    moneyness = abs(strike - current_price) / current_price
                    if moneyness <= 0.05:
                        liquidity_score += 20
                    if not acceptable:
                        continue
                    iv = call.get('impliedVolatility', 0)
                    if iv == 0 or pd.isna(iv):
                        iv = 0.3 + (spread_pct * 0.5)
                    option_data = {
                        'symbol': symbol,
                        'type': 'CALL',
                        'strike': strike,
                        'expiration': exp_date,
                        'days_to_expiration': days_to_exp,
                        'bid': bid,
                        'ask': ask,
                        'mid': (bid + ask) / 2 if ask > 0 else call.get('lastPrice', 0),
                        'last': call.get('lastPrice', 0),
                        'volume': int(volume),
                        'open_interest': int(open_interest),
                        'implied_volatility': iv,
                        'in_the_money': call.get('inTheMoney', False),
                        'contract_symbol': call.get('contractSymbol', ''),
                        'spread_pct': spread_pct,
                        'liquidity_score': liquidity_score,
                        'delta': self._estimate_delta(current_price, strike, days_to_exp, iv),
                        'theta': self._estimate_theta(current_price, strike, days_to_exp, iv, ask if ask > 0 else 0.01),
                        'gamma': self._estimate_gamma(current_price, strike, days_to_exp, iv),
                        'vega': self._estimate_vega(current_price, strike, days_to_exp, iv),
                        'iv_percentile': min(95, max(5, iv * 150))
                    }
                    options_data.append(option_data)
            return options_data
        except Exception as e:
            logger.error(f"Error getting options chain for {symbol}: {e}")
            return []

    def save_all_caches(self):
        self._save_fundamentals_cache()
    
    def _estimate_delta(self, spot: float, strike: float, days: int, iv: float) -> float:
        """Estimate delta using Black-Scholes approximation"""
        try:
            # More accurate delta calculation
            moneyness = spot / strike
            time_to_exp = days / 365.0
            
            # Simplified Black-Scholes delta approximation
            d1 = (np.log(moneyness) + (0.02 + 0.5 * iv * iv) * time_to_exp) / (iv * np.sqrt(time_to_exp))
            delta = norm.cdf(d1)
            
            return round(delta, 3)
        except:
            # Fallback to simple calculation
            if moneyness > 1.05:
                return 0.7
            elif moneyness < 0.95:
                return 0.3
            else:
                return 0.5
    
    def _estimate_theta(self, spot: float, strike: float, days: int, 
                       iv: float, option_price: float) -> float:
        """Estimate theta (time decay) - NEGATIVE value"""
        try:
            # Theta increases as expiration approaches
            time_factor = np.sqrt(365 / max(days, 1))
            
            # ATM options have highest theta
            moneyness = spot / strike
            atm_factor = np.exp(-((moneyness - 1) ** 2) / 0.02)
            
            # Base theta as percentage of option value
            base_theta = -0.005 * time_factor * atm_factor * (1 + iv)
            
            # Convert to dollar amount
            theta_dollars = option_price * base_theta
            
            return round(theta_dollars, 4)
        except:
            return -0.01  # Default small theta
    
    def _estimate_gamma(self, spot: float, strike: float, days: int, iv: float) -> float:
        """Estimate gamma"""
        try:
            # Gamma highest at ATM
            moneyness = spot / strike
            time_to_exp = days / 365.0
            
            # ATM factor
            atm_factor = np.exp(-((moneyness - 1) ** 2) / 0.02)
            
            # Time factor - gamma increases near expiration
            time_factor = 1 / np.sqrt(max(time_to_exp, 0.01))
            
            gamma = 0.01 * atm_factor * time_factor / (spot * iv * np.sqrt(2 * np.pi))
            
            return round(max(0, gamma), 4)
        except:
            return 0.01
    
    def _estimate_vega(self, spot: float, strike: float, days: int, iv: float) -> float:
        """Estimate vega"""
        try:
            # Vega highest for ATM options with time remaining
            moneyness = spot / strike
            time_to_exp = days / 365.0
            
            # ATM factor
            atm_factor = np.exp(-((moneyness - 1) ** 2) / 0.02)
            
            # Time factor - vega decreases near expiration
            time_factor = np.sqrt(time_to_exp)
            
            vega = spot * 0.01 * atm_factor * time_factor * np.sqrt(2 / np.pi)
            
            return round(vega, 3)
        except:
            return 0.1
    
    def clear_cache(self):
        """Clear data cache"""
        self.cache.clear()
        self.cache_expiry.clear()
        
        # Clear file cache
        for cache_file in self.cache_dir.glob("*.pkl"):
            cache_file.unlink()
            
        logger.info("Data cache cleared")

    def _validate_stock_data(self, stock_data: Dict) -> bool:
        """Validate stock data for reasonableness"""
        try:
            # Check for required fields
            required_fields = ['symbol', 'market_cap', 'price', 'volume']
            for field in required_fields:
                if field not in stock_data or stock_data[field] is None:
                    return False
            
            # Sanity checks
            if stock_data['price'] <= 0:
                logger.debug(f"Invalid price for {stock_data['symbol']}: {stock_data['price']}")
                return False
                
            if stock_data['market_cap'] <= 0:
                logger.debug(f"Invalid market cap for {stock_data['symbol']}: {stock_data['market_cap']}")
                return False
                
            if stock_data['volume'] < 0:
                logger.debug(f"Invalid volume for {stock_data['symbol']}: {stock_data['volume']}")
                return False
            
            # Check for reasonable ranges
            if stock_data['price'] > 10000:  # $10k+ stocks are rare
                logger.debug(f"Suspiciously high price for {stock_data['symbol']}: {stock_data['price']}")
                return False
                
            if stock_data['market_cap'] > 1e12:  # $1T+ market cap
                logger.debug(f"Suspiciously high market cap for {stock_data['symbol']}: {stock_data['market_cap']}")
                return False
            
            return True
            
        except Exception as e:
            logger.debug(f"Error validating stock data: {e}")
            return False
    
    def _validate_option_data(self, option_data: Dict) -> bool:
        """Validate option data for reasonableness"""
        try:
            required_fields = ['strike', 'expiration', 'bid', 'ask', 'volume', 'open_interest']
            for field in required_fields:
                if field not in option_data or option_data[field] is None:
                    return False
            
            # Sanity checks
            if option_data['strike'] <= 0:
                return False
                
            if option_data['bid'] < 0 or option_data['ask'] < 0:
                return False
                
            if option_data['ask'] < option_data['bid']:
                logger.debug(f"Ask < Bid for option: {option_data}")
                return False
            
            return True
            
        except Exception as e:
            logger.debug(f"Error validating option data: {e}")
            return False

    def get_option_quote(self, symbol: str, strike: float, expiration: str, option_type: str = 'CALL') -> Optional[Dict]:
        """Get current quote for a specific option contract"""
        try:
            ticker = yf.Ticker(symbol)
            
            # Get options chain for the expiration
            opt_chain = self._safe_yfinance_call(lambda: ticker.option_chain(expiration))
            if not opt_chain:
                return None
            
            # Get the appropriate chain (calls or puts)
            if option_type.upper() == 'CALL':
                options = opt_chain.calls
            else:
                options = opt_chain.puts
            
            # Find the specific strike
            option_data = options[options['strike'] == strike]
            if option_data.empty:
                return None
            
            option = option_data.iloc[0]
            
            # Get current stock price
            current_price = self.get_quote(symbol)['price']
            
            # Calculate days to expiration
            exp_date = datetime.strptime(expiration, '%Y-%m-%d')
            days_to_exp = (exp_date - datetime.now()).days
            
            # Calculate spread
            bid = option.get('bid', 0)
            ask = option.get('ask', 0)
            spread_pct = (ask - bid) / ask if ask > 0 else 1.0
            
            # Estimate Greeks if not available
            iv = option.get('impliedVolatility', 0.3)
            if iv == 0 or pd.isna(iv):
                iv = 0.3  # Default IV
            
            return {
                'symbol': symbol,
                'strike': strike,
                'expiration': expiration,
                'type': option_type,
                'bid': bid,
                'ask': ask,
                'mid': (bid + ask) / 2 if ask > 0 else option.get('lastPrice', 0),
                'last': option.get('lastPrice', 0),
                'volume': int(option.get('volume', 0)),
                'open_interest': int(option.get('openInterest', 0)),
                'implied_volatility': iv,
                'days_to_expiration': days_to_exp,
                'spread_pct': spread_pct,
                'current_stock_price': current_price,
                # Estimated Greeks
                'delta': self._estimate_delta(current_price, strike, days_to_exp, iv),
                'theta': self._estimate_theta(current_price, strike, days_to_exp, iv, ask if ask > 0 else 0.01),
                'gamma': self._estimate_gamma(current_price, strike, days_to_exp, iv),
                'vega': self._estimate_vega(current_price, strike, days_to_exp, iv)
            }
            
        except Exception as e:
            logger.error(f"Error getting option quote for {symbol} {strike} {expiration}: {e}")
            return None