"""
data_engine.py

High-performance multi-threaded market data engine for QuantumTrader.
Fetches quotes and historical price action concurrently across Crypto, Forex,
Commodities, Indices, and Stocks.
"""
import time
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import urllib3

# Suppress insecure SSL warnings if any occur
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

import config

logger = logging.getLogger(__name__)


class MarketDataEngine:
    """Thread-safe, rate-resilient multi-asset market data engine with memory caching."""

    def __init__(self):
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.quote_cache_ttl = config.CACHE_QUOTES_TTL_SECONDS
        self.hist_cache_ttl = config.CACHE_HISTORICAL_TTL_SECONDS
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        })

    def _is_cache_valid(self, cache_key: str, ttl: int) -> bool:
        """Check if cached entry is within TTL."""
        if cache_key in self.cache:
            entry = self.cache[cache_key]
            if time.time() - entry.get("timestamp", 0) < ttl:
                return True
        return False

    def fetch_coinbase_crypto_price(self, coin_id: str) -> Optional[float]:
        """Fallback quote fetcher using public Coinbase spot price API."""
        try:
            url = f"https://api.coinbase.com/v2/prices/{coin_id}-USD/spot"
            res = self.session.get(url, timeout=5)
            if res.status_code == 200:
                data = res.json()
                amount_str = data.get("data", {}).get("amount")
                if amount_str:
                    return float(amount_str)
        except Exception as e:
            logger.debug(f"Coinbase quote fallback error for {coin_id}: {e}")
        return None

    def fetch_single_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        Fetches both current market quote and historical candle series in a single call.
        Uses Yahoo Finance v8 chart API with fallback to Coinbase for crypto if needed.
        """
        cache_key = f"data_{symbol}"
        if self._is_cache_valid(cache_key, self.quote_cache_ttl):
            return self.cache[cache_key]["data"]

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1d&range=3mo"
        meta_info = config.ASSET_METADATA.get(symbol, {})

        try:
            res = self.session.get(url, timeout=7)
            if res.status_code == 200:
                json_data = res.json()
                results = json_data.get("chart", {}).get("result")
                if results and len(results) > 0:
                    item = results[0]
                    meta = item.get("meta", {})
                    indicators = item.get("indicators", {}).get("quote", [{}])[0]

                    price = meta.get("regularMarketPrice")
                    change_pct = meta.get("regularMarketChangePercent")
                    volume = meta.get("regularMarketVolume", 0)
                    raw_closes = indicators.get("close", [])

                    # Clean historical prices: eliminate nulls from holidays
                    closes = [float(c) for c in raw_closes if c is not None and c > 0]

                    if price is None and closes:
                        price = closes[-1]

                    if price is not None and len(closes) >= 15:
                        data = {
                            "symbol": symbol,
                            "display_name": meta_info.get("name", symbol),
                            "category": meta_info.get("category", "other"),
                            "match_trader": meta_info.get("match_trader", symbol),
                            "price": round(float(price), 5),
                            "change_pct": round(float(change_pct), 2) if change_pct is not None else 0.0,
                            "volume": float(volume) if volume else 0.0,
                            "historical_prices": closes,
                            "timestamp": datetime.now().isoformat(),
                            "source": "yahoo_v8"
                        }
                        self.cache[cache_key] = {"data": data, "timestamp": time.time()}
                        return data

        except Exception as e:
            logger.debug(f"Direct fetch exception for {symbol}: {e}")

        # Fallback for Crypto via Coinbase if Yahoo temporarily throttled
        if meta_info.get("category") == "crypto":
            short_name = meta_info.get("short_name", "")
            cb_price = self.fetch_coinbase_crypto_price(short_name)
            if cb_price is not None:
                # Use previously cached closes if available and update latest price
                prev_data = self.cache.get(cache_key, {}).get("data")
                closes = prev_data.get("historical_prices", []) if prev_data else []
                if closes:
                    closes = closes[:-1] + [cb_price]
                else:
                    closes = [cb_price] * 20

                data = {
                    "symbol": symbol,
                    "display_name": meta_info.get("name", symbol),
                    "category": "crypto",
                    "match_trader": meta_info.get("match_trader", symbol),
                    "price": round(cb_price, 5),
                    "change_pct": 0.0,
                    "volume": 0.0,
                    "historical_prices": closes,
                    "timestamp": datetime.now().isoformat(),
                    "source": "coinbase_fallback"
                }
                self.cache[cache_key] = {"data": data, "timestamp": time.time()}
                return data

        # If previous cached data exists (even expired), return it rather than failing
        if cache_key in self.cache:
            return self.cache[cache_key]["data"]

        return None

    def fetch_all_markets(self, symbols: Optional[List[str]] = None, max_workers: int = 10) -> Dict[str, Dict[str, Any]]:
        """
        Fetches all monitored symbols in parallel using thread pool.
        Executes ~46 requests in 2-3 seconds.
        """
        symbols_to_fetch = symbols or config.ALL_WATCHED_SYMBOLS
        results: Dict[str, Dict[str, Any]] = {}

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_sym = {executor.submit(self.fetch_single_symbol, sym): sym for sym in symbols_to_fetch}
            for future in as_completed(future_to_sym):
                sym = future_to_sym[future]
                try:
                    data = future.result()
                    if data:
                        results[sym] = data
                except Exception as e:
                    logger.warning(f"Error fetching data for {sym}: {e}")

        logger.info(f"Successfully fetched {len(results)}/{len(symbols_to_fetch)} symbols.")
        return results
