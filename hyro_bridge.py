"""
hyro_bridge.py — QuantumTrader v3.2 <-> HyroTrader MCP bridge.

Strategy (research-backed, see research/ + V3.2_HANDOFF.md):
  4H Donchian(20) breakout, LONG only, with trend + market filters:
    close > highest high of the prior 20 CLOSED bars
    close > EMA200 (4H)
    BTC daily close not below its SMA50 * 0.995 (market regime gate)
  Stop  = entry - 3.0 x ATR(14, Wilder)     (sized so the stop = exactly the risk budget)
  Exit  = chandelier trail: highest high since entry - 4.5 x ATR, tightened once per closed bar.
  No fixed take-profit (winners run; ~1/3 win rate, avg win ~2.3R vs avg loss ~0.8R).
Backtest Jul-2023..Oct-2026, 32 coins, fees+slippage: per-trade +0.32R in-sample, +0.21R out-of-sample.

Why v3.1 was replaced: get_klines returns rows NEWEST-FIRST and v3.1 never sorted them, so every
indicator ran on time-reversed data (signal direction matched the correct one 49.7% of the time),
and even with correct ordering that signal stack had no edge (-0.05R/trade as a portfolio).

LEGAL: HyroTrader allows bots when the strategy is your own. This is Omar E. Garcia's own system.
"""

import asyncio
import json
import logging
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, ROUND_UP

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

VERSION = "3.2.0"
MCP_SERVER_URL = "https://mcp-public.hyro.trade/mcp"
TOKEN_ENV_VAR = "HYRO_AGENT_TOKEN"
DRY_RUN = os.getenv("DRY_RUN", "0") == "1"
SCAN_INTERVAL = int(os.getenv("SCAN_INTERVAL", "600"))

# ─── Strategy parameters (fixed a-priori family, validated out-of-sample) ─────
INTERVAL = "240"                 # 4H bars
BAR_MS = 4 * 3600 * 1000
KLINE_LIMIT = 600                # EMA200 seed error < 0.3% after 600 bars (validated vs backtest)
KLINE_FALLBACK = 500             # used if the simulator 503s on the larger request
DAY_MS = 24 * 3600 * 1000
DONCHIAN_N = 20
EMA_TREND = 200
ATR_N = 14
STOP_ATR = 3.0
TRAIL_ATR = 4.5
REGIME_SMA = 50
REGIME_BAND = 0.005

# ─── Risk parameters (from the walk-forward prop-firm simulation) ─────────────
RISK_PCT_EVAL = float(os.getenv("RISK_PCT_EVAL", "0.50"))      # % of initial balance per trade
RISK_PCT_FUNDED = float(os.getenv("RISK_PCT_FUNDED", "0.50"))  # % of initial balance per trade (GEMINI rule 7)
MAX_POSITIONS = 3
MAX_PER_CLUSTER = 2
OPEN_RISK_DAILY_FRAC = 0.60      # today's DD + open risk + new risk <= 60% of the daily limit
OPEN_RISK_TOTAL_FRAC = 0.70      # total loss + open risk + new risk <= 70% of the max-loss limit
GIVEBACK_FRAC = 0.70             # all stops hit => today's DD stays <= 70% of the daily limit
BRAKE_DAILY_FRAC = 0.75          # flatten everything if today's DD reaches 75% of the daily limit
MAX_NOTIONAL_PCT = 25.0          # single-position notional cap, % of equity
MARGIN_USE_FRAC = 0.80           # funded: total initial margin <= 80% of marginLimit
CPV_USE_FRAC = 0.80              # funded: total notional <= 80% of cpvMultiplier x initial
MIN_NOTIONAL_PCT_INITIAL = 5.0   # Hyro trading-day rule: notional >= 5% of initial balance
LOSS_STREAK_N = 6
LOSS_STREAK_PAUSE_H = 24
INACTIVITY_WARN_DAYS = 25
KEEPALIVE_DAYS = 26              # Hyro closes accounts after 30 days without a CLOSED trade
KEEPALIVE_SYMBOLS = ("XRPUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT")
STALE_ENTRY_MS = 2 * BAR_MS
SCAN_BUDGET_S = 240              # max seconds of market scanning per account per cycle
CALL_TIMEOUT_S = 90              # hard timeout per MCP call

