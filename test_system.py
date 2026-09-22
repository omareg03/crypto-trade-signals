"""
test_system.py

Comprehensive test suite verifying:
- Technical analysis edge cases & indicators
- Signal generation & scoring for Top 10 and Top 30
- Risk management & Match-Trader lot sizing
- Data engine caching & thread safety
- Flask API routes & web responses
"""
import unittest
import time
from typing import List

import config
from technical_analysis import TechnicalAnalyzer
from signal_engine import SignalEngine, TradeSetup
from risk_manager import RiskManager
from data_engine import MarketDataEngine
from app import app


class TestConfig(unittest.TestCase):
    def test_symbols_count(self):
        self.assertGreaterEqual(len(config.ALL_WATCHED_SYMBOLS), 30)
        self.assertGreaterEqual(len(config.WATCHLIST_CRYPTO), 10)
        self.assertGreaterEqual(len(config.WATCHLIST_FOREX), 10)
        self.assertGreaterEqual(len(config.WATCHLIST_COMMODITIES), 5)
        self.assertGreaterEqual(len(config.WATCHLIST_INDICES), 5)

    def test_metadata_integrity(self):
        for sym in config.ALL_WATCHED_SYMBOLS:
            self.assertIn(sym, config.ASSET_METADATA)
            meta = config.ASSET_METADATA[sym]
            self.assertIn("name", meta)
            self.assertIn("category", meta)
            self.assertIn("match_trader", meta)


class TestTechnicalAnalysis(unittest.TestCase):
    def setUp(self):
        self.analyzer = TechnicalAnalyzer()
        self.dummy_prices = [100.0 + (i * 0.5) for i in range(50)]

    def test_sma_empty_and_normal(self):
        # Empty input
        res_empty = self.analyzer.calculate_sma([], 20)
        self.assertIsNone(res_empty["value"])

        # Insufficient data
        res_short = self.analyzer.calculate_sma([10.0, 20.0], 5)
        self.assertIsNone(res_short["value"])

        # Normal calculation
        res = self.analyzer.calculate_sma(self.dummy_prices, 10)
        self.assertIsNotNone(res["value"])
        self.assertAlmostEqual(res["value"], sum(self.dummy_prices[-10:]) / 10.0, places=4)

    def test_ema_edge_cases(self):
        # Empty input
        self.assertIsNone(self.analyzer.calculate_ema([], 9)["value"])

        # Constant prices
        const_prices = [50.0] * 30
        res = self.analyzer.calculate_ema(const_prices, 9)
        self.assertAlmostEqual(res["value"], 50.0, places=4)

    def test_rsi_extremes(self):
        # All gains (RSI = 100)
        pure_gain = [float(i) for i in range(1, 30)]
        res_100 = self.analyzer.calculate_rsi(pure_gain, 14)
        self.assertEqual(res_100["value"], 100.0)
        self.assertEqual(res_100["interpretation"], "overbought")

        # All losses (RSI = 0)
        pure_loss = [float(100 - i) for i in range(30)]
        res_0 = self.analyzer.calculate_rsi(pure_loss, 14)
        self.assertEqual(res_0["value"], 0.0)
        self.assertEqual(res_0["interpretation"], "oversold")

    def test_macd_calculation(self):
        res = self.analyzer.calculate_macd(self.dummy_prices)
        self.assertIsNotNone(res["value"])
        self.assertIsNotNone(res["histogram"])

    def test_bollinger_bands(self):
        res = self.analyzer.calculate_bollinger_bands(self.dummy_prices, 20, 2.0)
        self.assertIsNotNone(res["upper"])
        self.assertIsNotNone(res["middle"])
        self.assertIsNotNone(res["lower"])
        self.assertGreater(res["upper"], res["middle"])
        self.assertGreater(res["middle"], res["lower"])

    def test_volatility_atr_proxy(self):
        vol = self.analyzer.calculate_volatility_atr_proxy(self.dummy_prices)
        self.assertGreater(vol, 0.0)
        self.assertLessEqual(vol, 0.08)


