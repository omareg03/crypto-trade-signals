"""
app.py

Flask Web Application & API for QuantumTrader Online Multi-Asset Dashboard.
Deployable to Render.com with Gunicorn, and runnable locally on port 5000.
"""
import os
import sys
import time
import logging
import threading
from datetime import datetime
from typing import List, Dict, Any

from flask import Flask, jsonify, render_template, request

from data_engine import MarketDataEngine
from technical_analysis import TechnicalAnalyzer
from signal_engine import SignalEngine, TradeSetup
from risk_manager import RiskManager
import config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
)
logger = logging.getLogger("QuantumTraderWeb")

app = Flask(__name__, template_folder="templates", static_folder="static")

# Shared Engine Instances
data_engine = MarketDataEngine()
analyzer = TechnicalAnalyzer()
signal_engine = SignalEngine(analyzer=analyzer)
risk_manager = RiskManager()

# Thread-safe in-memory cache
state_lock = threading.Lock()
app_state: Dict[str, Any] = {
    "signals": [],
    "last_updated": None,
    "is_updating": False,
    "update_count": 0,
    "risk_summary": risk_manager.get_challenge_summary()
}


def background_data_updater():
    """
    Continuous background updater daemon.
    Refreshes all market data and computes signals every 60 seconds.
    Ensures web requests to /api/signals are served with 0ms latency.
    """
    logger.info("Background market scanner thread started.")
    interval = config.SCAN_REFRESH_INTERVAL_SECONDS

    # Initial scan on startup
    while True:
        with state_lock:
            app_state["is_updating"] = True

        try:
            logger.info("Background scanner: Fetching live market data...")
            market_data = data_engine.fetch_all_markets()
            setups = signal_engine.scan_all_symbols(market_data, limit=40)

            signals_list = [s.to_dict() for s in setups]

            with state_lock:
                app_state["signals"] = signals_list
                app_state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                app_state["update_count"] += 1
                app_state["risk_summary"] = risk_manager.get_challenge_summary()

            logger.info(f"Background scanner: Updated {len(signals_list)} setups successfully.")
        except Exception as e:
            logger.error(f"Error in background data updater: {e}", exc_info=True)
        finally:
            with state_lock:
                app_state["is_updating"] = False

        time.sleep(interval)


# Start background thread automatically
scanner_thread = threading.Thread(target=background_data_updater, daemon=True, name="MarketScannerThread")
scanner_thread.start()


@app.route("/")
def index():
    """Main dashboard HTML interface."""
    return render_template("index.html")


@app.route("/api/signals", methods=["GET"])
def get_signals():
    """
    API endpoint returning live trade signals and risk metrics.
    Supports ?top=10 or ?top=30, and ?category=crypto|forex|commodities|indices|stocks.
    """
    top_param = request.args.get("top", default="30")
    try:
        limit = int(top_param)
        if limit not in (10, 30):
            limit = 30
    except ValueError:
        limit = 30

    category_filter = request.args.get("category", default="all").lower()

    # If initial scan is in progress and cache is empty, wait up to 3 seconds
    if not app_state["signals"] and app_state["is_updating"]:
        for _ in range(15):
            time.sleep(0.2)
            if app_state["signals"]:
                break

    with state_lock:
        all_signals = list(app_state["signals"])
        last_updated = app_state["last_updated"]
        is_updating = app_state["is_updating"]
        risk_summary = app_state["risk_summary"]
        update_count = app_state["update_count"]

    # Filter by category if requested
    if category_filter and category_filter != "all":
        filtered = [s for s in all_signals if s.get("category", "").lower() == category_filter]
    else:
        filtered = all_signals

    # Apply top limit (10 or 30)
    top_signals = filtered[:limit]

    # Category statistics
    cat_counts = {
        "all": len(all_signals),
        "crypto": len([s for s in all_signals if s.get("category") == "crypto"]),
        "forex": len([s for s in all_signals if s.get("category") == "forex"]),
        "commodities": len([s for s in all_signals if s.get("category") == "commodities"]),
        "indices": len([s for s in all_signals if s.get("category") == "indices"]),
        "stocks": len([s for s in all_signals if s.get("category") == "stocks"]),
    }

    return jsonify({
        "status": "success",
        "total_signals": len(top_signals),
        "limit": limit,
        "category": category_filter,
        "last_updated": last_updated,
        "is_updating": is_updating,
        "update_count": update_count,
        "signals": top_signals,
        "risk_summary": risk_summary,
        "category_counts": cat_counts
    })


@app.route("/api/calculate_lot", methods=["POST"])
def calculate_lot():
    """Calculates position sizing and lot size for Match-Trader based on Funding Pips rules."""
    req_data = request.get_json(silent=True) or {}
    symbol = req_data.get("symbol", "BTC-USD")
    entry = float(req_data.get("entry", 0))
    stop_loss = float(req_data.get("stop_loss", 0))
    risk_pct = float(req_data.get("risk_pct", 1.0))
    account_size = float(req_data.get("account_size", config.ACCOUNT_SIZE))

    result = risk_manager.calculate_lot_size(
        symbol=symbol,
        entry=entry,
        stop_loss=stop_loss,
        risk_pct=risk_pct,
        account_size=account_size
    )
    return jsonify(result)


@app.route("/health", methods=["GET"])
def health():
    """Health check for Render.com zero-downtime monitoring."""
    return jsonify({
        "status": "healthy",
        "service": "QuantumTrader Web Scanner",
        "timestamp": datetime.now().isoformat()
    }), 200


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    logger.info("=" * 65)
    logger.info("  QUANTUM TRADER WEB DASHBOARD — STANDALONE SERVER")
    logger.info(f"  Local Access:   http://127.0.0.1:{port}")
    logger.info(f"  Network/Mobile: http://0.0.0.0:{port}")
    logger.info("=" * 65)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
