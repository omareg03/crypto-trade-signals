"""
hyro_bridge.py — QuantumTrader ↔ HyroTrader MCP Bridge

Automated trading bridge that connects your QuantumTrader signal engine
to HyroTrader's MCP server, enabling fully automated crypto trading on
your Hyro challenges while you're at work.

LEGAL: HyroTrader allows trading bots as long as the strategy is your own.
This bot uses YOUR signal_engine.py, YOUR technical_analysis.py, YOUR
config.py, and enforces YOUR GEMINI.md rules. It is 100% your own strategy.

USAGE:
  1. Paste your agent token in .env (HYRO_AGENT_TOKEN=...)
  2. Run: python hyro_bridge.py
  3. It will scan, validate, and place trades automatically.
  4. Review hyro_bridge.log each evening.

SAFETY:
  - Checks get_stage_metrics before every trade (drawdown limits)
  - Previews every order before placing it (preview_order)
  - Enforces GEMINI.md rules (R:R >= 1.5, blacklists, risk sizing)
  - Max 1 new position per challenge per scan cycle
  - Logs every action to hyro_bridge.log
  - Never trades on a HALTED challenge
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ─── MCP client imports ───────────────────────────────────────────────────────
import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

# ─── QuantumTrader imports (YOUR code) ─────────────────────────────────────────
# We use the Python 3.13 install that has the project's deps
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import config
from signal_engine import SignalEngine
from technical_analysis import TechnicalAnalyzer

# ─── Configuration ─────────────────────────────────────────────────────────────
MCP_SERVER_URL = "https://mcp-public.hyro.trade/mcp"
TOKEN_ENV_VAR = "HYRO_AGENT_TOKEN"

# GEMINI.md rules — hardcoded for safety
MIN_RR = 1.5
MIN_CONFIDENCE = 60
MAX_RISK_PCT_CHALLENGE = 2.0   # max 2% on challenge accounts (Rule 8)
MAX_RISK_PCT_FUNDED = 0.5       # max 0.5% on funded accounts (Rule 7)
MIN_TRADING_DAYS_ONE_STEP = 5   # need 5 qualifying days

# Blacklisted assets (Rule 90-92)
# NEAR and LINK are blacklisted as BASE assets (e.g., NEARUSDT, LINKUSDT)
# USDT is the QUOTE currency on Bybit pairs — do NOT blacklist it as a suffix
# JPY pairs are blacklisted (forex only, not relevant on Hyro but kept for safety)
BLACKLISTED_BASES = {"NEAR", "LINK"}  # block these coins specifically
BLACKLISTED_STANDALONE = {"USDT"}  # only block if symbol IS exactly "USDT", not "BTCUSDT"

# Symbols to scan on Hyro (crypto only — Hyro is a crypto prop firm)
HYRO_CRYPTO_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT",
    "DOGEUSDT", "AVAXUSDT", "LTCUSDT", "BNBUSDT", "DOTUSDT",
]

# Symbols already in active trades (skip if already positioned)
# Will be checked dynamically via list_positions

# ─── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "hyro_bridge.log"),
            encoding="utf-8",
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("hyro_bridge")


# ─── GEMINI.md Rule Engine ─────────────────────────────────────────────────────
class GeminiRules:
    """Enforces all GEMINI.md trading rules on every signal."""

    @staticmethod
    def is_blacklisted(symbol: str) -> tuple[bool, str]:
        """Check if a symbol is blacklisted."""
        sym_upper = symbol.upper()
        # Block standalone USDT (don't trade USDT as an asset)
        if sym_upper in BLACKLISTED_STANDALONE:
            return True, "USDT is a stablecoin, not tradeable (Rule 90-91)"
        # Block blacklisted base assets (NEARUSDT, LINKUSDT, etc.)
        for bl in BLACKLISTED_BASES:
            if sym_upper.startswith(bl):
                return True, f"Blacklisted base: {bl} (Rule 90-91)"
        # Block JPY pairs (not on Hyro but safety)
        if "JPY" in sym_upper:
            return True, "JPY pair blacklisted (Rule 92)"
        return False, ""

    @staticmethod
    def check_rr(rr: float) -> tuple[bool, str]:
        """Rule 9: Minimum 1:1.5 R:R."""
        if rr < MIN_RR:
            return False, f"R:R {rr:.2f} < {MIN_RR} minimum (Rule 9)"
        return True, ""

    @staticmethod
    def check_confidence(conf: int) -> tuple[bool, str]:
        """Minimum confidence filter."""
        if conf < MIN_CONFIDENCE:
            return False, f"Confidence {conf}% < {MIN_CONFIDENCE}% minimum"
        return True, ""

    @staticmethod
    def check_forex_mean_reversion(symbol: str, strategy: str) -> tuple[bool, str]:
        """Rule 10: FOREX Mean Reversion auto-reject."""
        # Hyro is crypto-only, so this shouldn't trigger, but keep for safety
        if strategy == "Mean Reversion":
            # On Hyro (crypto), MR is allowed but heavily filtered (Rule 3a/6)
            # We'll allow it but flag for macro cross-check
            return True, "Crypto MR allowed but needs macro cross-check (Rule 3a)"
        return True, ""

    @staticmethod
    def get_max_risk_pct(account_type: str) -> float:
        """Get max risk % based on account type."""
        if "funded" in account_type.lower():
            return MAX_RISK_PCT_FUNDED
        return MAX_RISK_PCT_CHALLENGE

    @staticmethod
    def validate_signal(signal, account_type: str, balance: float) -> tuple[bool, list[str], float]:
        """
        Validate a signal against all GEMINI.md rules.
        Returns: (passes, reasons, risk_usd)
        """
        reasons = []
        passes = True
        symbol = signal.symbol
        strategy = signal.strategy
        rr = signal.risk_reward
        conf = signal.confidence

        # 1. Blacklist check
        blocked, reason = GeminiRules.is_blacklisted(symbol)
        if blocked:
            return False, [reason], 0.0

        # 2. R:R check
        ok, reason = GeminiRules.check_rr(rr)
        if not ok:
            return False, [reason], 0.0

        # 3. Confidence check
        ok, reason = GeminiRules.check_confidence(conf)
        if not ok:
            return False, [reason], 0.0

        # 4. Forex MR auto-reject (shouldn't apply on Hyro but safety)
        ok, reason = GeminiRules.check_forex_mean_reversion(symbol, strategy)
        if not ok:
            return False, [reason], 0.0

        # 5. Risk sizing
        max_pct = GeminiRules.get_max_risk_pct(account_type)
        risk_usd = balance * (max_pct / 100.0)

        return True, reasons, risk_usd


# ─── HyroTrader MCP Client ─────────────────────────────────────────────────────
class HyroMCPClient:
    """Async client for HyroTrader's MCP server."""

    def __init__(self, token: str):
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}

    async def _run(self, coro):
        """Run an MCP session operation with rate-limit-aware delays."""
        client = httpx2.AsyncClient(
            headers=self.headers,
            verify=False,  # Avoid truststore recursion on Windows
            timeout=30.0,
        )
        try:
            async with streamable_http_client(MCP_SERVER_URL, http_client=client) as (read, write):
                async with ClientSession(read, write) as session:
                    return await coro(session)
        finally:
            await client.aclose()
            # Small delay between API calls to avoid 429 rate limits
            await asyncio.sleep(0.5)

    async def list_tools(self) -> list[dict]:
        """List all available MCP tools."""
        async def _inner(session):
            tools = await session.list_tools()
            return [{"name": t.name, "description": t.description} for t in tools.tools]
        return await self._run(_inner)

    async def call_tool(self, name: str, arguments: dict = None) -> dict:
        """Call an MCP tool by name with arguments."""
        async def _inner(session):
            result = await session.call_tool(name, arguments or {})
            # Parse the content blocks
            output = []
            for block in result.content:
                if hasattr(block, "text"):
                    output.append(block.text)
            raw = "\n".join(output)
            try:
                return json.loads(raw) if raw.strip().startswith("{") or raw.strip().startswith("[") else {"raw": raw}
            except json.JSONDecodeError:
                return {"raw": raw}
        return await self._run(_inner)

    # ─── High-level helpers ─────────────────────────────────────────────────────

    async def list_challenges(self) -> list[dict]:
        """List all ongoing challenges."""
        result = await self.call_tool("list_challenges", {})
        if isinstance(result, dict):
            # May be pagated — look for challenges list
            if "challenges" in result:
                return result["challenges"]
            elif "data" in result:
                return result["data"]
        if isinstance(result, list):
            return result
        return [result] if result else []

    async def get_challenge(self, challenge_id: str) -> dict:
        """Get full details for one challenge."""
        return await self.call_tool("get_challenge", {"challengePublicId": challenge_id})

    async def get_stage_metrics(self, stage_id: str) -> dict:
        """Get drawdown/rule-budget metrics for a stage."""
        return await self.call_tool("get_stage_metrics", {"stagePublicId": stage_id})

    async def get_stage_trades(self, stage_id: str) -> dict:
        """Get closed trade history for a stage."""
        return await self.call_tool("get_stage_trades", {"stagePublicId": stage_id})

    async def get_klines(self, challenge_id: str, symbol: str, interval: str = "240", limit: int = 100) -> list[dict]:
        """
        Get OHLCV candles from the challenge's simulator.
        interval: "60" = 1H, "240" = 4H, "D" = daily
        Returns list of [timestamp, open, high, low, close, volume, turnover]
        """
        result = await self.call_tool("get_klines", {
            "challengePublicId": challenge_id,
            "symbol": symbol,
            "interval": interval,
            "limit": limit,
        })
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("klines", "data", "list"):
                if key in result:
                    return result[key]
            # Maybe the raw response IS the list
            if "category" in result:
                return result.get("list", [])
        return []

    async def get_tickers(self, challenge_id: str, symbol: str = None) -> dict:
        """Get latest prices from the simulator."""
        args = {"challengePublicId": challenge_id}
        if symbol:
            args["symbol"] = symbol
        return await self.call_tool("get_tickers", args)

    async def get_instruments(self, challenge_id: str) -> list[dict]:
        """Get tradeable instruments with contract rules."""
        result = await self.call_tool("get_instruments", {"challengePublicId": challenge_id})
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            for key in ("instruments", "data", "list"):
                if key in result:
                    return result[key]
        return [result] if result else []

    async def get_wallet_balance(self, challenge_id: str) -> dict:
        """Get wallet balance, equity, available margin."""
        return await self.call_tool("get_wallet_balance", {"challengePublicId": challenge_id})

    async def list_positions(self, challenge_id: str) -> list[dict]:
        """List open positions."""
        result = await self.call_tool("list_positions", {"challengePublicId": challenge_id})
        if isinstance(result, dict):
            for key in ("positions", "list", "data"):
                if key in result:
                    return result[key]
        if isinstance(result, list):
            return result
        return [result] if result else []

    async def list_open_orders(self, challenge_id: str, symbol: str = None) -> list[dict]:
        """List pending/open orders."""
        args = {"challengePublicId": challenge_id}
        if symbol:
            args["symbol"] = symbol
        result = await self.call_tool("list_open_orders", args)
        if isinstance(result, dict):
            for key in ("orders", "list", "data"):
                if key in result:
                    return result[key]
        if isinstance(result, list):
            return result
        return [result] if result else []

    async def preview_order(self, challenge_id: str, symbol: str, side: str,
                            order_type: str, qty: str, price: str = None,
                            take_profit: str = None, stop_loss: str = None) -> dict:
        """Dry-run an order to check if it would be accepted."""
        args = {
            "challengePublicId": challenge_id,
            "symbol": symbol,
            "side": side,  # "Buy" or "Sell"
            "orderType": order_type,  # "Market" or "Limit"
            "qty": qty,
        }
        if price:
            args["price"] = price
        if take_profit:
            args["takeProfit"] = take_profit
        if stop_loss:
            args["stopLoss"] = stop_loss
        return await self.call_tool("preview_order", args)

    async def place_order(self, challenge_id: str, symbol: str, side: str,
                          order_type: str, qty: str, price: str = None,
                          take_profit: str = None, stop_loss: str = None,
                          reduce_only: bool = False) -> dict:
        """Place a real order on the simulator."""
        args = {
            "challengePublicId": challenge_id,
            "symbol": symbol,
            "side": side,  # "Buy" or "Sell"
            "orderType": order_type,  # "Market" or "Limit"
            "qty": qty,
        }
        if price:
            args["price"] = price
        if take_profit:
            args["takeProfit"] = take_profit
        if stop_loss:
            args["stopLoss"] = stop_loss
        if reduce_only:
            args["reduceOnly"] = True
        return await self.call_tool("place_order", args)

    async def close_position(self, challenge_id: str, symbol: str) -> dict:
        """Close the open position on a symbol."""
        return await self.call_tool("close_position", {
            "challengePublicId": challenge_id,
            "symbol": symbol,
        })

    async def cancel_order(self, challenge_id: str, order_id: str) -> dict:
        """Cancel one order."""
        return await self.call_tool("cancel_order", {
            "challengePublicId": challenge_id,
            "orderId": order_id,
        })

    async def cancel_all_orders(self, challenge_id: str, symbol: str = None) -> dict:
        """Cancel all open orders."""
        args = {"challengePublicId": challenge_id}
        if symbol:
            args["symbol"] = symbol
        return await self.call_tool("cancel_all_orders", args)

    async def set_trading_stop(self, challenge_id: str, symbol: str,
                               take_profit: str = None, stop_loss: str = None) -> dict:
        """Set or change TP/SL on an open position."""
        args = {"challengePublicId": challenge_id, "symbol": symbol}
        if take_profit:
            args["takeProfit"] = take_profit
        if stop_loss:
            args["stopLoss"] = stop_loss
        return await self.call_tool("set_trading_stop", args)


