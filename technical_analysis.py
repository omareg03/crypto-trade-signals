"""
technical_analysis.py

Robust pure-Python technical analysis indicator engine.
Zero external dependencies (no numpy/pandas required).
Fast, reliable, and completely error-shielded.
"""
from typing import List, Dict, Any, Optional
import math
import logging

logger = logging.getLogger(__name__)


class TechnicalAnalyzer:
    """Calculates technical indicators with high performance and zero external dependencies."""

    @staticmethod
    def calculate_sma(prices: List[float], period: int) -> Dict[str, Any]:
        """Simple Moving Average (SMA)."""
        if not prices or len(prices) < period or period <= 0:
            return {"value": None, "interpretation": "insufficient data"}
        sma = sum(prices[-period:]) / float(period)
        return {"value": round(sma, 6), "interpretation": "baseline"}

    @staticmethod
    def calculate_ema(prices: List[float], period: int) -> Dict[str, Any]:
        """Exponential Moving Average (EMA)."""
        if not prices or len(prices) < period or period <= 0:
            return {"value": None, "interpretation": "insufficient data"}
        multiplier = 2.0 / (period + 1.0)
        # Seed with initial SMA
        ema = sum(prices[:period]) / float(period)
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return {"value": round(ema, 6), "interpretation": "trend"}

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> Dict[str, Any]:
        """
        Wilder's Smoothed Relative Strength Index (RSI).
        Returns value between 0 and 100.
        """
        if not prices or len(prices) < period + 1 or period <= 0:
            return {"value": None, "interpretation": "insufficient data"}

        gains = []
        losses = []
        for i in range(1, len(prices)):
            change = prices[i] - prices[i - 1]
            if change > 0:
                gains.append(change)
                losses.append(0.0)
            else:
                gains.append(0.0)
                losses.append(abs(change))

        if len(gains) < period:
            return {"value": None, "interpretation": "insufficient data"}

        avg_gain = sum(gains[:period]) / float(period)
        avg_loss = sum(losses[:period]) / float(period)

        if avg_loss == 0.0:
            rsi = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi = 100.0 - (100.0 / (1.0 + rs))

        # Wilder's smoothing for subsequent periods
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / float(period)
            avg_loss = (avg_loss * (period - 1) + losses[i]) / float(period)
            if avg_loss == 0.0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100.0 - (100.0 / (1.0 + rs))

        rsi = round(rsi, 2)
        interpretation = "neutral"
        if rsi >= 70.0:
            interpretation = "overbought"
        elif rsi <= 30.0:
            interpretation = "oversold"

        return {"value": rsi, "interpretation": interpretation}

    @staticmethod
    def calculate_macd(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Dict[str, Any]:
        """Moving Average Convergence Divergence (MACD) with Signal Line and Histogram."""
        if not prices or len(prices) < slow + signal:
            return {"value": None, "signal": None, "histogram": None, "interpretation": "insufficient data"}

        macd_line = []
        for i in range(slow, len(prices) + 1):
            f_ema = TechnicalAnalyzer.calculate_ema(prices[:i], fast)["value"]
            s_ema = TechnicalAnalyzer.calculate_ema(prices[:i], slow)["value"]
            if f_ema is not None and s_ema is not None:
                macd_line.append(f_ema - s_ema)

        if len(macd_line) < signal:
            return {"value": None, "signal": None, "histogram": None, "interpretation": "insufficient data"}

        signal_res = TechnicalAnalyzer.calculate_ema(macd_line, signal)
        signal_line = signal_res.get("value")
        current_macd = macd_line[-1]

        if signal_line is not None:
            hist = current_macd - signal_line
            interpretation = "bullish" if hist > 0 else "bearish"
        else:
            hist = None
            interpretation = "neutral"

        return {
            "value": round(current_macd, 6),
            "signal": round(signal_line, 6) if signal_line is not None else None,
            "histogram": round(hist, 6) if hist is not None else None,
            "interpretation": interpretation
        }

    @staticmethod
    def calculate_bollinger_bands(prices: List[float], period: int = 20, std_dev: float = 2.0) -> Dict[str, Any]:
        """Bollinger Bands (Upper, Middle, Lower, and Bandwidth)."""
        if not prices or len(prices) < period or period <= 0:
            return {"upper": None, "middle": None, "lower": None, "bandwidth": None, "interpretation": "insufficient data"}

        window = prices[-period:]
        sma = sum(window) / float(period)
        variance = sum((p - sma) ** 2 for p in window) / float(period)
        std = math.sqrt(variance)

        upper = sma + (std * std_dev)
        lower = sma - (std * std_dev)
        current = prices[-1]

        bandwidth = (upper - lower) / sma if sma > 0 else 0.0

        interpretation = "neutral"
        if current >= upper:
            interpretation = "overbought"
        elif current <= lower:
            interpretation = "oversold"

        return {
            "upper": round(upper, 6),
            "middle": round(sma, 6),
            "lower": round(lower, 6),
            "bandwidth": round(bandwidth, 4),
            "interpretation": interpretation
        }

    @staticmethod
    def calculate_volatility_atr_proxy(prices: List[float], period: int = 14) -> float:
        """
        Calculates an ATR volatility proxy from closing prices.
        Used for dynamic stop loss & take profit sizing when full OHLC is not fetched.
        """
        if not prices or len(prices) < 2:
            return 0.02  # default 2% volatility

        pct_changes = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0:
                pct = abs(prices[i] - prices[i - 1]) / prices[i - 1]
                pct_changes.append(pct)

        sample = pct_changes[-period:] if len(pct_changes) >= period else pct_changes
        if not sample:
            return 0.02

        avg_vol = sum(sample) / float(len(sample))
        # Ensure sensible bounds: minimum 0.5% (for stable forex), maximum 8% (for volatile crypto)
        return max(0.005, min(0.08, avg_vol * 1.5))
