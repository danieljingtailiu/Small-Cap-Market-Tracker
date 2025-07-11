"""
Market Scanner module for finding small-cap opportunities
"""

import logging
import time
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)


class MarketScanner:
    """Scans market for small-cap stocks meeting criteria"""
    
    def __init__(self, config, data_fetcher):
        self.config = config
        self.data_fetcher = data_fetcher
        
    def find_small_caps(self) -> List[Dict]:
        """Find all stocks with market cap between configured min and max"""
        logger.info("Scanning for stocks within market cap range...")
        
        # Get all stocks with basic filters using dynamic market cap range
        stocks = self.data_fetcher.get_stocks_by_market_cap(
            min_cap=self.config.trading.market_cap_min,
            max_cap=self.config.trading.market_cap_max,
            min_volume=self.config.trading.min_volume
        )
        
        # Add additional data for each stock in batches to avoid rate limits
        enriched_stocks = []
        batch_size = 3  # Process 3 stocks at a time to be very conservative
        
        logger.info(f"Enriching {len(stocks)} stocks with current data...")
        
        for i in range(0, len(stocks), batch_size):
            batch = stocks[i:i + batch_size]
            logger.info(f"Enriching batch {i//batch_size + 1}/{(len(stocks) + batch_size - 1)//batch_size}")
            
            for stock in batch:
                try:
                    # Get current price and volume
                    quote = self.data_fetcher.get_quote(stock['symbol'])
                    
                    # Get basic fundamentals
                    fundamentals = self.data_fetcher.get_fundamentals(stock['symbol'])
                    
                    enriched_stock = {
                        'symbol': stock['symbol'],
                        'name': stock['name'],
                        'market_cap': stock['market_cap'],
                        'price': quote['price'],
                        'volume': quote['volume'],
                        'avg_volume': quote['avg_volume'],
                        'pe_ratio': fundamentals.get('pe_ratio'),
                        'revenue_growth': fundamentals.get('revenue_growth'),
                        'earnings_growth': fundamentals.get('earnings_growth'),
                        'institutional_ownership': fundamentals.get('institutional_ownership', 0),
                        'sector': stock.get('sector', 'Unknown'),
                        'industry': stock.get('industry', 'Unknown'),
                        'market_cap_category': stock.get('market_cap_category', 'unknown')
                    }
                    
                    enriched_stocks.append(enriched_stock)
                    
                except Exception as e:
                    logger.warning(f"Error enriching data for {stock['symbol']}: {e}")
                    continue
            
            # Rate limiting between batches
            if i + batch_size < len(stocks):
                time.sleep(5)  # 5 second delay between batches
        
        logger.info(f"Successfully enriched {len(enriched_stocks)} stocks")
                
        return enriched_stocks
    
    def apply_filters(self, stocks: List[Dict]) -> List[Dict]:
        """Apply technical and fundamental filters"""
        filtered = []
        
        for stock in stocks:
            try:
                # Apply fundamental filters
                if not self._passes_fundamental_filters(stock):
                    continue
                    
                # Get technical data
                technicals = self._analyze_technicals(stock['symbol'])
                if not technicals:
                    continue
                    
                # Check technical patterns
                if self._has_bullish_setup(technicals):
                    stock.update(technicals)
                    filtered.append(stock)
                    logger.info(f"{stock['symbol']} passed all filters")
                    
            except Exception as e:
                logger.warning(f"Error filtering {stock['symbol']}: {e}")
                
        return filtered
    
    def _passes_fundamental_filters(self, stock: Dict) -> bool:
        """Check if stock passes fundamental criteria with growth focus"""
        # PE Ratio check - allow higher PEs for growth stocks
        if stock.get('pe_ratio'):
            if stock['pe_ratio'] > 100 or stock['pe_ratio'] < 0:  # Allow high PEs for growth
                return False
                
        # Growth checks - require strong growth
        if stock.get('revenue_growth'):
            if stock['revenue_growth'] < 0.15:  # Require 15%+ revenue growth
                return False
                
        if stock.get('earnings_growth'):
            if stock['earnings_growth'] < 0.10:  # Require 10%+ earnings growth
                return False
                
        # Institutional ownership - want some institutional interest
        if stock.get('institutional_ownership', 0) < 0.05:  # At least 5%
            return False
            
        return True
    
    def _analyze_technicals(self, symbol: str) -> Optional[Dict]:
        """Analyze technical indicators for a stock"""
        try:
            # Get price history
            history = self.data_fetcher.get_price_history(symbol, days=100)
            if len(history) < 50:
                return None
                
            df = pd.DataFrame(history)
            
            # Calculate indicators
            technicals = {
                'rsi': self._calculate_rsi(df['close']),
                'sma_20': df['close'].rolling(20).mean().iloc[-1],
                'sma_50': df['close'].rolling(50).mean().iloc[-1],
                'volume_ratio': df['volume'].iloc[-1] / df['volume'].rolling(20).mean().iloc[-1],
                'price_change_5d': (df['close'].iloc[-1] / df['close'].iloc[-5] - 1),
                'price_change_20d': (df['close'].iloc[-1] / df['close'].iloc[-20] - 1),
                'atr': self._calculate_atr(df),
                'relative_strength': self._calculate_relative_strength(df),
                'pattern': self._detect_pattern(df)
            }
            
            return technicals
            
        except Exception as e:
            logger.error(f"Error analyzing technicals for {symbol}: {e}")
            return None
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """Calculate RSI indicator"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        
        return rsi.iloc[-1]
    
    def _calculate_atr(self, df: pd.DataFrame, period: int = 14) -> float:
        """Calculate Average True Range"""
        high = df['high']
        low = df['low']
        close = df['close']
        
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()
        
        return atr.iloc[-1]
    
    def _calculate_relative_strength(self, df: pd.DataFrame) -> float:
        """Calculate relative strength vs market"""
        # Simple implementation - compare to SPY
        try:
            spy_history = self.data_fetcher.get_price_history('SPY', days=20)
            spy_return = (spy_history[-1]['close'] / spy_history[0]['close'] - 1)
            stock_return = (df['close'].iloc[-1] / df['close'].iloc[-20] - 1)
            
            return stock_return / spy_return if spy_return != 0 else 1.0
        except:
            return 1.0
    
    def _detect_pattern(self, df: pd.DataFrame) -> str:
        """Detect chart patterns"""
        closes = df['close'].values[-20:]
        highs = df['high'].values[-20:]
        lows = df['low'].values[-20:]
        
        # Simple pattern detection
        if self._is_breakout(closes, highs):
            return 'breakout'
        elif self._is_flag_pattern(closes, highs, lows):
            return 'flag'
        elif self._is_ascending_triangle(highs, lows):
            return 'ascending_triangle'
        else:
            return 'none'
    
    def _is_breakout(self, closes: np.ndarray, highs: np.ndarray) -> bool:
        """Check for breakout pattern"""
        # Price breaks above recent high with volume
        recent_high = np.max(highs[:-5])
        current_price = closes[-1]
        
        return current_price > recent_high * 1.02  # 2% above recent high
    
    def _is_flag_pattern(self, closes: np.ndarray, highs: np.ndarray, lows: np.ndarray) -> bool:
        """Check for flag pattern"""
        # Simplified flag detection
        first_half_trend = np.polyfit(range(10), closes[:10], 1)[0]
        second_half_trend = np.polyfit(range(10), closes[10:], 1)[0]
        
        # Strong move up followed by consolidation
        return first_half_trend > 0.5 and abs(second_half_trend) < 0.1
    
    def _is_ascending_triangle(self, highs: np.ndarray, lows: np.ndarray) -> bool:
        """Check for ascending triangle pattern"""
        # Higher lows with resistance at top
        low_trend = np.polyfit(range(len(lows)), lows, 1)[0]
        high_std = np.std(highs)
        
        return low_trend > 0 and high_std < np.mean(highs) * 0.02
    
    def _has_bullish_setup(self, technicals: Dict) -> bool:
        """Check for bullish technical setup with momentum focus"""
        # Require strong momentum indicators
        if technicals.get('relative_strength', 1) < 1.1:  # Must outperform market
            return False
            
        # Price above moving averages
        if technicals.get('price_change_20d', 0) < 0.05:  # 5% above 20-day MA
            return False
            
        # Volume confirmation
        if technicals.get('volume_ratio', 1) < 1.2:  # 20% above average volume
            return False
            
        # RSI not overbought
        if technicals.get('rsi', 50) > 80:  # Avoid overbought
            return False
            
        # Positive price momentum
        if technicals.get('price_change_5d', 0) < 0.02:  # 2% up in 5 days
            return False
            
        return True

if __name__ == "__main__":
    # Dummy config and data_fetcher for testing
    class DummyConfig:
        class trading:
            market_cap_min = 500_000_000
            market_cap_max = 10_000_000_000
            min_volume = 100_000
            rsi_overbought = 70
        class scanner:
            max_pe_ratio = 40
            min_revenue_growth = 0.05
            min_earnings_growth = 0.05
            min_institutional_ownership = 0.1
            min_relative_strength = 1.1

    class DummyDataFetcher:
        def get_stocks_by_market_cap(self, min_cap, max_cap, min_volume):
            return [{'symbol': 'TEST', 'name': 'Test Corp', 'market_cap': 1_000_000_000}]
        def get_quote(self, symbol):
            return {'price': 10, 'volume': 200_000, 'avg_volume': 150_000}
        def get_fundamentals(self, symbol):
            return {'pe_ratio': 20, 'revenue_growth': 0.1, 'earnings_growth': 0.1, 'institutional_ownership': 0.2}
        def get_price_history(self, symbol, days):
            return [{'close': 10 + i*0.1, 'high': 10 + i*0.15, 'low': 10 + i*0.05, 'volume': 200_000} for i in range(days)]

    scanner = MarketScanner(DummyConfig(), DummyDataFetcher())
    stocks = scanner.find_small_caps()
    filtered = scanner.apply_filters(stocks)
    print("Filtered stocks:", filtered)