# Large-cap, liquid perpetuals only (Hyro low-cap rule: < $100M mcap capped at 5% of initial).
UNIVERSE = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT", "DOGEUSDT", "ADAUSDT", "TRXUSDT",
    "AVAXUSDT", "LTCUSDT", "BCHUSDT", "DOTUSDT", "XLMUSDT", "HBARUSDT", "SUIUSDT", "ETCUSDT",
    "AAVEUSDT", "UNIUSDT", "APTUSDT", "ARBUSDT", "OPUSDT", "FILUSDT", "ATOMUSDT", "INJUSDT",
    "TIAUSDT", "SEIUSDT", "ENAUSDT", "WLDUSDT", "1000PEPEUSDT", "WIFUSDT", "JUPUSDT",
]
BLACKLISTED_BASES = {"NEAR", "LINK"}
CORRELATION_GROUPS = {
    "BTC": {"BTCUSDT", "ORDIUSDT", "BCHUSDT"},
    "ETH": {"ETHUSDT", "ARBUSDT", "OPUSDT", "UNIUSDT", "AAVEUSDT", "ENAUSDT"},
    "SOL": {"SOLUSDT", "JUPUSDT", "WIFUSDT"},
    "MEME": {"1000PEPEUSDT", "DOGEUSDT"},
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hyro_bridge.log"),
                            encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx2").setLevel(logging.WARNING)
log = logging.getLogger("hyro_bridge")


# ═══ Pure helpers (unit-tested in test_bridge.py) ═════════════════════════════
def is_blacklisted(symbol: str) -> bool:
    s = symbol.upper()
    return s == "USDT" or "JPY" in s or any(s.startswith(b) for b in BLACKLISTED_BASES)


def correlation_group(symbol: str) -> str:
    s = symbol.upper()
    for g, members in CORRELATION_GROUPS.items():
        if s in members:
            return g
    return s


def _f(x, default=0.0) -> float:
    try:
        v = float(x)
        return v if math.isfinite(v) else default
    except (TypeError, ValueError):
        return default


def parse_klines(result) -> list:
    """Normalise get_klines output to ASCENDING [(start_ms, o, h, l, c, v)].
    The Hyro tool returns rows NEWEST-FIRST — the v3.1 root-cause bug."""
    rows = result.get("list") if isinstance(result, dict) else result
    out = []
    for r in rows or []:
        try:
            if isinstance(r, (list, tuple)) and len(r) >= 6:
                out.append((int(float(r[0])), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])))
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda k: k[0])
    dedup = []
    for k in out:
        if dedup and dedup[-1][0] == k[0]:
            dedup[-1] = k
        else:
            dedup.append(k)
    return dedup


def closed_only(bars: list, interval_ms: int, now_ms: int) -> list:
    """Drop the still-forming candle(s): keep bars whose end time has passed."""
    return [b for b in bars if b[0] + interval_ms <= now_ms]


def ema_series(values: list, n: int) -> list:
    """EMA seeded with the first value (pandas ewm adjust=False). None until n values seen."""
    out, e, a = [], None, 2.0 / (n + 1.0)
    for i, v in enumerate(values):
        e = v if e is None else (v - e) * a + e
        out.append(e if i >= n - 1 else None)
    return out


def atr_series(bars: list, n: int = ATR_N) -> list:
    """Wilder ATR (ewm alpha=1/n, seeded with the first true range). None until n bars."""
    out, a, prev_c = [], None, None
    for i, (_, _o, h, l, c, _v) in enumerate(bars):
        tr = h - l if prev_c is None else max(h - l, abs(h - prev_c), abs(l - prev_c))
        a = tr if a is None else a + (tr - a) / n
        out.append(a if i >= n - 1 else None)
        prev_c = c
    return out


def market_regime(daily_bars: list) -> str:
    """BTC regime from CLOSED daily bars (ascending): risk-on / range / risk-off."""
    closes = [b[4] for b in daily_bars]
    if len(closes) < REGIME_SMA:
        return "unknown"
    sma = sum(closes[-REGIME_SMA:]) / REGIME_SMA
    last = closes[-1]
    if last < sma * (1 - REGIME_BAND):
        return "risk-off"
    if last > sma * (1 + REGIME_BAND):
        return "risk-on"
    return "range"


def breakout_signal(bars: list):
    """Evaluate the LAST closed bar. Returns dict(score, atr, close, bar_ts) or None."""
    if len(bars) < max(EMA_TREND, DONCHIAN_N + ATR_N) + 5:
        return None
    closes = [b[4] for b in bars]
    e200 = ema_series(closes, EMA_TREND)[-1]
    atr = atr_series(bars)[-1]
    if e200 is None or atr is None or atr <= 0:
        return None
    last = bars[-1]
    prior_high = max(b[2] for b in bars[-DONCHIAN_N - 1:-1])
    close = last[4]
    if close > prior_high and close > e200:
        return {"score": (close - e200) / atr, "atr": atr, "close": close, "bar_ts": last[0]}
    return None


def chandelier_stop(bars_since_entry: list, atr: float, side: str) -> float:
    if not bars_since_entry or atr <= 0:
        return 0.0
    if side == "Buy":
        return max(b[2] for b in bars_since_entry) - TRAIL_ATR * atr
    return min(b[3] for b in bars_since_entry) + TRAIL_ATR * atr


def tighten_only(side: str, current_sl: float, candidate: float, mark: float) -> bool:
    """True if candidate is a strictly tighter, valid stop (never loosen, never cross price)."""
    if candidate <= 0:
        return False
    if side == "Buy":
        return candidate > current_sl and candidate < mark
    return (current_sl <= 0 or candidate < current_sl) and candidate > mark


