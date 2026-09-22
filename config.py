"""
config.py

Comprehensive configuration for QuantumTrader 30-Symbol Multi-Asset Intelligence System.
Optimized for Funding Pips ($5,000 Challenge) via Match-Trader & Coinbase.
"""
import os

# Base Directory & Environment
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Refresh & Scanning Parameters
SCAN_REFRESH_INTERVAL_SECONDS = int(os.getenv("REFRESH_INTERVAL", "60"))
CACHE_QUOTES_TTL_SECONDS = 45
CACHE_HISTORICAL_TTL_SECONDS = 180

# Funding Pips & Match-Trader Risk Rules ($5,000 Account)
ACCOUNT_SIZE = float(os.getenv("ACCOUNT_SIZE", "5000.0"))
RISK_PER_TRADE_MIN_PCT = 1.0      # 1% = $50.00
RISK_PER_TRADE_MAX_PCT = 2.0      # 2% = $100.00
MAX_DAILY_DRAWDOWN_PCT = 5.0      # 5% = $250.00 hard stop
MAX_TOTAL_DRAWDOWN_PCT = 10.0     # 10% = $500.00 hard stop
MAX_CORRELATED_POSITIONS = 3
ALWAYS_ENFORCE_STOP_LOSS = True

# Asset Watchlists (46 Total Curated High-Liquidity Symbols)
WATCHLIST_CRYPTO = [
    "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "ADA-USD",
    "DOGE-USD", "AVAX-USD", "LINK-USD", "DOT-USD", "NEAR-USD",
    "LTC-USD", "BNB-USD"
]

WATCHLIST_FOREX = [
    "EURUSD=X", "GBPUSD=X", "JPY=X", "CAD=X", "AUDUSD=X",
    "CHF=X", "NZDUSD=X", "EURGBP=X", "EURJPY=X", "GBPJPY=X",
    "AUDJPY=X", "EURCAD=X"
]

WATCHLIST_COMMODITIES = [
    "GC=F", "SI=F", "CL=F", "BZ=F", "NG=F", "HG=F", "PL=F"
]

WATCHLIST_INDICES = [
    "^IXIC", "^GSPC", "^DJI", "^RUT", "^GDAXI", "^FTSE", "^N225"
]

WATCHLIST_STOCKS = [
    "NVDA", "TSLA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "AMD"
]

ALL_WATCHED_SYMBOLS = (
    WATCHLIST_CRYPTO +
    WATCHLIST_FOREX +
    WATCHLIST_COMMODITIES +
    WATCHLIST_INDICES +
    WATCHLIST_STOCKS
)

