"""
app.py

Flask Web Application & API for QuantumTrader Online Multi-Asset Dashboard.
Deployable to Render.com with Gunicorn, and runnable locally on port 5000/5001.

Features:
- Instant pre-warmed cache (0ms latency, zero chance of blank signals table on startup)
- Dynamic multi-prop firm support:
  * Funding Pips (Match-Trader): $5K, $10K, $25K, $50K, $100K, $200K
  * Hyro Trader (Cleo.finance Bybit Futures): 5K, 10K, 25K, 50K, 100K, 200K USDT
- Live background market scanner with resilient error handling
- Interactive position sizing & risk management endpoints
"""
import os
import sys
import time
import json
import asyncio
import logging
import threading
from datetime import datetime
from typing import List, Dict, Any

import httpx2
from flask import Flask, jsonify, render_template, request

from data_engine import MarketDataEngine
from technical_analysis import TechnicalAnalyzer
from signal_engine import SignalEngine, TradeSetup
from risk_manager import RiskManager
import config

# MCP client for HyroTrader bot dashboard
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

MCP_SERVER_URL = "https://mcp-public.hyro.trade/mcp"

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

# Pre-warm signals immediately at startup so cache is NEVER empty on first request
logger.info("Pre-warming signal cache from market engine baseline...")
init_data = data_engine.fetch_all_markets()
init_setups = signal_engine.scan_all_symbols(init_data, limit=40)
init_signals = [s.to_dict() for s in init_setups]
logger.info(f"Pre-warmed {len(init_signals)} live signals ready for instant serving.")