def _dec(x) -> Decimal:
    return Decimal(str(x))


def round_step(value: float, step: str, mode=ROUND_DOWN) -> Decimal:
    st = _dec(step)
    return ((_dec(value) / st).to_integral_value(rounding=mode) * st).quantize(st)


def round_price(value: float, tick: str, mode=ROUND_HALF_UP) -> str:
    return format(round_step(value, tick, mode), "f")


def size_position(risk_usd: float, entry: float, stop: float, equity: float, instr: dict):
    """Risk-based qty, capped by notional, rounded DOWN to qtyStep. Returns (qty_str, notional) or (None, reason)."""
    dist = abs(entry - stop)
    if dist <= 0 or entry <= 0:
        return None, "zero stop distance"
    qty = risk_usd / dist
    cap = equity * MAX_NOTIONAL_PCT / 100.0
    if qty * entry > cap:
        qty = cap / entry
    q = round_step(qty, instr["qtyStep"], ROUND_DOWN)
    if q < _dec(instr["minOrderQty"]):
        return None, f"qty {q} < minOrderQty {instr['minOrderQty']}"
    notional = float(q) * entry
    if notional < float(instr.get("minNotionalValue", 5) or 5):
        return None, f"notional ${notional:.2f} < venue minimum"
    return format(q, "f"), notional


def risk_scale(loss_tot: float, loss_lim: float) -> float:
    """Shrink risk as total loss grows (anti-martingale), floored at 50% of base risk."""
    if loss_lim <= 0:
        return 1.0
    return max(0.5, 1.0 - max(0.0, loss_tot) / loss_lim)


def order_link_id(symbol: str, bar_ts: int) -> str:
    """Stable idempotency key per (symbol, signal bar): a retry can never double-fill."""
    base = symbol.replace("USDT", "")[:16]
    return f"qt32-{base}-{int(bar_ts) // 1000}"[:36]


def consecutive_losses(trades: list) -> tuple:
    rows = [t for t in trades if isinstance(t, dict) and not t.get("invalidated", False)]
    rows.sort(key=lambda t: str(t.get("timestamp", "")), reverse=True)
    n, last_ts = 0, None
    for t in rows:
        if _f(t.get("netPnl")) < 0:
            n += 1
            last_ts = last_ts or t.get("timestamp")
        else:
            break
    return n, last_ts


def parse_iso(ts) -> float:
    try:
        txt = re.sub(r"(\.\d{6})\d+", r"\1", str(ts)).replace("Z", "+00:00")
        return datetime.fromisoformat(txt).timestamp()
    except Exception:
        return 0.0


# ═══ MCP client ═══════════════════════════════════════════════════════════════
class MCPError(Exception):
    pass


class HyroMCP:
    """One persistent MCP session per scan cycle; retries 429/503 with back-off."""

    def __init__(self, token: str):
        self.token = token
        self._http = None
        self._cm = None
        self._scm = None
        self.session = None
        self.calls = 0

    async def __aenter__(self):
        # verify=False: httpx2's truststore hits a RecursionError on Windows (documented project
        # workaround); on Render (Linux) this is the same TLS endpoint behind a public CA.
        self._http = httpx2.AsyncClient(headers={"Authorization": f"Bearer {self.token}"},
                                        verify=False, timeout=60.0)
        self._cm = streamable_http_client(MCP_SERVER_URL, http_client=self._http)
        read, write = await self._cm.__aenter__()
        self._scm = ClientSession(read, write)
        self.session = await self._scm.__aenter__()
        await self.session.initialize()
        return self

    async def __aexit__(self, *exc):
        for cm in (self._scm, self._cm):
            try:
                if cm is not None:
                    await cm.__aexit__(None, None, None)
            except Exception:
                pass
        try:
            await self._http.aclose()
        except Exception:
            pass

    @staticmethod
    def _extract(result):
        sc = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
        if sc:
            return sc
        text = "\n".join(getattr(c, "text", "") or "" for c in (getattr(result, "content", None) or []))
        try:
            return json.loads(text)
        except Exception:
            return text

    async def call(self, name: str, args: dict, retries: int = 5):
        last = None
        for attempt in range(retries):
            self.calls += 1
            try:
                r = await asyncio.wait_for(self.session.call_tool(name, args), timeout=CALL_TIMEOUT_S)
            except Exception as e:  # transport hiccup
                last = f"transport: {e}"
                await asyncio.sleep(3 + 2 * attempt)
                continue
            d = self._extract(r)
            if isinstance(d, str):
                low = d.lower()
                if "429" in d or "rate-limit" in low:
                    m = re.search(r"retry after (\d+)s", low)
                    await asyncio.sleep((int(m.group(1)) + 2) if m else 20)
                    last = d
                    continue
                if "503" in d or "http request failed" in low:
                    await asyncio.sleep(3 + 2 * attempt)
                    last = d
                    continue
                if getattr(r, "isError", False) or getattr(r, "is_error", False) or "error" in low:
                    raise MCPError(d[:300])
            await asyncio.sleep(0.35)
            return d
        raise MCPError(f"{name} failed after {retries} tries: {str(last)[:200]}")