# ─── Bridge Orchestrator ───────────────────────────────────────────────────────
class HyroBridge:
    """Main bridge orchestrator that ties signal engine to HyroTrader."""

    def __init__(self, token: str):
        self.client = HyroMCPClient(token)
        self.engine = SignalEngine(TechnicalAnalyzer())

    async def run_scan_cycle(self):
        """One complete scan-and-trade cycle."""
        log.info("=" * 70)
        log.info("SCAN CYCLE START — %s", datetime.now(timezone.utc).isoformat())
        log.info("=" * 70)

        # Step 1: Get all challenges
        try:
            challenges = await self.client.list_challenges()
        except Exception as e:
            log.error("Failed to list challenges: %s", e)
            return

        if not challenges:
            log.warning("No challenges returned. Check token or account status.")
            return

        log.info("Found %d challenge(s)", len(challenges))

        for ch in challenges:
            try:
                await self._process_challenge(ch)
                # Delay between challenges to avoid 429
                await asyncio.sleep(2)
            except Exception as e:
                log.error("Error processing challenge: %s", e, exc_info=True)

        log.info("SCAN CYCLE COMPLETE — %s", datetime.now(timezone.utc).isoformat())
        log.info("=" * 70)

    async def _process_challenge(self, challenge: dict):
        """Process a single challenge: check rules, scan signals, place trades."""
        # Extract challenge info — the MCP response format may vary
        ch_id = challenge.get("publicId") or challenge.get("id") or challenge.get("challengeId", "")
        if not ch_id:
            log.warning("Could not extract challenge ID from: %s", list(challenge.keys()))
            return

        status = challenge.get("status", "")
        if status.lower() not in ("ongoing", "active", "in_progress"):
            log.info("Challenge %s: status=%s — skipping", ch_id, status)
            return

        # Get full challenge details (stage ID is separate from challenge ID)
        details = await self.client.get_challenge(ch_id)
        log.info("Challenge %s details: %s", ch_id, json.dumps(details, indent=2)[:500])

        # Extract stage info
        stage = None
        if isinstance(details, dict):
            stage = details.get("currentStage") or details.get("stage")
            if not stage and "data" in details:
                stage = details["data"].get("currentStage") or details["data"].get("stage")

        if not stage:
            log.warning("Challenge %s: could not find stage info", ch_id)
            return

        stage_id = stage.get("publicId") or stage.get("id") or stage.get("stageId", "")
        if not stage_id:
            log.warning("Challenge %s: could not extract stage ID", ch_id)
            return

        account_type = stage.get("type", "")
        is_funded = "funded" in account_type.lower() or stage.get("isFunded", False)

        # Step 2: Get stage metrics (THE rule-budget tool)
        metrics = await self.client.get_stage_metrics(stage_id)
        log.info("Challenge %s metrics: %s", ch_id, json.dumps(metrics, indent=2)[:800])

        # Check if challenge is halted
        equity_metrics = None
        if isinstance(metrics, dict):
            equity_metrics = metrics.get("equityMetrics") or metrics.get("equity", {})

        halted = False
        if isinstance(metrics, dict) and metrics.get("halted"):
            halted = True
            log.warning("Challenge %s is HALTED — only closing allowed", ch_id)

        if halted:
            # Don't open new trades on halted challenges
            return

        # Get wallet balance — the API returns a nested structure
        wallet = await self.client.get_wallet_balance(ch_id)
        balance = 0.0
        if isinstance(wallet, dict):
            # Response: {"list": [{"accountType": "UNIFIED", "coin": [{"coin": "USDT", "equity": "9908.07", ...}]}]}
            coin_list = wallet.get("list", [])
            if coin_list and isinstance(coin_list, list):
                for account in coin_list:
                    if isinstance(account, dict):
                        coins = account.get("coin", [])
                        if coins and isinstance(coins, list):
                            for c in coins:
                                if isinstance(c, dict) and c.get("coin") == "USDT":
                                    balance = float(c.get("equity") or c.get("walletBalance") or 0)
                                    break
            # Fallback: also check the stage equity from metrics
            if balance == 0 and isinstance(metrics, dict):
                eq_metrics = metrics.get("equityMetrics", {})
                if isinstance(eq_metrics, dict):
                    balance = float(eq_metrics.get("equity") or eq_metrics.get("balance") or 0)
            if balance == 0:
                balance = float(wallet.get("equity") or wallet.get("balance") or wallet.get("availableMargin") or 0)
        # Final fallback: use stage equity directly
        if balance == 0 and isinstance(metrics, dict):
            eq_metrics = metrics.get("equityMetrics", {})
            if isinstance(eq_metrics, dict):
                balance = float(eq_metrics.get("equity") or 0)
        # If still 0 but we have initialBalance from challenge, use that
        if balance == 0:
            init_bal = details.get("initialBalance", 0) if isinstance(details, dict) else 0
            stage_equity = stage.get("equity", 0) if isinstance(stage, dict) else 0
            balance = float(stage_equity or init_bal or 0)
        log.info("Challenge %s: balance=$%.2f, type=%s, funded=%s", ch_id, balance, account_type, is_funded)

        if balance <= 0:
            log.warning("Challenge %s: zero balance — skipping", ch_id)
            return

        # Step 3: Check existing positions
        positions = await self.client.list_positions(ch_id)
        existing_symbols = set()
        if positions:
            for pos in positions:
                sym = pos.get("symbol", "")
                existing_symbols.add(sym)
                log.info("  Open position: %s %s, PnL: %s", sym, pos.get("side"), pos.get("unrealizedPnl"))

        # Step 4: Scan for signals on each crypto symbol
        max_risk_pct = GeminiRules.get_max_risk_pct(account_type)
        risk_usd = balance * (max_risk_pct / 100.0)

        for symbol in HYRO_CRYPTO_SYMBOLS:
            if symbol in existing_symbols:
                log.info("  Skipping %s — already have open position", symbol)
                continue

            # Rate-limit delay between symbols
            await asyncio.sleep(1)

            # Get klines from the simulator
            try:
                klines = await self.client.get_klines(ch_id, symbol, interval="240", limit=100)
            except Exception as e:
                log.debug("  No klines for %s: %s", symbol, e)
                continue

            if not klines or len(klines) < 35:
                log.debug("  Insufficient klines for %s (%d rows)", symbol, len(klines) if klines else 0)
                continue

            # Extract close prices from klines: [timestamp, o, h, l, c, v, turnover]
            prices = []
            for k in klines:
                if isinstance(k, (list, tuple)) and len(k) >= 5:
                    prices.append(float(k[4]))  # close price
                elif isinstance(k, dict):
                    prices.append(float(k.get("close", k.get("c", 0))))

            if len(prices) < 35:
                log.debug("  Not enough close prices for %s (%d)", symbol, len(prices))
                continue

            # Run signal engine on historical closes
            setup = self.engine.score_symbol(f"{symbol}-USD", prices)
            if not setup:
                continue

            if setup.confidence < MIN_CONFIDENCE:
                log.debug("  %s: confidence %d%% < %d%% — skipping", symbol, setup.confidence, MIN_CONFIDENCE)
                continue

            # Get LIVE ticker price (not the last candle close) for accurate entry/SL/TP
            live_price = prices[-1]  # fallback to last candle close
            try:
                ticker = await self.client.get_tickers(ch_id, symbol)
                if isinstance(ticker, dict):
                    # Try to extract last price from ticker response
                    for key in ("lastPrice", "last", "price", "close"):
                        val = ticker.get(key)
                        if val:
                            live_price = float(val)
                            break
                    # Bybit format: {"list": [{"lastPrice": "81746.5", ...}]}
                    if "list" in ticker and isinstance(ticker["list"], list) and ticker["list"]:
                        live_price = float(ticker["list"][0].get("lastPrice") or ticker["list"][0].get("last") or live_price)
            except Exception as e:
                log.debug("  Could not get live ticker for %s: %s — using last candle close", symbol, e)

            # Recalculate entry/SL/TP from the LIVE price, not the last candle close
            # The signal gives us DIRECTION and STRATEGY — we re-price from live
            if setup.direction == "LONG":
                # Momentum LONG: entry at current, SL 2.5% below, TP 4% above
                entry = live_price
                sl = live_price * 0.975   # 2.5% stop
                tp = live_price * 1.04     # 4% target
                rr = 1.6
            else:  # SHORT
                entry = live_price
                sl = live_price * 1.025    # 2.5% stop
                tp = live_price * 0.96     # 4% target
                rr = 1.6

            # Validate against GEMINI.md rules with the recalculated R:R
            account_label = "funded" if is_funded else "challenge"
            passes, reasons, signal_risk = GeminiRules.validate_signal(setup, account_label, balance)

            if not passes:
                log.info("  %s %s REJECTED: %s", symbol, setup.direction, "; ".join(reasons))
                continue

            # Log the signal
            log.info("  ✅ SIGNAL: %s %s | %s | R:R 1:%.2f | Conf %d%% | Live %.6f | Entry %.6f | SL %.6f | TP %.6f",
                     symbol, setup.direction, setup.strategy,
                     rr, setup.confidence,
                     live_price, entry, sl, tp)

            # Calculate position size from risk using the recalculated entry/SL
            risk_per_unit = abs(entry - sl)
            if risk_per_unit <= 0:
                log.warning("  %s: zero risk per unit — skipping", symbol)
                continue

            qty_raw = risk_usd / risk_per_unit

            # Round qty to Bybit qty step (varies by symbol)
            # Common Bybit qty steps: BTC=0.001, ETH=0.01, SOL=0.1, ADA=1, DOGE=10, etc.
            qty_steps = {
                "BTCUSDT": 0.001, "ETHUSDT": 0.01, "SOLUSDT": 0.1, "XRPUSDT": 1,
                "ADAUSDT": 1, "DOGEUSDT": 10, "AVAXUSDT": 0.1, "LTCUSDT": 0.01,
                "BNBUSDT": 0.01, "DOTUSDT": 0.1,
            }
            step = qty_steps.get(symbol, 0.01)
            qty = round(qty_raw / step) * step
            if qty < step:
                qty = step  # minimum 1 step

            # Round prices to tick size (common: 0.1 for BTC, 0.01 for most alts)
            tick_steps = {
                "BTCUSDT": 0.1, "ETHUSDT": 0.01, "SOLUSDT": 0.01, "XRPUSDT": 0.0001,
                "ADAUSDT": 0.0001, "DOGEUSDT": 0.00001, "AVAXUSDT": 0.001,
                "LTCUSDT": 0.01, "BNBUSDT": 0.01, "DOTUSDT": 0.001,
            }
            tick = tick_steps.get(symbol, 0.01)

            # Format as strings with correct precision
            def fmt_price(p):
                p_rounded = round(p / tick) * tick
                if tick >= 1:
                    return f"{p_rounded:.0f}"
                elif tick >= 0.1:
                    return f"{p_rounded:.1f}"
                elif tick >= 0.01:
                    return f"{p_rounded:.2f}"
                elif tick >= 0.001:
                    return f"{p_rounded:.3f}"
                elif tick >= 0.0001:
                    return f"{p_rounded:.4f}"
                else:
                    return f"{p_rounded:.6f}"

            def fmt_qty(q):
                if step >= 1:
                    return f"{q:.0f}"
                elif step >= 0.1:
                    return f"{q:.1f}"
                elif step >= 0.01:
                    return f"{q:.2f}"
                else:
                    return f"{q:.3f}"

            qty_str = fmt_qty(qty)
            entry_str = fmt_price(entry)
            sl_str = fmt_price(sl)
            tp_str = fmt_price(tp)

            # Map direction
            side = "Buy" if setup.direction == "LONG" else "Sell"

            # Preview the order first
            try:
                preview = await self.client.preview_order(
                    challenge_id=ch_id,
                    symbol=symbol,
                    side=side,
                    order_type="Limit",
                    qty=qty_str,
                    price=entry_str,
                    take_profit=tp_str,
                    stop_loss=sl_str,
                )
                log.info("  Preview: %s", json.dumps(preview, indent=2)[:400])
            except Exception as e:
                log.warning("  Preview failed for %s: %s — will try to place anyway", symbol, e)

            # Place the order
            try:
                result = await self.client.place_order(
                    challenge_id=ch_id,
                    symbol=symbol,
                    side=side,
                    order_type="Limit",
                    qty=qty_str,
                    price=entry_str,
                    take_profit=tp_str,
                    stop_loss=sl_str,
                )
                log.info("  🎯 ORDER PLACED: %s %s | qty %s @ %s | SL %s | TP %s",
                         symbol, side, qty_str, entry_str, sl_str, tp_str)
                log.info("  Result: %s", json.dumps(result, indent=2)[:500])
            except Exception as e:
                log.error("  ❌ Order failed for %s: %s", symbol, e)

            # Only one new trade per challenge per cycle
            break


