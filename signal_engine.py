"""
signal_engine.py

Trade signal generator for QuantumTrader.
Replicates the original QuantumTrader strategy calculations, confidence formula,
and reasoning output exactly, while providing dynamic support for Multi-Asset prop firm challenges.
"""
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime

from technical_analysis import TechnicalAnalyzer
import config

logger = logging.getLogger(__name__)


@dataclass
class TradeSetup:
    """Represents a scored trade opportunity."""
    symbol: str
    direction: str          # 'LONG' or 'SHORT'
    strategy: str           # Strategy name that triggered
    confidence: int         # 0-100
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    reasoning: str
    display_name: str = ""
    category: str = "other"
    match_trader_symbol: str = ""
    cleo_symbol: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SignalEngine:
    """Generates trade signals from market data using original technical analysis strategies."""

    def __init__(self, analyzer: Optional[TechnicalAnalyzer] = None):
        self.analyzer = analyzer or TechnicalAnalyzer()
        self.logger = logging.getLogger(self.__class__.__name__)

    @staticmethod
    def _format_macd_hist(hist: float) -> str:
        """Format MACD histogram with sign and clean precision."""
        if abs(hist) >= 1.0:
            return f"+{hist:.1f}" if hist > 0 else f"{hist:.1f}"
        return f"+{hist:.4f}" if hist > 0 else f"{hist:.4f}"

    def _trend_following(self, symbol: str, prices: List[float], vol_pct: Optional[float] = None) -> Optional[TradeSetup]:
        """EMA crossover (9/21) + MACD confirmation."""
        if len(prices) < 35:
            return None

        ema_9 = self.analyzer.calculate_ema(prices, 9)
        ema_21 = self.analyzer.calculate_ema(prices, 21)
        macd = self.analyzer.calculate_macd(prices)

        if not all([ema_9.get("value"), ema_21.get("value"), macd.get("value")]):
            return None

        current = prices[-1]
        ema9_val = ema_9["value"]
        ema21_val = ema_21["value"]
        macd_hist = macd.get("histogram", 0) or 0

        meta = config.ASSET_METADATA.get(symbol, {})
        display_name = meta.get("name", symbol)
        category = meta.get("category", "other")
        mt_sym = meta.get("match_trader", symbol)
        cleo_sym = meta.get("cleo_symbol", symbol.replace("-USD", "USDT"))

        hist_str = self._format_macd_hist(macd_hist)

        # Bullish: EMA9 > EMA21 and MACD histogram positive
        if ema9_val > ema21_val and macd_hist > 0:
            confidence = min(90, 60 + int(abs(macd_hist / current * 1000)))
            stop = current * 0.97
            tp1 = current * 1.045
            tp2 = current * 1.06
            rr = round((tp1 - current) / (current - stop), 2)
            return TradeSetup(
                symbol=symbol,
                direction="LONG",
                strategy="Trend Following",
                confidence=confidence,
                entry_price=current,
                stop_loss=stop,
                take_profit_1=tp1,
                take_profit_2=tp2,
                risk_reward=rr,
                reasoning=f"EMA9({ema9_val:.2f}) > EMA21({ema21_val:.2f}), MACD hist {hist_str}",
                display_name=display_name,
                category=category,
                match_trader_symbol=mt_sym,
                cleo_symbol=cleo_sym
            )
        # Bearish: EMA9 < EMA21 and MACD histogram negative
        elif ema9_val < ema21_val and macd_hist < 0:
            confidence = min(90, 60 + int(abs(macd_hist / current * 1000)))
            stop = current * 1.03
            tp1 = current * 0.955
            tp2 = current * 0.94
            rr = round((current - tp1) / (stop - current), 2)
            return TradeSetup(
                symbol=symbol,
                direction="SHORT",
                strategy="Trend Following",
                confidence=confidence,
                entry_price=current,
                stop_loss=stop,
                take_profit_1=tp1,
                take_profit_2=tp2,
                risk_reward=rr,
                reasoning=f"EMA9({ema9_val:.2f}) < EMA21({ema21_val:.2f}), MACD hist {hist_str}",
                display_name=display_name,
                category=category,
                match_trader_symbol=mt_sym,
                cleo_symbol=cleo_sym
            )
        return None

    def _mean_reversion(self, symbol: str, prices: List[float], vol_pct: Optional[float] = None) -> Optional[TradeSetup]:
        """RSI oversold/overbought + Bollinger Band touches."""
        if len(prices) < 20:
            return None

        rsi = self.analyzer.calculate_rsi(prices)
        bb = self.analyzer.calculate_bollinger_bands(prices)

        rsi_val = rsi.get("value")
        if rsi_val is None or bb.get("upper") is None or bb.get("lower") is None or bb.get("middle") is None:
            return None

        current = prices[-1]
        meta = config.ASSET_METADATA.get(symbol, {})
        display_name = meta.get("name", symbol)
        category = meta.get("category", "other")
        mt_sym = meta.get("match_trader", symbol)
        cleo_sym = meta.get("cleo_symbol", symbol.replace("-USD", "USDT"))

        # Oversold + price near lower BB = BUY
        if rsi_val < 30 and current <= bb["lower"] * 1.01:
            confidence = min(95, 70 + int((30 - rsi_val) * 2))
            stop = current * 0.96
            tp1 = bb["middle"]
            tp2 = bb["upper"]
            rr = round((bb["middle"] - current) / (current - current * 0.96), 2)
            return TradeSetup(
                symbol=symbol,
                direction="LONG",
                strategy="Mean Reversion",
                confidence=confidence,
                entry_price=current,
                stop_loss=stop,
                take_profit_1=tp1,
                take_profit_2=tp2,
                risk_reward=rr,
                reasoning=f"RSI oversold ({rsi_val:.1f}), price near lower BB ({bb['lower']:.2f})",
                display_name=display_name,
                category=category,
                match_trader_symbol=mt_sym,
                cleo_symbol=cleo_sym
            )
        # Overbought + price near upper BB = SELL
        elif rsi_val > 70 and current >= bb["upper"] * 0.99:
            confidence = min(95, 70 + int((rsi_val - 70) * 2))
            stop = current * 1.04
            tp1 = bb["middle"]
            tp2 = bb["lower"]
            rr = round((current - bb["middle"]) / (current * 1.04 - current), 2)
            return TradeSetup(
                symbol=symbol,
                direction="SHORT",
                strategy="Mean Reversion",
                confidence=confidence,
                entry_price=current,
                stop_loss=stop,
                take_profit_1=tp1,
                take_profit_2=tp2,
                risk_reward=rr,
                reasoning=f"RSI overbought ({rsi_val:.1f}), price near upper BB ({bb['upper']:.2f})",
                display_name=display_name,
                category=category,
                match_trader_symbol=mt_sym,
                cleo_symbol=cleo_sym
            )
        return None

    def _momentum(self, symbol: str, prices: List[float], vol_pct: Optional[float] = None) -> Optional[TradeSetup]:
        """RSI momentum + MACD histogram acceleration."""
        if len(prices) < 35:
            return None

        rsi = self.analyzer.calculate_rsi(prices)
        macd = self.analyzer.calculate_macd(prices)

        rsi_val = rsi.get("value")
        macd_hist = macd.get("histogram")
        if rsi_val is None or macd_hist is None:
            return None

        current = prices[-1]
        meta = config.ASSET_METADATA.get(symbol, {})
        display_name = meta.get("name", symbol)
        category = meta.get("category", "other")
        mt_sym = meta.get("match_trader", symbol)
        cleo_sym = meta.get("cleo_symbol", symbol.replace("-USD", "USDT"))

        hist_str = self._format_macd_hist(macd_hist)

        # Strong upward momentum: RSI 50-70 + positive accelerating MACD
        if 50 < rsi_val < 70 and macd_hist > 0:
            confidence = min(85, 55 + int(rsi_val - 50))
            return TradeSetup(
                symbol=symbol,
                direction="LONG",
                strategy="Momentum",
                confidence=confidence,
                entry_price=current,
                stop_loss=current * 0.975,
                take_profit_1=current * 1.04,
                take_profit_2=current * 1.08,
                risk_reward=round(0.04 / 0.025, 2),
                reasoning=f"Momentum: RSI={rsi_val:.1f} (bullish zone), MACD hist={hist_str}",
                display_name=display_name,
                category=category,
                match_trader_symbol=mt_sym,
                cleo_symbol=cleo_sym
            )
        return None

    def score_symbol(self, symbol: str, prices: List[float]) -> Optional[TradeSetup]:
        """Score the best setup for a symbol by running all strategies and selecting highest confidence."""
        if not prices or len(prices) < 15:
            return None

        best_setup = None
        strategies = [
            self._mean_reversion,
            self._trend_following,
            self._momentum,
        ]

        for strategy_fn in strategies:
            try:
                setup = strategy_fn(symbol, prices)
                if setup and (best_setup is None or setup.confidence > best_setup.confidence):
                    best_setup = setup
            except Exception as e:
                self.logger.debug(f"Strategy {strategy_fn.__name__} error for {symbol}: {e}")

        return best_setup

    def score_setup(self, symbol: str, prices: List[float]) -> Optional[TradeSetup]:
        """Legacy alias matching original QuantumTrader interface."""
        return self.score_symbol(symbol, prices)

    def scan_all_symbols(self, market_data_map: Dict[str, Dict[str, Any]], limit: int = 30) -> List[TradeSetup]:
        """
        Scores all available symbols and returns the top trade setups ranked by confidence descending.
        Guarantees up to `limit` setups (e.g. 10 or 30).
        """
        all_setups = []

        for symbol, data in market_data_map.items():
            prices = data.get("historical_prices", [])
            if prices and len(prices) >= 15:
                try:
                    setup = self.score_symbol(symbol, prices)
                    if setup and setup.confidence >= 50:
                        all_setups.append(setup)
                except Exception as e:
                    self.logger.warning(f"Error scoring setup for {symbol}: {e}")

        # Sort by confidence descending, then by risk_reward descending
        all_setups.sort(key=lambda s: (s.confidence, s.risk_reward), reverse=True)
        return all_setups[:limit]

    def scan_all_markets_live(self, all_data: Dict[str, Any], data_engine) -> List[TradeSetup]:
        """
        Legacy scan interface matching original QuantumTrader main.py.
        Scans all categories and fetches historical prices using data_engine.
        """
        setups = []

        # When all_data is a dict of lists (category -> list of items)
        if isinstance(all_data, dict):
            for category, items in all_data.items():
                if isinstance(items, list):
                    for item in items:
                        if not item:
                            continue
                        symbol = item.get("symbol", "")
                        if not symbol:
                            continue
                        try:
                            prices = data_engine.fetch_historical_prices(symbol, period="3mo") if hasattr(data_engine, "fetch_historical_prices") else item.get("historical_prices")
                            if prices and len(prices) >= 15:
                                setup = self.score_setup(symbol, prices)
                                if setup and setup.confidence >= 50:
                                    setups.append(setup)
                        except Exception as e:
                            self.logger.debug(f"Could not analyze {symbol}: {e}")
                elif isinstance(items, dict):
                    # Market data map (symbol -> dict)
                    prices = items.get("historical_prices", [])
                    if prices and len(prices) >= 15:
                        setup = self.score_setup(category, prices)
                        if setup and setup.confidence >= 50:
                            setups.append(setup)

        setups.sort(key=lambda x: (x.confidence, x.risk_reward), reverse=True)
        return setups