# ═══ Bridge ═══════════════════════════════════════════════════════════════════
class HyroBridge:
    def __init__(self, token: str):
        self.token = token
        self.instruments = {}      # symbol -> {tickSize, qtyStep, minOrderQty, minNotionalValue}
        self.cache = {}            # (symbol, interval) -> ascending bars (shared by all accounts)
        self.fetched_at = {}       # (symbol, interval) -> unix time of last refresh
        self.scanned = {}          # (challenge, bar_ts) -> symbols already evaluated for that bar

    # ── data ──────────────────────────────────────────────────────────────
    async def _klines(self, mcp, ch, symbol, interval, limit):
        raw = await mcp.call("get_klines", {"challengePublicId": ch, "symbol": symbol,
                                            "interval": interval, "limit": limit}, retries=3)
        rows = parse_klines(raw)
        if not rows:
            raise MCPError(f"empty klines for {symbol}")
        return rows

    async def bars(self, mcp, ch, symbol, interval=INTERVAL, limit=KLINE_LIMIT):
        """Closed bars (ascending). Full history is downloaded once, then only the newest bars."""
        key, ms = (symbol, interval), (BAR_MS if interval == INTERVAL else DAY_MS)
        have = self.cache.get(key)
        if not have or time.time() - self.fetched_at.get(key, 0) > 45:
            if have and len(have) >= min(limit, KLINE_FALLBACK):
                new = await self._klines(mcp, ch, symbol, interval, 10)
                if new[0][0] - have[-1][0] > ms:      # gap (outage) -> rebuild from scratch
                    have = None
                else:
                    have = [b for b in have if b[0] < new[0][0]] + new
            if not have:
                try:
                    have = await self._klines(mcp, ch, symbol, interval, limit)
                except MCPError:
                    if limit <= KLINE_FALLBACK:
                        raise
                    have = await self._klines(mcp, ch, symbol, interval, KLINE_FALLBACK)
            self.cache[key] = have[-max(limit, KLINE_LIMIT):]
            self.fetched_at[key] = time.time()
        return closed_only(self.cache[key], ms, int(time.time() * 1000))[-limit:]

    async def instrument(self, mcp, ch, symbol):
        if symbol in self.instruments:
            return self.instruments[symbol]
        d = await mcp.call("get_instruments", {"challengePublicId": ch, "symbol": symbol})
        rows = d.get("list") if isinstance(d, dict) else None
        if not rows:
            raise MCPError(f"no instrument spec for {symbol}")
        it = rows[0]
        if it.get("status") != "Trading":
            raise MCPError(f"{symbol} status {it.get('status')}")
        spec = {"tickSize": it["priceFilter"]["tickSize"], "qtyStep": it["lotSizeFilter"]["qtyStep"],
                "minOrderQty": it["lotSizeFilter"]["minOrderQty"],
                "minNotionalValue": it["lotSizeFilter"].get("minNotionalValue", "5")}
        self.instruments[symbol] = spec
        return spec

    # ── cycle ─────────────────────────────────────────────────────────────
    async def run_cycle(self):
        log.info("=" * 70)
        log.info("SCAN CYCLE START v%s %s%s", VERSION, datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 " [DRY RUN]" if DRY_RUN else "")
        async with HyroMCP(self.token) as mcp:
            data = await mcp.call("list_challenges", {})
            chs = data.get("data", data) if isinstance(data, dict) else data
            frozen = {x.strip() for x in os.getenv("FROZEN_ACCOUNTS", "").split(",") if x.strip()}
            active = []
            for ch in chs or []:
                if not isinstance(ch, dict) or str(ch.get("status", "")).lower() != "active":
                    continue
                cid = ch.get("publicId")
                if cid in frozen:
                    log.info("[%s] FROZEN (payout in progress) — skipped", cid)
                    continue
                active.append(cid)
            # pass 1 protects every account (stops, brake, housekeeping) before any slow market scan
            for scan in (False, True):
                for cid in active:
                    try:
                        await self.process(mcp, cid, scan=scan)
                    except MCPError as e:
                        log.warning("[%s] %s pass skipped (fail-safe): %s", cid, "scan" if scan else "manage", e)
                    except Exception as e:
                        log.error("[%s] unexpected error: %s", cid, e, exc_info=True)
            log.info("SCAN CYCLE END — %d MCP calls", mcp.calls)

    async def process(self, mcp, ch, scan=True):
        det = await mcp.call("get_challenge", {"challengePublicId": ch})
        stage = det.get("currentStage") or {}
        stage_id = stage.get("publicId")
        if not stage_id or str(stage.get("status", "")).lower() != "active":
            log.info("[%s] stage not active — skipped", ch)
            return
        funded = str(stage.get("type", "")).lower() == "funded"
        init = _f(det.get("initialBalance"))
        rules = stage.get("rules") or {}
        daily_lim = _f(rules.get("drawdownLimit"), 0.04 * init)
        loss_lim = _f(rules.get("equityLossLimit"), 0.06 * init)
        sheet = {r.get("key"): r.get("value") for r in stage.get("ruleSheet") or [] if isinstance(r, dict)}
        margin_lim = init * _f(sheet.get("marginLimit"), 0) / 100.0
        cpv_lim = init * _f(sheet.get("cpvMultiplier"), 0)
        progress = stage.get("progress") or {}

        met = await mcp.call("get_stage_metrics", {"stagePublicId": stage_id})
        em = met.get("equityMetrics") if isinstance(met, dict) else None
        if not isinstance(em, dict):
            raise MCPError("no equityMetrics")
        equity, balance = _f(em.get("equity")), _f(em.get("balance"))
        dd_today, loss_tot = _f(em.get("currentDrawdown")), _f(em.get("currentLoss"))
        cushion = equity - _f(em.get("drawdownPivot"), equity + dd_today)   # vs 00:00 UTC equity
        pos_meta = {p.get("symbol"): p for p in (met.get("positions") or []) if isinstance(p, dict)}

        pr = await mcp.call("list_positions", {"challengePublicId": ch})
        positions = [p for p in (pr.get("list", []) if isinstance(pr, dict) else []) if _f(p.get("size")) > 0]
        tag = "FUNDED" if funded else "EVAL"
        log.info("[%s %s] equity $%.2f | DD today $%.2f/$%.2f | loss $%.2f/$%.2f | positions %d | days %s",
                 tag, ch[:8], equity, dd_today, daily_lim, loss_tot, loss_lim, len(positions),
                 progress.get("tradingDays"))

        # 1) emergency brake — daily drawdown close to the limit
        if positions and dd_today >= BRAKE_DAILY_FRAC * daily_lim:
            log.warning("[%s] BRAKE: DD $%.2f >= %.0f%% of daily limit — flattening", ch[:8], dd_today,
                        BRAKE_DAILY_FRAC * 100)
            for p in positions:
                try:
                    if not DRY_RUN:
                        await mcp.call("close_position", {"challengePublicId": ch, "symbol": p["symbol"]})
                    log.warning("  closed %s%s", p["symbol"], " (dry run)" if DRY_RUN else "")
                except MCPError as e:
                    log.error("  BRAKE could not close %s: %s", p["symbol"], str(e)[:160])
            return

        # 2) manage open positions (initial stop if missing, chandelier trail on closed bars)
        open_risk, infos = 0.0, []
        for p in positions:
            gb, info = await self.manage(mcp, ch, p, pos_meta.get(p["symbol"]))
            open_risk += gb
            if info:
                infos.append(info)
        open_risk = await self.cap_giveback(mcp, ch, infos, open_risk, daily_lim, cushion)
        margin_used = sum(_f(p.get("positionIM")) for p in positions)
        cpv_used = sum(_f(p.get("positionValue")) for p in positions)

        # 3) stale entry limits (non reduce-only) — cancel with symbol (required by the tool)
        await self.cancel_stale(mcp, ch)

        # 4) gates for new entries
        trades = await mcp.call("get_stage_trades", {"stagePublicId": stage_id, "pageSize": 50})
        rows = trades.get("data", []) if isinstance(trades, dict) else []
        last_close = max((parse_iso(t.get("timestamp")) for t in rows if isinstance(t, dict)), default=0)
        if last_close and (time.time() - last_close) / 86400 > INACTIVITY_WARN_DAYS:
            log.warning("[%s] INACTIVITY: last closed trade %.0f days ago (account closes at 30)", ch[:8],
                        (time.time() - last_close) / 86400)
        ref_ts = last_close or parse_iso(met.get("startedAt"))
        if not scan and ref_ts and (time.time() - ref_ts) / 86400 >= KEEPALIVE_DAYS:
            try:
                await self.keepalive(mcp, ch, {p["symbol"] for p in positions}, init, funded, margin_lim, margin_used)
            except MCPError as e:
                log.warning("[%s] keep-alive failed: %s", ch[:8], e)
        if not scan:
            return
        n_loss, last_loss_ts = consecutive_losses(rows)
        if n_loss >= LOSS_STREAK_N and (time.time() - parse_iso(last_loss_ts)) < LOSS_STREAK_PAUSE_H * 3600:
            log.warning("[%s] %d consecutive losses — new entries paused %dh", ch[:8], n_loss, LOSS_STREAK_PAUSE_H)
            return
        if funded and balance - init >= 0.05 * init:
            log.warning("[%s] PAYOUT READY: profit $%.2f >= 5%% cap — no new entries until payout", ch[:8],
                        balance - init)
            return
        if len(positions) >= MAX_POSITIONS:
            return

        btc_daily = await self.bars(mcp, ch, "BTCUSDT", interval="D", limit=80)
        regime = market_regime(btc_daily)
        if regime in ("risk-off", "unknown"):
            log.info("[%s] BTC regime %s — no new longs", ch[:8], regime)
            return
        btc4 = await self.bars(mcp, ch, "BTCUSDT")
        if not btc4:
            raise MCPError("no closed BTC 4H bar")
        bar_ts = btc4[-1][0]
        for k in [k for k in self.scanned if k[0] == ch and k[1] != bar_ts]:
            del self.scanned[k]
        done = self.scanned.setdefault((ch, bar_ts), set())
        risk_pct = RISK_PCT_FUNDED if funded else RISK_PCT_EVAL
        risk_usd = init * risk_pct / 100.0 * risk_scale(loss_tot, loss_lim)

        held = {p["symbol"] for p in positions}
        clusters = {}
        for p in positions:
            clusters[correlation_group(p["symbol"])] = clusters.get(correlation_group(p["symbol"]), 0) + 1
        cands = []
        todo = [s for s in UNIVERSE if s not in held and s not in done and not is_blacklisted(s)]
        if not todo:
            return  # every symbol already evaluated for this closed bar
        t_scan0 = time.time()
        for sym in todo:
            if time.time() - t_scan0 > SCAN_BUDGET_S:
                log.info("  scan time budget reached — remaining symbols next cycle")
                break
            try:
                b = await self.bars(mcp, ch, sym)
            except MCPError as e:
                log.info("  %s: no data this cycle (%s) — retry next cycle", sym, str(e)[:80])
                continue
            if not b or b[-1][0] != bar_ts:
                continue  # feed lagging; retry next cycle
            done.add(sym)
            sig = breakout_signal(b)
            if sig:
                cands.append((sig["score"], sym, sig))
        cands.sort(reverse=True)
        log.info("[%s] regime %s | bar %s | scanned %d/%d | breakouts: %s", ch[:8], regime,
                 datetime.fromtimestamp(bar_ts / 1000, timezone.utc).strftime("%m-%d %H:%M"), len(done),
                 len([s for s in UNIVERSE if not is_blacklisted(s)]),
                 ", ".join(f"{s}({sc:.1f})" for sc, s, _ in cands[:6]) or "none")

        n_open = len(positions)
        for _sc, sym, sig in cands:
            if n_open >= MAX_POSITIONS:
                break
            grp = correlation_group(sym)
            if clusters.get(grp, 0) >= MAX_PER_CLUSTER:
                continue
            if open_risk + risk_usd - cushion > OPEN_RISK_DAILY_FRAC * daily_lim:
                log.info("  budget: daily DD + open risk would exceed %.0f%% of limit — stop", OPEN_RISK_DAILY_FRAC * 100)
                break
            if open_risk + risk_usd - (equity - init) > OPEN_RISK_TOTAL_FRAC * loss_lim:
                log.info("  budget: total loss + open risk would exceed %.0f%% of limit — stop", OPEN_RISK_TOTAL_FRAC * 100)
                break
            try:
                placed = await self.enter(mcp, ch, sym, sig, risk_usd, equity, init, funded,
                                          margin_lim, cpv_lim, margin_used, cpv_used)
            except MCPError as e:
                log.warning("  %s: entry rejected (%s)", sym, str(e)[:200])
                continue
            if placed:
                n_open += 1
                open_risk += risk_usd
                clusters[grp] = clusters.get(grp, 0) + 1
                margin_used += placed[0]
                cpv_used += placed[1]

    async def manage(self, mcp, ch, p, meta):
        """Trail/repair the stop. Returns (give_back_usd, info) where give_back = (mark - stop) x size."""
        sym, side = p["symbol"], p.get("side")
        size, entry, mark = _f(p.get("size")), _f(p.get("avgPrice")), _f(p.get("markPrice"))
        sl = _f(p.get("stopLoss"))
        sign = 1 if side == "Buy" else -1
        try:
            inst = await self.instrument(mcp, ch, sym)
            bars = await self.bars(mcp, ch, sym)
        except MCPError as e:
            log.warning("  %s: cannot manage this cycle (%s)", sym, e)
            return (max(0.0, (mark - sl) * sign * size) if sl > 0 else 0.10 * mark * size), None
        atr = (atr_series(bars)[-1] if len(bars) > ATR_N else None) or 0.0
        new_sl = None
        if sl <= 0 and atr > 0:  # never leave a position naked
            new_sl = entry - sign * STOP_ATR * atr
            if (side == "Buy" and new_sl >= mark) or (side == "Sell" and new_sl <= mark):
                new_sl = mark - sign * 1.0 * atr
            why = "initial stop (was missing)"
        else:
            created = parse_iso((meta or {}).get("createdTime")) * 1000 if meta else 0
            since = [b for b in bars if b[0] + BAR_MS > created] if created else []
            cand = chandelier_stop(since, atr, side) if since else 0.0
            if tighten_only(side, sl, cand, mark):
                new_sl, why = cand, f"chandelier {TRAIL_ATR}xATR"
        if new_sl:
            mode = ROUND_DOWN if side == "Buy" else ROUND_UP
            sl_str = round_price(new_sl, inst["tickSize"], mode)
            if DRY_RUN:
                log.info("  [DRY] %s %s: would move SL %s -> %s (%s)", sym, side, p.get("stopLoss"), sl_str, why)
            else:
                try:
                    await mcp.call("set_trading_stop", {"challengePublicId": ch, "symbol": sym, "stopLoss": sl_str})
                    log.info("  TRAIL %s %s: SL %s -> %s (%s)", sym, side, p.get("stopLoss"), sl_str, why)
                    sl = float(sl_str)
                except MCPError as e:
                    log.warning("  %s: stop update rejected (%s)", sym, str(e)[:160])
        pnl = _f(p.get("unrealisedPnl"))
        log.info("  POS %s %s size %s entry %s mark %s SL %s uPnL $%.2f", sym, side, p.get("size"),
                 p.get("avgPrice"), p.get("markPrice"), sl, pnl)
        gb = max(0.0, (mark - sl) * sign * size) if sl > 0 else 0.10 * mark * size
        return gb, {"sym": sym, "side": side, "sign": sign, "size": size, "mark": mark, "sl": sl,
                    "tick": inst["tickSize"]}

    async def keepalive(self, mcp, ch, held, init, funded, margin_lim, margin_used):
        """Tiny open+close round trip so a quiet (risk-off) market never trips the 30-day inactivity close."""
        sym = next((s for s in KEEPALIVE_SYMBOLS if s not in held), None)
        if not sym:
            return
        inst = await self.instrument(mcp, ch, sym)
        tk = await mcp.call("get_tickers", {"challengePublicId": ch, "symbol": sym})
        px = _f(((tk.get("list") or [{}])[0] if isinstance(tk, dict) else {}).get("lastPrice"))
        if px <= 0:
            return
        notional = 0.052 * init
        if funded and margin_lim > 0:
            notional = min(notional, MARGIN_USE_FRAC * margin_lim - margin_used)
        notional = max(notional, float(inst.get("minNotionalValue", 5) or 5) * 1.3)
        need = max(float(inst["minOrderQty"]), notional / px)
        qty = format(round_step(need, inst["qtyStep"], ROUND_UP), "f")
        log.warning("[%s] KEEP-ALIVE: no closed trade for %d+ days — %s round trip qty %s (~$%.2f)%s",
                    ch[:8], KEEPALIVE_DAYS, sym, qty, float(qty) * px, " [DRY RUN]" if DRY_RUN else "")
        if DRY_RUN:
            return
        day = datetime.now(timezone.utc).strftime("%Y%m%d")
        await mcp.call("place_order", {"challengePublicId": ch, "symbol": sym, "side": "Buy", "orderType": "Market",
                                       "qty": qty, "orderLinkId": f"qt32-ka-{sym[:6]}-{day}"})
        await asyncio.sleep(3)
        await mcp.call("close_position", {"challengePublicId": ch, "symbol": sym})

    async def cap_giveback(self, mcp, ch, infos, total, daily_lim, cushion):
        """Hyro daily DD is measured from 00:00 UTC equity INCLUDING open profit, so giving back open
        profit is drawdown (how the 10K died on Oct 12 while in profit). If all stops hitting would
        exceed GIVEBACK_FRAC of the daily limit, tighten every stop proportionally (never loosen)."""
        allowed = GIVEBACK_FRAC * daily_lim + cushion
        if total <= allowed or total <= 0 or allowed <= 0 or not infos:
            return total
        scale = allowed / total
        log.warning("[%s] GIVE-BACK SHIELD: stops allow $%.2f > $%.2f — tightening x%.2f", ch[:8], total, allowed, scale)
        new_total = total
        for i in infos:
            gb = max(0.0, (i["mark"] - i["sl"]) * i["sign"] * i["size"])
            if gb <= 0 or i["size"] <= 0:
                continue
            cand = i["mark"] - i["sign"] * gb * scale / i["size"]
            px = round_price(cand, i["tick"], ROUND_UP if i["sign"] > 0 else ROUND_DOWN)
            if not tighten_only(i["side"], i["sl"], float(px), i["mark"]):
                continue
            if DRY_RUN:
                log.info("  [DRY] %s: would tighten SL %s -> %s (give-back shield)", i["sym"], i["sl"], px)
            else:
                try:
                    await mcp.call("set_trading_stop", {"challengePublicId": ch, "symbol": i["sym"], "stopLoss": px})
                    log.info("  SHIELD %s: SL %s -> %s", i["sym"], i["sl"], px)
                except MCPError as e:
                    log.warning("  %s: shield stop rejected (%s)", i["sym"], str(e)[:160])
                    continue
            new_total -= gb - max(0.0, (i["mark"] - float(px)) * i["sign"] * i["size"])
        return new_total

    async def cancel_stale(self, mcp, ch):
        d = await mcp.call("list_open_orders", {"challengePublicId": ch, "limit": 50})
        now = time.time() * 1000
        for o in (d.get("list", []) if isinstance(d, dict) else []):
            if o.get("reduceOnly") or str(o.get("orderType")) != "Limit" or o.get("stopOrderType"):
                continue
            if now - _f(o.get("createdTime"), now) < STALE_ENTRY_MS:
                continue
            if DRY_RUN:
                log.info("  [DRY] would cancel stale %s limit %s", o.get("symbol"), o.get("orderId"))
                continue
            try:
                await mcp.call("cancel_order", {"challengePublicId": ch, "symbol": o.get("symbol"),
                                                "orderId": o.get("orderId")})
                log.info("  cancelled stale %s entry limit %s", o.get("symbol"), o.get("orderId"))
            except MCPError as e:
                log.warning("  could not cancel %s: %s", o.get("orderId"), str(e)[:160])

    async def enter(self, mcp, ch, sym, sig, risk_usd, equity, init, funded,
                    margin_lim, cpv_lim, margin_used, cpv_used):
        inst = await self.instrument(mcp, ch, sym)
        tk = await mcp.call("get_tickers", {"challengePublicId": ch, "symbol": sym})
        row = (tk.get("list") or [{}])[0] if isinstance(tk, dict) else {}
        last = _f(row.get("lastPrice")) or sig["close"]
        if abs(last / sig["close"] - 1) > 0.5 * STOP_ATR * sig["atr"] / sig["close"]:
            log.info("  %s: price ran %.2f%% from the signal close — skip (chasing)", sym, 100 * (last / sig["close"] - 1))
            return None
        stop = last - STOP_ATR * sig["atr"]
        qty, notional = size_position(risk_usd, last, stop, equity, inst)
        if qty is None:
            log.info("  %s: size rejected (%s)", sym, notional)
            return None
        if notional < MIN_NOTIONAL_PCT_INITIAL / 100.0 * init:
            log.info("  %s: notional $%.0f < 5%% of initial (would not count as a trading day) — still OK", sym, notional)
        sl_str = round_price(stop, inst["tickSize"], ROUND_DOWN)
        args = {"challengePublicId": ch, "symbol": sym, "side": "Buy", "orderType": "Market",
                "qty": qty, "stopLoss": sl_str, "orderLinkId": order_link_id(sym, sig["bar_ts"])}
        pv = await mcp.call("preview_order", {k: v for k, v in args.items() if k != "orderLinkId"})
        im = _f(pv.get("estimatedInitialMargin"), notional) if isinstance(pv, dict) else notional
        if funded:
            if margin_lim > 0 and margin_used + im > MARGIN_USE_FRAC * margin_lim:
                log.warning("  %s: MARGIN GUARD %.0f + %.0f > %.0f%% of $%.0f — skip", sym, margin_used, im,
                            MARGIN_USE_FRAC * 100, margin_lim)
                return None
            if cpv_lim > 0 and cpv_used + notional > CPV_USE_FRAC * cpv_lim:
                log.warning("  %s: CPV GUARD — skip", sym)
                return None
        log.info("  >>> ENTRY %s LONG qty %s ~$%.0f notional @ ~%s | SL %s (%.1fxATR) | risk $%.2f | score %.1f%s",
                 sym, qty, notional, last, sl_str, STOP_ATR, risk_usd, sig["score"], " [DRY RUN]" if DRY_RUN else "")
        if DRY_RUN:
            return (im, notional)
        res = await mcp.call("place_order", args)
        log.info("  order result: %s", json.dumps(res, default=str)[:300])
        return (im, notional)


# ═══ entry point ══════════════════════════════════════════════════════════════
def load_token() -> str:
    tok = os.getenv(TOKEN_ENV_VAR, "").strip()
    if tok:
        return tok
    env = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env):
        for line in open(env, encoding="utf-8"):
            if line.startswith(TOKEN_ENV_VAR + "="):
                tok = line.split("=", 1)[1].strip().strip('"').strip("'")
                if tok:
                    return tok
    log.error("No %s found (env var on Render, .env locally)", TOKEN_ENV_VAR)
    sys.exit(1)


async def main(loop: bool):
    log.info("QuantumTrader <-> HyroTrader bridge v%s | 4H Donchian(%d) breakout, long-only | risk eval %.2f%% "
             "funded %.2f%% | DRY_RUN=%s", VERSION, DONCHIAN_N, RISK_PCT_EVAL, RISK_PCT_FUNDED, DRY_RUN)
    bridge = HyroBridge(load_token())
    while True:
        try:
            await bridge.run_cycle()
        except Exception as e:
            log.error("cycle error: %s", e, exc_info=True)
        if not loop:
            return
        await asyncio.sleep(SCAN_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main("--loop" in sys.argv))