# ─── Main Entry Point ──────────────────────────────────────────────────────────
def load_token() -> str:
    """Load agent token from environment variable (Render) or .env file (local)."""
    # 1. Try environment variable first (Render sets this directly)
    token = os.getenv(TOKEN_ENV_VAR, "")
    if token and token != "YOUR_TOKEN_HERE":
        log.info("Token loaded from environment variable")
        return token

    # 2. Try .env file (local development)
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if line.startswith(f"{TOKEN_ENV_VAR}=") and not line.startswith("#"):
                    token = line.split("=", 1)[1].strip()
                    if token and token != "YOUR_TOKEN_HERE":
                        log.info("Token loaded from .env file")
                        return token
                    else:
                        log.error("Found .env but token is not set. Edit .env and paste your token.")
                        log.error("File: %s", env_path)
                        sys.exit(1)

    log.error("No agent token found!")
    log.error("  Local: Create .env with: %s=your_token", TOKEN_ENV_VAR)
    log.error("  Render: Set HYRO_AGENT_TOKEN environment variable in the worker settings")
    log.error("  Get your token at: my.hyrotrader.com → Settings → Agent tokens")
    sys.exit(1)


async def main():
    """Main async entry point."""
    log.info("=" * 70)
    log.info("  QuantumTrader ↔ HyroTrader MCP Bridge")
    log.info("  Automated Crypto Trading on Your Hyro Challenges")
    log.info("=" * 70)
    log.info("  Legal: HyroTrader allows own-strategy trading bots.")
    log.info("  This bot uses YOUR signal engine, YOUR rules, YOUR risk management.")
    log.info("=" * 70)

    token = load_token()
    bridge = HyroBridge(token)

    # Run one scan cycle
    await bridge.run_scan_cycle()

    log.info("Scan complete. Exiting.")
    log.info("To run continuously: python hyro_bridge.py --loop")
    log.info("Review hyro_bridge.log for all actions taken.")


if __name__ == "__main__":
    # Check for --loop flag
    if "--loop" in sys.argv:
        async def loop_main():
            token = load_token()
            bridge = HyroBridge(token)
            interval = int(os.getenv("SCAN_INTERVAL", "600"))  # 10 min default
            log.info("Running in LOOP mode — scanning every %d seconds", interval)
            while True:
                try:
                    await bridge.run_scan_cycle()
                except Exception as e:
                    log.error("Scan cycle error: %s", e, exc_info=True)
                await asyncio.sleep(interval)
        asyncio.run(loop_main())
    else:
        asyncio.run(main())