# Detailed Asset Metadata & Match-Trader / Funding Pips Cross-Reference
ASSET_METADATA = {
    # Crypto (24/7)
    "BTC-USD": {
        "name": "Bitcoin (BTC)",
        "short_name": "BTC",
        "category": "crypto",
        "match_trader": "BTCUSD",
        "coinbase": "BTC-USD",
        "pip_size": 1.0,
        "is_24_7": True
    },
    "ETH-USD": {
        "name": "Ethereum (ETH)",
        "short_name": "ETH",
        "category": "crypto",
        "match_trader": "ETHUSD",
        "coinbase": "ETH-USD",
        "pip_size": 0.1,
        "is_24_7": True
    },
    "SOL-USD": {
        "name": "Solana (SOL)",
        "short_name": "SOL",
        "category": "crypto",
        "match_trader": "SOLUSD",
        "coinbase": "SOL-USD",
        "pip_size": 0.01,
        "is_24_7": True
    },
    "XRP-USD": {
        "name": "XRP (Ripple)",
        "short_name": "XRP",
        "category": "crypto",
        "match_trader": "XRPUSD",
        "coinbase": "XRP-USD",
        "pip_size": 0.0001,
        "is_24_7": True
    },
    "ADA-USD": {
        "name": "Cardano (ADA)",
        "short_name": "ADA",
        "category": "crypto",
        "match_trader": "ADAUSD",
        "coinbase": "ADA-USD",
        "pip_size": 0.0001,
        "is_24_7": True
    },
    "DOGE-USD": {
        "name": "Dogecoin (DOGE)",
        "short_name": "DOGE",
        "category": "crypto",
        "match_trader": "DOGEUSD",
        "coinbase": "DOGE-USD",
        "pip_size": 0.00001,
        "is_24_7": True
    },
    "AVAX-USD": {
        "name": "Avalanche (AVAX)",
        "short_name": "AVAX",
        "category": "crypto",
        "match_trader": "AVAXUSD",
        "coinbase": "AVAX-USD",
        "pip_size": 0.01,
        "is_24_7": True
    },
    "LINK-USD": {
        "name": "Chainlink (LINK)",
        "short_name": "LINK",
        "category": "crypto",
        "match_trader": "LINKUSD",
        "coinbase": "LINK-USD",
        "pip_size": 0.01,
        "is_24_7": True
    },
    "DOT-USD": {
        "name": "Polkadot (DOT)",
        "short_name": "DOT",
        "category": "crypto",
        "match_trader": "DOTUSD",
        "coinbase": "DOT-USD",
        "pip_size": 0.01,
        "is_24_7": True
    },
    "NEAR-USD": {
        "name": "Near Protocol (NEAR)",
        "short_name": "NEAR",
        "category": "crypto",
        "match_trader": "NEARUSD",
        "coinbase": "NEAR-USD",
        "pip_size": 0.001,
        "is_24_7": True
    },
    "LTC-USD": {
        "name": "Litecoin (LTC)",
        "short_name": "LTC",
        "category": "crypto",
        "match_trader": "LTCUSD",
        "coinbase": "LTC-USD",
        "pip_size": 0.01,
        "is_24_7": True
    },
    "BNB-USD": {
        "name": "Binance Coin (BNB)",
        "short_name": "BNB",
        "category": "crypto",
        "match_trader": "BNBUSD",
        "coinbase": "BNB-USD",
        "pip_size": 0.1,
        "is_24_7": True
    },

    # Forex Majors & Crosses (24/5)
    "EURUSD=X": {
        "name": "EUR/USD",
        "short_name": "EURUSD",
        "category": "forex",
        "match_trader": "EURUSD",
        "coinbase": None,
        "pip_size": 0.0001,
        "is_24_7": False
    },
    "GBPUSD=X": {
        "name": "GBP/USD",
        "short_name": "GBPUSD",
        "category": "forex",
        "match_trader": "GBPUSD",
        "coinbase": None,
        "pip_size": 0.0001,
        "is_24_7": False
    },
    "JPY=X": {
        "name": "USD/JPY",
        "short_name": "USDJPY",
        "category": "forex",
        "match_trader": "USDJPY",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
    "CAD=X": {
        "name": "USD/CAD",
        "short_name": "USDCAD",
        "category": "forex",
        "match_trader": "USDCAD",
        "coinbase": None,
        "pip_size": 0.0001,
        "is_24_7": False
    },
    "AUDUSD=X": {
        "name": "AUD/USD",
        "short_name": "AUDUSD",
        "category": "forex",
        "match_trader": "AUDUSD",
        "coinbase": None,
        "pip_size": 0.0001,
        "is_24_7": False
    },
    "CHF=X": {
        "name": "USD/CHF",
        "short_name": "USDCHF",
        "category": "forex",
        "match_trader": "USDCHF",
        "coinbase": None,
        "pip_size": 0.0001,
        "is_24_7": False
    },
    "NZDUSD=X": {
        "name": "NZD/USD",
        "short_name": "NZDUSD",
        "category": "forex",
        "match_trader": "NZDUSD",
        "coinbase": None,
        "pip_size": 0.0001,
        "is_24_7": False
    },
    "EURGBP=X": {
        "name": "EUR/GBP",
        "short_name": "EURGBP",
        "category": "forex",
        "match_trader": "EURGBP",
        "coinbase": None,
        "pip_size": 0.0001,
        "is_24_7": False
    },
    "EURJPY=X": {
        "name": "EUR/JPY",
        "short_name": "EURJPY",
        "category": "forex",
        "match_trader": "EURJPY",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
    "GBPJPY=X": {
        "name": "GBP/JPY",
        "short_name": "GBPJPY",
        "category": "forex",
        "match_trader": "GBPJPY",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
    "AUDJPY=X": {
        "name": "AUD/JPY",
        "short_name": "AUDJPY",
        "category": "forex",
        "match_trader": "AUDJPY",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
    "EURCAD=X": {
        "name": "EUR/CAD",
        "short_name": "EURCAD",
        "category": "forex",
        "match_trader": "EURCAD",
        "coinbase": None,
        "pip_size": 0.0001,
        "is_24_7": False
    },

    # Commodities & Metals
    "GC=F": {
        "name": "Gold (XAU/USD)",
        "short_name": "GOLD",
        "category": "commodities",
        "match_trader": "XAUUSD",
        "coinbase": None,
        "pip_size": 0.1,
        "is_24_7": False
    },
    "SI=F": {
        "name": "Silver (XAG/USD)",
        "short_name": "SILVER",
        "category": "commodities",
        "match_trader": "XAGUSD",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
    "CL=F": {
        "name": "Crude Oil (WTI)",
        "short_name": "USOIL",
        "category": "commodities",
        "match_trader": "USOIL",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
    "BZ=F": {
        "name": "Brent Oil",
        "short_name": "UKOIL",
        "category": "commodities",
        "match_trader": "UKOIL",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
    "NG=F": {
        "name": "Natural Gas",
        "short_name": "NATGAS",
        "category": "commodities",
        "match_trader": "NGAS",
        "coinbase": None,
        "pip_size": 0.001,
        "is_24_7": False
    },
    "HG=F": {
        "name": "Copper",
        "short_name": "COPPER",
        "category": "commodities",
        "match_trader": "COPPER",
        "coinbase": None,
        "pip_size": 0.001,
        "is_24_7": False
    },
    "PL=F": {
        "name": "Platinum",
        "short_name": "PLATINUM",
        "category": "commodities",
        "match_trader": "XPTUSD",
        "coinbase": None,
        "pip_size": 0.1,
        "is_24_7": False
    },

    # Indices
    "^IXIC": {
        "name": "NASDAQ 100",
        "short_name": "US100",
        "category": "indices",
        "match_trader": "US100",
        "coinbase": None,
        "pip_size": 1.0,
        "is_24_7": False
    },
    "^GSPC": {
        "name": "S&P 500",
        "short_name": "US500",
        "category": "indices",
        "match_trader": "US500",
        "coinbase": None,
        "pip_size": 0.1,
        "is_24_7": False
    },
    "^DJI": {
        "name": "Dow Jones 30",
        "short_name": "US30",
        "category": "indices",
        "match_trader": "US30",
        "coinbase": None,
        "pip_size": 1.0,
        "is_24_7": False
    },
    "^RUT": {
        "name": "Russell 2000",
        "short_name": "US2000",
        "category": "indices",
        "match_trader": "US2000",
        "coinbase": None,
        "pip_size": 0.1,
        "is_24_7": False
    },
    "^GDAXI": {
        "name": "DAX 40",
        "short_name": "GER40",
        "category": "indices",
        "match_trader": "GER40",
        "coinbase": None,
        "pip_size": 1.0,
        "is_24_7": False
    },
    "^FTSE": {
        "name": "FTSE 100",
        "short_name": "UK100",
        "category": "indices",
        "match_trader": "UK100",
        "coinbase": None,
        "pip_size": 1.0,
        "is_24_7": False
    },
    "^N225": {
        "name": "Nikkei 225",
        "short_name": "JP225",
        "category": "indices",
        "match_trader": "JP225",
        "coinbase": None,
        "pip_size": 1.0,
        "is_24_7": False
    },

    # Top Stocks / Tech Movers
    "NVDA": {
        "name": "Nvidia (NVDA)",
        "short_name": "NVDA",
        "category": "stocks",
        "match_trader": "NVDA.US",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
    "TSLA": {
        "name": "Tesla (TSLA)",
        "short_name": "TSLA",
        "category": "stocks",
        "match_trader": "TSLA.US",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
    "MSFT": {
        "name": "Microsoft (MSFT)",
        "short_name": "MSFT",
        "category": "stocks",
        "match_trader": "MSFT.US",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
    "AAPL": {
        "name": "Apple (AAPL)",
        "short_name": "AAPL",
        "category": "stocks",
        "match_trader": "AAPL.US",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
    "AMZN": {
        "name": "Amazon (AMZN)",
        "short_name": "AMZN",
        "category": "stocks",
        "match_trader": "AMZN.US",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
    "GOOGL": {
        "name": "Alphabet (GOOGL)",
        "short_name": "GOOGL",
        "category": "stocks",
        "match_trader": "GOOGL.US",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
    "META": {
        "name": "Meta Platforms (META)",
        "short_name": "META",
        "category": "stocks",
        "match_trader": "META.US",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
    "AMD": {
        "name": "AMD (AMD)",
        "short_name": "AMD",
        "category": "stocks",
        "match_trader": "AMD.US",
        "coinbase": None,
        "pip_size": 0.01,
        "is_24_7": False
    },
}

# Category labels & icons
CATEGORY_CONFIG = {
    "all": {"label": "Top 30 All", "icon": "🎯"},
    "crypto": {"label": "Crypto", "icon": "₿"},
    "forex": {"label": "Forex", "icon": "💱"},
    "commodities": {"label": "Commodities", "icon": "🥇"},
    "indices": {"label": "Indices", "icon": "📊"},
    "stocks": {"label": "Stocks", "icon": "📈"}
}
