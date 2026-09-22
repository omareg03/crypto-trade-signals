"""
signal_engine.py

Advanced trade signal generator for QuantumTrader.
Uses real multi-timeframe and multi-indicator technical analysis to produce
actionable setups with dynamic stops, targets, and R:R ratios.
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
    display_name: str
    category: str
    direction: str          # 'LONG' or 'SHORT'
    strategy: str           # Strategy name
    confidence: int         # 0-100
    entry_price: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float
    risk_reward: float
    reasoning: str
    match_trader_symbol: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SignalEngine:
    """Generates and ranks trade signals from market data across all asset classes."""

    def __init__(self, analyzer: Optional[TechnicalAnalyzer] = None):
        self.analyzer = analyzer or TechnicalAnalyzer()
        self.logger = logging.getLogger(self.__class__.__name__)

    def _mean_reversion(self, symbol: str, prices: List[float], vol_pct: float) -> Optional[TradeSetup]:
        """Mean Reversion Strategy: RSI extreme + Bollinger Band touch."""
        if len(prices) < 20:
            return None

        rsi_res = self.analyzer.calculate_rsi(prices, 14)
        bb_res = self.analyzer.calculate_bollinger_bands(prices, 20, 2.0)

        rsi_val = rsi_res.get("value")
        upper_bb = bb_res.get("upper")
        lower_bb = bb_res.get("lower")
        mid_bb = bb_res.get("middle")

        if rsi_val is None or upper_bb is None or lower_bb is None or mid_bb is None:
            return None

        current = prices[-1]
        meta = config.ASSET_METADATA.get(symbol, {})
        display_name = meta.get("name", symbol)
        category = meta.get("category", "other")
        mt_sym = meta.get("match_trader", symbol)

        # Bullish Mean Reversion: Oversold RSI (<35) and price near or below lower BB
        if rsi_val <= 35.0 and current <= lower_bb * 1.015:
            confidence = min(96, int(72 + (35.0 - rsi_val) * 1.6))
            stop_dist = max(current * vol_pct, current - lower_bb * 0.985)
            stop_loss = current - stop_dist
            min_tp1 = current + (stop_dist * 1.8)
            tp1 = max(min_tp1, mid_bb)
            min_tp2 = current + (stop_dist * 2.8)
            tp2 = max(min_tp2, upper_bb)
            rr = round(abs(tp1 - current) / max(1e-6, abs(current - stop_loss)), 2)

            return TradeSetup(
                symbol=symbol,
                display_name=display_name,
                category=category,
                direction="LONG",
                strategy="Mean Reversion",
                confidence=confidence,
                entry_price=round(current, 5),
                stop_loss=round(stop_loss, 5),
                take_profit_1=round(tp1, 5),
                take_profit_2=round(tp2, 5),
                risk_reward=rr,
                reasoning=f"RSI oversold ({rsi_val:.1f}), bounced off lower BB ({lower_bb:.2f})",
                match_trader_symbol=mt_sym
            )

        # Bearish Mean Reversion: Overbought RSI (>65) and price near or above upper BB
        elif rsi_val >= 65.0 and current >= upper_bb * 0.985:
            confidence = min(96, int(72 + (rsi_val - 65.0) * 1.6))
            stop_dist = max(current * vol_pct, upper_bb * 1.015 - current)
            stop_loss = current + stop_dist
            min_tp1 = current - (stop_dist * 1.8)
            tp1 = min(min_tp1, mid_bb)
            min_tp2 = current - (stop_dist * 2.8)
            tp2 = min(min_tp2, lower_bb)
            rr = round(abs(current - tp1) / max(1e-6, abs(stop_loss - current)), 2)

            return TradeSetup(
                symbol=symbol,
                display_name=display_name,
                category=category,
                direction="SHORT",
                strategy="Mean Reversion",
                confidence=confidence,
                entry_price=round(current, 5),
                stop_loss=round(stop_loss, 5),
                take_profit_1=round(tp1, 5),
                take_profit_2=round(tp2, 5),
                risk_reward=rr,
                reasoning=f"RSI overbought ({rsi_val:.1f}), rejected upper BB ({upper_bb:.2f})",
                match_trader_symbol=mt_sym
            )

        return None

    def _trend_following(self, symbol: str, prices: List[float], vol_pct: float) -> Optional[TradeSetup]:
        """Trend Following: EMA 9/21 cross + MACD confirmation."""
        if len(prices) < 35:
            return None

        ema_9 = self.analyzer.calculate_ema(prices, 9).get("value")
        ema_21 = self.analyzer.calculate_ema(prices, 21).get("value")
        macd_res = self.analyzer.calculate_macd(prices)
        macd_hist = macd_res.get("histogram")

        if ema_9 is None or ema_21 is None or macd_hist is None:
            return None

        current = prices[-1]
        meta = config.ASSET_METADATA.get(symbol, {})
        display_name = meta.get("name", symbol)
        category = meta.get("category", "other")
        mt_sym = meta.get("match_trader", symbol)

        # Bullish Trend: EMA9 > EMA21 and MACD histogram positive
        if ema_9 > ema_21 and macd_hist > 0:
            norm_hist = abs(macd_hist / current) if current > 0 else 0
            confidence = min(92, int(65 + min(25, norm_hist * 1500)))
            stop_dist = max(current * vol_pct, current - ema_21 * 0.995)
            stop_loss = current - stop_dist
            tp1 = current + (stop_dist * 1.8)
            tp2 = current + (stop_dist * 3.0)
            rr = round(abs(tp1 - current) / max(1e-6, abs(current - stop_loss)), 2)

            return TradeSetup(
                symbol=symbol,
                display_name=display_name,
                category=category,
                direction="LONG",
                strategy="Trend Following",
                confidence=confidence,
                entry_price=round(current, 5),
                stop_loss=round(stop_loss, 5),
                take_profit_1=round(tp1, 5),
                take_profit_2=round(tp2, 5),
                risk_reward=max(1.5, rr),
                reasoning=f"Bullish EMA9({ema_9:.2f}) > EMA21({ema_21:.2f}), MACD hist (+{macd_hist:.4f})",
                match_trader_symbol=mt_sym
            )

        # Bearish Trend: EMA9 < EMA21 and MACD histogram negative
        elif ema_9 < ema_21 and macd_hist < 0:
            norm_hist = abs(macd_hist / current) if current > 0 else 0
            confidence = min(92, int(65 + min(25, norm_hist * 1500)))
            stop_dist = max(current * vol_pct, ema_21 * 1.005 - current)
            stop_loss = current + stop_dist
            tp1 = current - (stop_dist * 1.8)
            tp2 = current - (stop_dist * 3.0)
            rr = round(abs(current - tp1) / max(1e-6, abs(stop_loss - current)), 2)

            return TradeSetup(
                symbol=symbol,
                display_name=display_name,
                category=category,
                direction="SHORT",
                strategy="Trend Following",
                confidence=confidence,
                entry_price=round(current, 5),
                stop_loss=round(stop_loss, 5),
                take_profit_1=round(tp1, 5),
                take_profit_2=round(tp2, 5),
                risk_reward=max(1.5, rr),
                reasoning=f"Bearish EMA9({ema_9:.2f}) < EMA21({ema_21:.2f}), MACD hist ({macd_hist:.4f})",
                match_trader_symbol=mt_sym
            )

        return None

    def _momentum(self, symbol: str, prices: List[float], vol_pct: float) -> Optional[TradeSetup]:
        """Momentum Strategy: RSI in active drive zone with supporting MACD velocity."""
        if len(prices) < 35:
            return None

        rsi_val = self.analyzer.calculate_rsi(prices, 14).get("value")
        macd_res = self.analyzer.calculate_macd(prices)
        macd_hist = macd_res.get("histogram")

        if rsi_val is None or macd_hist is None:
            return None

        current = prices[-1]
        meta = config.ASSET_METADATA.get(symbol, {})
        display_name = meta.get("name", symbol)
        category = meta.get("category", "other")
        mt_sym = meta.get("match_trader", symbol)

        # Bullish Momentum: RSI in power zone 52-68 with positive histogram
        if 52.0 <= rsi_val <= 68.0 and macd_hist > 0:
            confidence = min(88, int(60 + (rsi_val - 50.0) * 1.4))
            stop_dist = current * vol_pct * 1.1
            stop_loss = current - stop_dist
            tp1 = current + (stop_dist * 1.85)
            tp2 = current + (stop_dist * 3.1)
            rr = round(abs(tp1 - current) / max(1e-6, abs(current - stop_loss)), 2)

            return TradeSetup(
                symbol=symbol,
                display_name=display_name,
                category=category,
                direction="LONG",
                strategy="Momentum",
                confidence=confidence,
                entry_price=round(current, 5),
                stop_loss=round(stop_loss, 5),
                take_profit_1=round(tp1, 5),
                take_profit_2=round(tp2, 5),
                risk_reward=max(1.5, rr),
                reasoning=f"Momentum: RSI {rsi_val:.1f} bullish zone, expanding MACD (+{macd_hist:.4f})",
                match_trader_symbol=mt_sym
            )

        # Bearish Momentum: RSI in sell zone 32-48 with negative histogram
        elif 32.0 <= rsi_val <= 48.0 and macd_hist < 0:
            confidence = min(88, int(60 + (50.0 - rsi_val) * 1.4))
            stop_dist = current * vol_pct * 1.1
            stop_loss = current + stop_dist
            tp1 = current - (stop_dist * 1.85)
            tp2 = current - (stop_dist * 3.1)
            rr = round(abs(current - tp1) / max(1e-6, abs(stop_loss - current)), 2)

            return TradeSetup(
                symbol=symbol,
                display_name=display_name,
                category=category,
                direction="SHORT",
                strategy="Momentum",
                confidence=confidence,
                entry_price=round(current, 5),
                stop_loss=round(stop_loss, 5),
                take_profit_1=round(tp1, 5),
                take_profit_2=round(tp2, 5),
                risk_reward=max(1.5, rr),
                reasoning=f"Momentum: RSI {rsi_val:.1f} bearish zone, expanding MACD ({macd_hist:.4f})",
                match_trader_symbol=mt_sym
            )

        return None

    def _breakout(self, symbol: str, prices: List[float], vol_pct: float) -> Optional[TradeSetup]:
        """Breakout Strategy: Price crossing outside Bollinger Bands with range expansion."""
        if len(prices) < 25:
            return None

        bb = self.analyzer.calculate_bollinger_bands(prices, 20, 2.0)
        upper = bb.get("upper")
        lower = bb.get("lower")
        mid = bb.get("middle")
        bandwidth = bb.get("bandwidth", 0.0)

        if upper is None or lower is None or mid is None:
            return None

        current = prices[-1]
        prev_close = prices[-2] if len(prices) >= 2 else current
        meta = config.ASSET_METADATA.get(symbol, {})
        display_name = meta.get("name", symbol)
        category = meta.get("category", "other")
        mt_sym = meta.get("match_trader", symbol)

        # Bullish Breakout: Previous close below upper BB, current close cleanly breaking above
        if prev_close <= upper and current > upper:
            confidence = min(86, int(64 + min(20, bandwidth * 200)))
            stop_dist = max(current * vol_pct, current - mid)
            stop_loss = current - stop_dist
            tp1 = current + (stop_dist * 2.0)
            tp2 = current + (stop_dist * 3.5)
            rr = round(abs(tp1 - current) / max(1e-6, abs(current - stop_loss)), 2)

            return TradeSetup(
                symbol=symbol,
                display_name=display_name,
                category=category,
                direction="LONG",
                strategy="Breakout",
                confidence=confidence,
                entry_price=round(current, 5),
                stop_loss=round(stop_loss, 5),
                take_profit_1=round(tp1, 5),
                take_profit_2=round(tp2, 5),
                risk_reward=max(1.5, rr),
                reasoning=f"Volatility Breakout: Clean close above upper BB ({upper:.2f})",
                match_trader_symbol=mt_sym
            )

        # Bearish Breakdown: Previous close above lower BB, current close cleanly breaking below
        elif prev_close >= lower and current < lower:
            confidence = min(86, int(64 + min(20, bandwidth * 200)))
            stop_dist = max(current * vol_pct, mid - current)
            stop_loss = current + stop_dist
            tp1 = current - (stop_dist * 2.0)
            tp2 = current - (stop_dist * 3.5)
            rr = round(abs(current - tp1) / max(1e-6, abs(stop_loss - current)), 2)

            return TradeSetup(
                symbol=symbol,
                display_name=display_name,
                category=category,
                direction="SHORT",
                strategy="Breakout",
                confidence=confidence,
                entry_price=round(current, 5),
                stop_loss=round(stop_loss, 5),
                take_profit_1=round(tp1, 5),
                take_profit_2=round(tp2, 5),
                risk_reward=max(1.5, rr),
                reasoning=f"Volatility Breakdown: Clean close below lower BB ({lower:.2f})",
                match_trader_symbol=mt_sym
            )

        return None

    def _adaptive_trend(self, symbol: str, prices: List[float], vol_pct: float) -> Optional[TradeSetup]:
        """
        Adaptive Trend Baseline: Ensures every monitored asset can be scored and ranked.
        Guarantees that at all times a full Top 30 list is readily available.
        """
        if len(prices) < 20:
            return None

        current = prices[-1]
        sma_20 = self.analyzer.calculate_sma(prices, 20).get("value")
        rsi_val = self.analyzer.calculate_rsi(prices, 14).get("value") or 50.0

        if sma_20 is None:
            return None

        meta = config.ASSET_METADATA.get(symbol, {})
        display_name = meta.get("name", symbol)
        category = meta.get("category", "other")
        mt_sym = meta.get("match_trader", symbol)

        is_bullish = current >= sma_20
        direction = "LONG" if is_bullish else "SHORT"
        confidence = int(52 + abs(rsi_val - 50.0) * 0.4)
        confidence = min(68, max(50, confidence))

        stop_dist = current * vol_pct * 1.2
        if direction == "LONG":
            stop_loss = current - stop_dist
            tp1 = current + (stop_dist * 1.7)
            tp2 = current + (stop_dist * 2.8)
        else:
            stop_loss = current + stop_dist
            tp1 = current - (stop_dist * 1.7)
            tp2 = current - (stop_dist * 2.8)

        rr = round(abs(tp1 - current) / max(1e-6, abs(stop_loss - current)), 2)

        return TradeSetup(
            symbol=symbol,
            display_name=display_name,
            category=category,
            direction=direction,
            strategy="Trend Continuation",
            confidence=confidence,
            entry_price=round(current, 5),
            stop_loss=round(stop_loss, 5),
            take_profit_1=round(tp1, 5),
            take_profit_2=round(tp2, 5),
            risk_reward=max(1.5, rr),
            reasoning=f"Baseline: Price {'above' if is_bullish else 'below'} 20-day SMA, RSI={rsi_val:.1f}",
            match_trader_symbol=mt_sym
        )

    def score_symbol(self, symbol: str, prices: List[float]) -> Optional[TradeSetup]:
        """Evaluates all strategies for a single symbol and selects the highest confidence setup."""
        if not prices or len(prices) < 15:
            return None

        vol_pct = self.analyzer.calculate_volatility_atr_proxy(prices, 14)

        strategies = [
            self._mean_reversion,
            self._trend_following,
            self._momentum,
            self._breakout
        ]

        best_setup = None
        for strategy_fn in strategies:
            try:
                setup = strategy_fn(symbol, prices, vol_pct)
                if setup:
                    if best_setup is None or setup.confidence > best_setup.confidence:
                        best_setup = setup
            except Exception as e:
                self.logger.debug(f"Strategy {strategy_fn.__name__} error for {symbol}: {e}")

        # If no specific setup fired, fall back to adaptive trend so every symbol has a score
        if best_setup is None:
            best_setup = self._adaptive_trend(symbol, prices, vol_pct)

        return best_setup

    def scan_all_symbols(self, market_data_map: Dict[str, Dict[str, Any]], limit: int = 30) -> List[TradeSetup]:
        """
        Scores all available symbols and returns the top trade setups ranked by confidence descending.
        Guarantees up to `limit` (default 30) top setups.
        """
        all_setups = []

        for symbol, data in market_data_map.items():
            prices = data.get("historical_prices", [])
            if prices and len(prices) >= 15:
                try:
                    setup = self.score_symbol(symbol, prices)
                    if setup:
                        all_setups.append(setup)
                except Exception as e:
                    self.logger.warning(f"Error scoring setup for {symbol}: {e}")

        # Sort by confidence descending, then by risk_reward descending
        all_setups.sort(key=lambda s: (s.confidence, s.risk_reward), reverse=True)
        return all_setups[:limit]