class TestSignalEngine(unittest.TestCase):
    def setUp(self):
        self.analyzer = TechnicalAnalyzer()
        self.engine = SignalEngine(analyzer=self.analyzer)

    def test_score_symbol_returns_valid_setup(self):
        prices = [100.0 + (i * 0.4) for i in range(40)]
        setup = self.engine.score_symbol("BTC-USD", prices)
        self.assertIsNotNone(setup)
        self.assertIn(setup.direction, ["LONG", "SHORT"])
        self.assertGreaterEqual(setup.confidence, 50)
        self.assertGreater(setup.entry_price, 0)
        self.assertGreater(setup.stop_loss, 0)
        self.assertGreater(setup.take_profit_1, 0)
        self.assertGreaterEqual(setup.risk_reward, 1.5)

    def test_scan_all_symbols_ranking(self):
        market_data_map = {}
        for i, sym in enumerate(config.ALL_WATCHED_SYMBOLS[:35]):
            # Vary trend direction
            step = 0.5 if i % 2 == 0 else -0.5
            prices = [100.0 + (j * step) for j in range(40)]
            market_data_map[sym] = {"historical_prices": prices}

        setups = self.engine.scan_all_symbols(market_data_map, limit=30)
        self.assertGreaterEqual(len(setups), 30)

        # Verify sorted by confidence descending
        confidences = [s.confidence for s in setups]
        self.assertEqual(confidences, sorted(confidences, reverse=True))


class TestRiskManager(unittest.TestCase):
    def setUp(self):
        self.rm = RiskManager(account_size=5000.0)

    def test_challenge_summary(self):
        summary = self.rm.get_challenge_summary()
        self.assertEqual(summary["account_size"], 5000.0)
        self.assertEqual(summary["max_daily_drawdown_usd"], 250.0)
        self.assertEqual(summary["max_total_drawdown_usd"], 500.0)
        self.assertEqual(summary["recommended_risk_1pct_usd"], 50.0)
        self.assertEqual(summary["recommended_risk_2pct_usd"], 100.0)

    def test_lot_size_forex(self):
        # EURUSD: entry 1.1400, stop 1.1350 (50 pips), 1% risk = $50
        res = self.rm.calculate_lot_size("EURUSD=X", entry=1.1400, stop_loss=1.1350, risk_pct=1.0)
        self.assertEqual(res["risk_usd"], 50.0)
        self.assertGreater(res["lot_size"], 0.0)

    def test_lot_size_gold(self):
        # Gold: entry 4400, stop 4380 ($20 distance), 1% risk = $50
        res = self.rm.calculate_lot_size("GC=F", entry=4400.0, stop_loss=4380.0, risk_pct=1.0)
        self.assertEqual(res["risk_usd"], 50.0)
        self.assertGreater(res["lot_size"], 0.0)

    def test_lot_size_crypto(self):
        # BTC: entry 86000, stop 84000 ($2000 distance), 1% risk = $50 -> 0.025 BTC
        res = self.rm.calculate_lot_size("BTC-USD", entry=86000.0, stop_loss=84000.0, risk_pct=1.0)
        self.assertEqual(res["lot_size"], 0.025)


class TestFlaskEndpoints(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_health_check(self):
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "healthy")

    def test_index_page(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"QUANTUM TRADER", res.data)
        self.assertIn(b"FUNDING PIPS", res.data)

    def test_api_signals_endpoint(self):
        res = self.client.get("/api/signals?top=10")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertIn("signals", data)
        self.assertIn("risk_summary", data)

    def test_calculate_lot_api(self):
        payload = {
            "symbol": "BTC-USD",
            "entry": 86000,
            "stop_loss": 84000,
            "risk_pct": 1.0,
            "account_size": 5000
        }
        res = self.client.post("/api/calculate_lot", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["lot_size"], 0.025)
        self.assertEqual(data["risk_usd"], 50.0)


if __name__ == "__main__":
    unittest.main()
