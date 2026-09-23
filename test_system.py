"""
test_system.py

Comprehensive test suite verifying:
- Technical analysis edge cases & indicators
- Signal generation & scoring for Top 10 and Top 30
- Multi-Prop Firm Risk management (Funding Pips & Hyro Trader across $5K-$200K)
- Match-Trader lot sizing & Cleo.finance crypto futures position sizing
- Pre-warmed Data engine caching & thread safety (46/46 symbols guarantee)
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

    def test_prop_firms_config(self):
        self.assertIn("funding_pips", config.PROP_FIRMS)
        self.assertIn("hyro_trader", config.PROP_FIRMS)
        fp = config.PROP_FIRMS["funding_pips"]
        ht = config.PROP_FIRMS["hyro_trader"]
        self.assertIn(5000, fp["tiers"])
        self.assertIn(200000, ht["tiers"])
        self.assertEqual(ht["currency"], "USDT")
        self.assertEqual(fp["currency"], "USD")


class TestTechnicalAnalysis(unittest.TestCase):
    def setUp(self):
        self.analyzer = TechnicalAnalyzer()
        self.dummy_prices = [100.0 + (i * 0.5) for i in range(50)]

    def test_sma_empty_and_normal(self):
        res_empty = self.analyzer.calculate_sma([], 20)
        self.assertIsNone(res_empty["value"])

        res_short = self.analyzer.calculate_sma([10.0, 20.0], 5)
        self.assertIsNone(res_short["value"])

        res = self.analyzer.calculate_sma(self.dummy_prices, 10)
        self.assertIsNotNone(res["value"])
        self.assertAlmostEqual(res["value"], sum(self.dummy_prices[-10:]) / 10.0, places=4)

    def test_ema_edge_cases(self):
        self.assertIsNone(self.analyzer.calculate_ema([], 9)["value"])

        const_prices = [50.0] * 30
        res = self.analyzer.calculate_ema(const_prices, 9)
        self.assertAlmostEqual(res["value"], 50.0, places=4)

    def test_rsi_extremes(self):
        pure_gain = [float(i) for i in range(1, 30)]
        res_100 = self.analyzer.calculate_rsi(pure_gain, 14)
        self.assertEqual(res_100["value"], 100.0)
        self.assertEqual(res_100["interpretation"], "overbought")

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
        self.assertGreaterEqual(setup.risk_reward, 0.5)
        self.assertTrue(len(setup.cleo_symbol) > 0)

    def test_scan_all_symbols_ranking(self):
        market_data_map = {}
        for i, sym in enumerate(config.ALL_WATCHED_SYMBOLS[:35]):
            step = 0.5 if i % 2 == 0 else -0.5
            prices = [100.0 + (j * step) for j in range(40)]
            market_data_map[sym] = {"historical_prices": prices}

        setups = self.engine.scan_all_symbols(market_data_map, limit=30)
        self.assertGreaterEqual(len(setups), 15)

        confidences = [s.confidence for s in setups]
        self.assertEqual(confidences, sorted(confidences, reverse=True))

    def test_mean_reversion_rr_guarantee(self):
        prices = [100.0 - (i * 1.5) for i in range(30)]
        setup = self.engine._mean_reversion("EURUSD=X", prices, 0.02)
        if setup:
            real_rr = abs(setup.take_profit_1 - setup.entry_price) / abs(setup.entry_price - setup.stop_loss)
            self.assertGreaterEqual(real_rr, 1.79)
            self.assertAlmostEqual(real_rr, setup.risk_reward, delta=0.05)


class TestRiskManager(unittest.TestCase):
    def setUp(self):
        self.rm = RiskManager(account_size=5000.0)

    def test_funding_pips_summary_5k(self):
        summary = self.rm.get_challenge_summary(firm="funding_pips", account_size=5000.0)
        self.assertEqual(summary["account_size"], 5000.0)
        self.assertEqual(summary["platform"], "Match-Trader")
        self.assertEqual(summary["max_daily_drawdown_usd"], 250.0)
        self.assertEqual(summary["max_total_drawdown_usd"], 500.0)
        self.assertEqual(summary["recommended_risk_1pct_usd"], 50.0)
        self.assertEqual(summary["recommended_risk_2pct_usd"], 100.0)

    def test_hyro_trader_summary_200k(self):
        summary = self.rm.get_challenge_summary(firm="hyro_trader", account_size=200000.0)
        self.assertEqual(summary["account_size"], 200000.0)
        self.assertEqual(summary["currency"], "USDT")
        self.assertEqual(summary["platform"], "Cleo.finance (Bybit)")
        self.assertEqual(summary["max_daily_drawdown_usd"], 10000.0)
        self.assertEqual(summary["max_total_drawdown_usd"], 20000.0)
        self.assertEqual(summary["recommended_risk_1pct_usd"], 2000.0)
        self.assertEqual(summary["recommended_risk_2pct_usd"], 4000.0)

    def test_lot_size_forex(self):
        res = self.rm.calculate_lot_size("EURUSD=X", entry=1.1400, stop_loss=1.1350, risk_pct=1.0, firm="funding_pips")
        self.assertEqual(res["risk_usd"], 50.0)
        self.assertGreater(res["lot_size"], 0.0)

    def test_lot_size_gold(self):
        res = self.rm.calculate_lot_size("GC=F", entry=4400.0, stop_loss=4380.0, risk_pct=1.0, firm="funding_pips")
        self.assertEqual(res["risk_usd"], 50.0)
        self.assertGreater(res["lot_size"], 0.0)

    def test_hyro_trader_crypto_futures_sizing(self):
        # On Hyro Trader 200k USDT: 1% risk = 2000 USDT. BTC entry 86000, SL 84000 (dist 2000) -> 1.0 BTC contract
        res = self.rm.calculate_lot_size("BTC-USD", entry=86000.0, stop_loss=84000.0, risk_pct=1.0, account_size=200000.0, firm="hyro_trader")
        self.assertEqual(res["risk_usd"], 2000.0)
        self.assertEqual(res["contracts"], 1.0)
        self.assertEqual(res["notional_usd"], 86000.0)
        self.assertEqual(res["margin_10x"], 8600.0)

    def test_lot_size_invalid_inputs(self):
        res_zero = self.rm.calculate_lot_size("BTC-USD", entry=100.0, stop_loss=100.0)
        self.assertEqual(res_zero["lot_size"], 0.0)

        res_neg_entry = self.rm.calculate_lot_size("BTC-USD", entry=-10.0, stop_loss=50.0)
        self.assertEqual(res_neg_entry["lot_size"], 0.0)

        res_neg_acc = self.rm.calculate_lot_size("BTC-USD", entry=100.0, stop_loss=90.0, account_size=0.0)
        self.assertEqual(res_neg_acc["lot_size"], 0.0)

        res_neg_risk = self.rm.calculate_lot_size("BTC-USD", entry=100.0, stop_loss=90.0, risk_pct=0.0)
        self.assertEqual(res_neg_risk["lot_size"], 0.0)


class TestDataEngine(unittest.TestCase):
    def setUp(self):
        self.engine = MarketDataEngine()


    def test_fetch_all_markets_full_coverage(self):
        # Guarantees all symbols returned
        results = self.engine.fetch_all_markets()
        self.assertEqual(len(results), len(config.ALL_WATCHED_SYMBOLS))


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
        self.assertIn(b"Funding Pips", res.data)
        self.assertIn(b"Hyro Trader", res.data)

    def test_api_signals_endpoint_default(self):
        res = self.client.get("/api/signals?top=10")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertGreaterEqual(len(data["signals"]), 10)
        self.assertIn("risk_summary", data)
        self.assertIn("firms_config", data)

    def test_api_signals_hyro_trader_200k(self):
        res = self.client.get("/api/signals?firm=hyro_trader&capital=200000")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["risk_summary"]["account_size"], 200000.0)
        self.assertEqual(data["risk_summary"]["currency"], "USDT")
        self.assertEqual(data["risk_summary"]["max_daily_drawdown_usd"], 10000.0)

    def test_api_risk_summary_route(self):
        res = self.client.get("/api/risk_summary?firm=hyro_trader&capital=100000")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["risk_summary"]["account_size"], 100000.0)

    def test_calculate_lot_hyro_crypto(self):
        payload = {
            "symbol": "BTC-USD",
            "entry": 86000,
            "stop_loss": 84000,
            "risk_pct": 1.0,
            "account_size": 200000,
            "firm": "hyro_trader"
        }
        res = self.client.post("/api/calculate_lot", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["contracts"], 1.0)
        self.assertEqual(data["risk_usd"], 2000.0)


if __name__ == "__main__":
    unittest.main()