# Thread-safe in-memory cache
state_lock = threading.Lock()
app_state: Dict[str, Any] = {
    "signals": init_signals,
    "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "is_updating": False,
    "update_count": 1,
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

    while True:
        with state_lock:
            app_state["is_updating"] = True

        try:
            logger.info("Background scanner: Fetching live market data...")
            market_data = data_engine.fetch_all_markets()
            setups = signal_engine.scan_all_symbols(market_data, limit=40)

            signals_list = [s.to_dict() for s in setups]

            with state_lock:
                if signals_list:
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
    Supports:
      ?top=10|30
      ?category=all|crypto|forex|commodities|indices|stocks
      ?firm=funding_pips|hyro_trader
      ?capital=5000|10000|25000|50000|100000|200000
    """
    top_param = request.args.get("top", default="30")
    try:
        limit = int(top_param)
        if limit not in (10, 30):
            limit = 30
    except ValueError:
        limit = 30

    category_filter = request.args.get("category", default="all").lower()
    firm_param = request.args.get("firm", default="funding_pips").lower()
    capital_param = request.args.get("capital")

    capital = None
    if capital_param:
        try:
            val = float(capital_param)
            if val > 0:
                capital = val
        except ValueError:
            pass

    with state_lock:
        all_signals = list(app_state["signals"])
        last_updated = app_state["last_updated"]
        is_updating = app_state["is_updating"]
        update_count = app_state["update_count"]

    # If signals is somehow empty, generate immediately from current data engine
    if not all_signals:
        mk_data = data_engine.fetch_all_markets()
        quick_setups = signal_engine.scan_all_symbols(mk_data, limit=40)
        all_signals = [s.to_dict() for s in quick_setups]
        with state_lock:
            app_state["signals"] = all_signals

    # Filter by category if requested
    if category_filter and category_filter != "all":
        filtered = [s for s in all_signals if s.get("category", "").lower() == category_filter]
    else:
        filtered = all_signals

    # Apply top limit (10 or 30)
    top_signals = filtered[:limit]

    # Category statistics across all available signals
    cat_counts = {
        "all": len(all_signals),
        "crypto": len([s for s in all_signals if s.get("category") == "crypto"]),
        "forex": len([s for s in all_signals if s.get("category") == "forex"]),
        "commodities": len([s for s in all_signals if s.get("category") == "commodities"]),
        "indices": len([s for s in all_signals if s.get("category") == "indices"]),
        "stocks": len([s for s in all_signals if s.get("category") == "stocks"]),
    }

    # Dynamic risk summary based on selected firm and capital
    risk_summary = risk_manager.get_challenge_summary(firm=firm_param, account_size=capital)

    return jsonify({
        "status": "success",
        "total_signals": len(top_signals),
        "limit": limit,
        "category": category_filter,
        "firm": firm_param,
        "capital": capital or risk_summary["account_size"],
        "last_updated": last_updated,
        "is_updating": is_updating,
        "update_count": update_count,
        "signals": top_signals,
        "risk_summary": risk_summary,
        "category_counts": cat_counts,
        "firms_config": config.PROP_FIRMS
    })


@app.route("/api/risk_summary", methods=["GET"])
def get_risk_summary():
    """Dynamic risk parameters for a specific firm and capital tier."""
    firm_param = request.args.get("firm", default="funding_pips").lower()
    capital_param = request.args.get("capital")
    capital = None
    if capital_param:
        try:
            val = float(capital_param)
            if val > 0:
                capital = val
        except ValueError:
            pass

    summary = risk_manager.get_challenge_summary(firm=firm_param, account_size=capital)
    return jsonify({
        "status": "success",
        "risk_summary": summary,
        "firms_config": config.PROP_FIRMS
    })


@app.route("/api/calculate_lot", methods=["POST"])
def calculate_lot():
    """
    Calculates position sizing for Match-Trader (Funding Pips) or
    Cleo.finance Bybit Futures (Hyro Trader).
    """
    req_data = request.get_json(silent=True) or {}
    symbol = req_data.get("symbol", "BTC-USD")
    entry = float(req_data.get("entry", 0))
    stop_loss = float(req_data.get("stop_loss", 0))
    risk_pct = float(req_data.get("risk_pct", 1.0))
    account_size = float(req_data.get("account_size", 5000.0))
    firm = req_data.get("firm", "funding_pips").lower()

    result = risk_manager.calculate_lot_size(
        symbol=symbol,
        entry=entry,
        stop_loss=stop_loss,
        risk_pct=risk_pct,
        account_size=account_size,
        firm=firm
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


# ─── Bot Dashboard Routes ──────────────────────────────────────────────────────

@app.route("/bot")
def bot_dashboard():
    """Visual dashboard for the HyroTrader automated bot performance."""
    return render_template("bot_dashboard.html")


@app.route("/bot/api")
def bot_api():
    """API endpoint that fetches live HyroTrader bot data via MCP server."""
    token = os.getenv("HYRO_AGENT_TOKEN", "")
    if not token:
        # Try .env file
        env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
        if os.path.exists(env_path):
            with open(env_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("HYRO_AGENT_TOKEN=") and not line.startswith("#"):
                        token = line.split("=", 1)[1].strip()
                        break

    if not token or token == "YOUR_TOKEN_HERE":
        return jsonify({"error": "No HYRO_AGENT_TOKEN configured", "accounts": [], "positions": [], "trades": []}), 200

    try:
        data = asyncio.run(_fetch_bot_data(token))
        return jsonify(data), 200
    except Exception as e:
        logger.error(f"Bot API error: {e}", exc_info=True)
        return jsonify({"error": str(e), "accounts": [], "positions": [], "trades": []}), 200


async def _fetch_bot_data(token: str) -> dict:
    """Fetch all bot performance data from HyroTrader MCP server."""
    headers = {"Authorization": f"Bearer {token}"}
    client = httpx2.AsyncClient(headers=headers, verify=False, timeout=30.0)

    try:
        async with streamable_http_client(MCP_SERVER_URL, http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                # 1. List all challenges
                r = await session.call_tool("list_challenges", {})
                raw = ""
                for b in r.content:
                    if hasattr(b, "text"):
                        raw = b.text
                        break
                challenges_data = json.loads(raw) if raw else []
                if isinstance(challenges_data, dict):
                    challenges_data = challenges_data.get("challenges", challenges_data.get("data", [challenges_data]))

                accounts = []
                all_positions = []
                all_trades = []

                for ch in challenges_data:
                    if not isinstance(ch, dict):
                        continue
                    status = ch.get("status", "")
                    if status.lower() not in ("active", "ongoing", "in_progress"):
                        continue

                    ch_id = ch.get("publicId", "")
                    if not ch_id:
                        continue

                    # Get challenge details for stage info
                    r2 = await session.call_tool("get_challenge", {"challengePublicId": ch_id})
                    details_raw = ""
                    for b in r2.content:
                        if hasattr(b, "text"):
                            details_raw = b.text
                            break
                    details = json.loads(details_raw) if details_raw else {}
                    if isinstance(details, dict) and "raw" in details:
                        continue  # error response

                    stage = details.get("currentStage", {}) if isinstance(details, dict) else {}
                    stage_id = stage.get("publicId", "") if isinstance(stage, dict) else ""
                    initial_balance = float(details.get("initialBalance", 0) if isinstance(details, dict) else 0)
                    is_funded = "funded" in (stage.get("type", "") if isinstance(stage, dict) else "").lower()

                    # Get stage metrics
                    metrics = {}
                    if stage_id:
                        r3 = await session.call_tool("get_stage_metrics", {"stagePublicId": stage_id})
                        for b in r3.content:
                            if hasattr(b, "text"):
                                try:
                                    metrics = json.loads(b.text)
                                except json.JSONDecodeError:
                                    pass
                                break

                    eq_metrics = metrics.get("equityMetrics", {}) if isinstance(metrics, dict) else {}
                    trade_metrics = metrics.get("tradeMetrics", {}) if isinstance(metrics, dict) else {}
                    rules = stage.get("rules", {}) if isinstance(stage, dict) else {}

                    equity = float(eq_metrics.get("equity", 0) or 0)
                    # v4.0: HyroTrader's own stage progress is the source of truth for P&L and trading days
                    # (matches the account page). tradeMetrics long+short realized is only a fallback.
                    progress = stage.get("progress", {}) if isinstance(stage, dict) else {}
                    progress = progress if isinstance(progress, dict) else {}
                    if progress.get("totalPnl") is not None:
                        realized_pnl = float(progress.get("totalPnl") or 0)
                    else:
                        realized_pnl = float(trade_metrics.get("longRealizedPnl", 0) or 0) + float(trade_metrics.get("shortRealizedPnl", 0) or 0)
                    trading_days = int(float(progress.get("tradingDays", 0) or 0))

                    # Actually currentLoss is the loss amount (positive), so PnL = -(currentLoss)
                    current_loss = float(eq_metrics.get("currentLoss", 0) or 0)
                    current_drawdown = float(eq_metrics.get("currentDrawdown", 0) or 0)

                    long_trades = int(trade_metrics.get("longTrades", 0) or 0)
                    short_trades = int(trade_metrics.get("shortTrades", 0) or 0)
                    long_wins = int(trade_metrics.get("longWinningTrades", 0) or 0)
                    short_wins = int(trade_metrics.get("shortWinningTrades", 0) or 0)
                    total_trades = long_trades + short_trades
                    winning_trades = long_wins + short_wins

                    # Calculate progress percentages
                    profit_target = float(rules.get("profitTarget", 0) or 0)
                    drawdown_limit = float(rules.get("drawdownLimit", 0) or 0)
                    equity_loss_limit = float(rules.get("equityLossLimit", 0) or 0)
                    min_days = int(rules.get("minTradingDays", 5) or 5)

                    target_pct = (realized_pnl / profit_target * 100) if profit_target > 0 else 0
                    loss_pct = (current_loss / (equity_loss_limit / 100 * initial_balance) * 100) if equity_loss_limit > 0 and initial_balance > 0 else 0

                    account = {
                        "id": ch_id,
                        "name": details.get("challengeName", ch_id) if isinstance(details, dict) else ch_id,
                        "equity": equity,
                        "initialBalance": initial_balance,
                        "isFunded": is_funded,
                        "realizedPnl": realized_pnl,
                        "totalTrades": total_trades,
                        "winningTrades": winning_trades,
                        "longTrades": long_trades,
                        "shortTrades": short_trades,
                        "drawdownPct": round((current_drawdown / drawdown_limit * 100) if drawdown_limit > 0 else 0, 1),
                        "lossPct": loss_pct,
                        "targetPct": max(0, target_pct),
                        "tradingDays": trading_days,
                        "minDays": min_days,
                        "profitTarget": profit_target,
                    }
                    accounts.append(account)

                    # Get open positions
                    r4 = await session.call_tool("list_positions", {"challengePublicId": ch_id})
                    for b in r4.content:
                        if hasattr(b, "text"):
                            try:
                                pos_data = json.loads(b.text)
                                pos_list = pos_data.get("list", pos_data.get("positions", [])) if isinstance(pos_data, dict) else []
                                for p in pos_list:
                                    if isinstance(p, dict):
                                        p["accountName"] = account["name"]
                                        all_positions.append(p)
                            except json.JSONDecodeError:
                                pass
                            break

                    # Get trade history
                    if stage_id:
                        r5 = await session.call_tool("get_stage_trades", {"stagePublicId": stage_id})
                        for b in r5.content:
                            if hasattr(b, "text"):
                                try:
                                    tr_data = json.loads(b.text)
                                    tr_list = tr_data.get("list", tr_data.get("trades", [])) if isinstance(tr_data, dict) else (tr_data if isinstance(tr_data, list) else [])
                                    for t in tr_list[:10]:
                                        if isinstance(t, dict):
                                            all_trades.append(t)
                                except json.JSONDecodeError:
                                    pass
                            break

                    await asyncio.sleep(0.5)  # rate limit

                return {
                    "accounts": accounts,
                    "positions": all_positions,
                    "trades": all_trades[:20],
                    "timestamp": datetime.now().isoformat(),
                }
    finally:
        await client.aclose()


def find_available_port(preferred_port: int) -> int:
    """Find an available port starting with preferred_port."""
    import socket
    for p in [preferred_port, 5001, 5050, 8080, 8000]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("0.0.0.0", p))
                return p
            except OSError:
                continue
    return preferred_port


if __name__ == "__main__":
    env_port = os.getenv("PORT")
    if env_port:
        port = int(env_port)
    else:
        port = find_available_port(5000)

    # Automatically open local browser if launching standalone
    import webbrowser
    def _open_browser():
        time.sleep(1.2)
        try:
            webbrowser.open(f"http://127.0.0.1:{port}")
        except Exception:
            pass
    threading.Thread(target=_open_browser, daemon=True).start()

    logger.info("=" * 65)
    logger.info("  QUANTUM TRADER WEB DASHBOARD — MULTI-FIRM INTELLIGENCE")
    logger.info(f"  Local Access:   http://127.0.0.1:{port}")
    logger.info(f"  Network/Mobile: http://0.0.0.0:{port}")
    if port != 5000:
        logger.info(f"  (Port 5000 in use by legacy process; bound to port {port})")
    logger.info("=" * 65)
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
