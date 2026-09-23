"""
technical_analysis.py

Pure Python technical indicators engine for QuantumTrader.
Matches the original QuantumTrader mathematical models and indicators.
Zero external dependencies (no numpy/pandas required).
"""
from typing import List, Dict, Any, Optional
import math
import logging

logger = logging.getLogger(__name__)


class TechnicalAnalyzer:
    """Calculates technical indicators without numpy/pandas dependencies."""

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
        ema = sum(prices[:period]) / float(period)  # SMA seed
        for price in prices[period:]:
            ema = (price - ema) * multiplier + ema
        return {"value": round(ema, 6), "interpretation": "trend"}

    @staticmethod
    def calculate_rsi(prices: List[float], period: int = 14) -> Dict[str, Any]:
        """
        Relative Strength Index (RSI).
        Uses Wilder's smoothing technique.
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
            return {"value": 100.0, "interpretation": "overbought"}

        rs = avg_gain / avg_loss
        rsi = 100.0 - (100.0 / (1.0 + rs))

        # Smoothed Wilder's RSI
        for i in range(period, len(prices) - 1):
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
        """MACD (Moving Average Convergence Divergence) with Signal Line and Histogram."""
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

        signal_line = TechnicalAnalyzer.calculate_ema(macd_line, signal)["value"]
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
            return {"upper": None, "middle": None, "lower": None, "bandwidth": 0.0, "interpretation": "insufficient data"}

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
    def calculate_atr(highs: List[float], lows: List[float], closes: List[float], period: int = 14) -> Dict[str, Any]:
        """Average True Range (ATR)."""
        if len(highs) < period + 1 or len(lows) < period + 1 or len(closes) < period + 1:
            return {"value": None, "interpretation": "insufficient data"}

        true_ranges = []
        for i in range(1, len(highs)):
            tr = max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1])
            )
            true_ranges.append(tr)

        atr = sum(true_ranges[-period:]) / float(period)
        return {"value": round(atr, 6), "interpretation": "volatility"}

    @staticmethod
    def calculate_stochastic(highs: List[float], lows: List[float], closes: List[float], k_period: int = 14) -> Dict[str, Any]:
        """Stochastic Oscillator (%K)."""
        if len(highs) < k_period or len(lows) < k_period or len(closes) < k_period:
            return {"value": None, "interpretation": "insufficient data"}

        recent_highs = highs[-k_period:]
        recent_lows = lows[-k_period:]
        current_close = closes[-1]

        highest_high = max(recent_highs)
        lowest_low = min(recent_lows)

        if highest_high == lowest_low:
            k = 50.0
        else:
            k = 100.0 * ((current_close - lowest_low) / (highest_high - lowest_low))

        interpretation = "neutral"
        if k > 80.0:
            interpretation = "overbought"
        elif k < 20.0:
            interpretation = "oversold"

        return {"value": round(k, 2), "interpretation": interpretation}

    @staticmethod
    def generate_signals(prices: List[float]) -> Dict[str, Any]:
        """Combined multi-indicator signal generator."""
        if len(prices) < 35:
            return {"signal": "HOLD", "confidence": 0.0, "reason": "insufficient data"}

        rsi = TechnicalAnalyzer.calculate_rsi(prices)
        macd = TechnicalAnalyzer.calculate_macd(prices)
        bb = TechnicalAnalyzer.calculate_bollinger_bands(prices)

        score = 0
        if rsi.get("interpretation") == "oversold":
            score += 1
        elif rsi.get("interpretation") == "overbought":
            score -= 1

        if macd.get("interpretation") == "bullish":
            score += 1
        elif macd.get("interpretation") == "bearish":
            score -= 1

        if bb.get("interpretation") == "oversold":
            score += 1
        elif bb.get("interpretation") == "overbought":
            score -= 1

        signal = "HOLD"
        if score >= 2:
            signal = "BUY"
        elif score <= -2:
            signal = "SELL"

        return {
            "signal": signal,
            "confidence": round(abs(score) / 3.0, 2),
            "reason": f"Score: {score} based on RSI, MACD, BB"
        }

    @staticmethod
    def calculate_volatility_atr_proxy(prices: List[float], period: int = 14) -> float:
        """Calculates an ATR volatility proxy from closing prices for dynamic position sizing."""
        if not prices or len(prices) < 2:
            return 0.02

        pct_changes = []
        for i in range(1, len(prices)):
            if prices[i - 1] > 0:
                pct = abs(prices[i] - prices[i - 1]) / prices[i - 1]
                pct_changes.append(pct)

        sample = pct_changes[-period:] if len(pct_changes) >= period else pct_changes
        if not sample:
            return 0.02

        avg_vol = sum(sample) / float(len(sample))
        return max(0.005, min(0.08, avg_vol * 1.5))
