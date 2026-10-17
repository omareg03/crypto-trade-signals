"""
hyro_bridge.py — QuantumTrader v3.3 <-> HyroTrader MCP bridge.

v3.3 (Oct 17 2026) = the validated v3.2 strategy + v4.0 safety plumbing. Chosen by backtest
(research/bt_v40_compare.py, research/v33_decision_run1.txt, 34 coins, Jul-2023..Oct-2026, 1 eval slot):
  v4.0 (score>=70, 2.2xATR stop, 2R TP)   +0.04R/trade ALL, -0.01R IS  -> rejected
  v3.2.3 (3xATR stop, 4.5xATR trail)      +0.66R ALL, +0.52R IS, +0.86R OOS, 0.6 trades/wk
  v3.3  (= v3.2.3 + hard 10R TP)          +0.54R ALL, +0.41R IS, +0.71R OOS, 0.6 trades/wk
  Entry: close > Donchian(20) high, close > EMA200, BTC regime not risk-off. Stop 3xATR, chandelier
  4.5xATR, hard TP at 10R on EVERY order + TP repair on any open position missing one.
  Kept from v4.0: no ticker blacklist, ranked cross-account routing with de-dup (positions + pending
  orders), passed-account hard lock, 5-pillar score logged for information only.
  Off (untested): breakeven ratchet, stagnation swap, fixed 2R TP.

Section below describes the v4.0 engine that is kept in the code for reference/logging.

v4.0 Smart Analytics Engine (LONG only, 0-100 score, trade only if score >= 70):
  P1 MACD(12,26,9) histogram expansion   0-25  (gate: hist > 0 and rising 3 bars; slope / ATR)
  P2 Candle anatomy / impulse            0-20  (body >= 60% of range, upper wick <= 20%)
  P3 Trend + breakout structure          0-20  (gate: close > Donchian(20) high and > EMA200;
                                                 + EMA20>EMA50>EMA200 stack, + ADX(14) >= 22)
  P4 Relative volume (RVOL vs SMA20)     0-20  (gate: RVOL >= 1.25; max at 2.5)
  P5 ATR% efficiency                     0-15  (max at ATR/close >= 1.2%, +3 if ATR expanding)
  1H confirmation: a negative 1H MACD histogram costs 10 points.
  Every entry carries a hard SL (2.2 x ATR) AND a hard TP (4.4 x ATR = 2R; 5.5 x ATR = 2.5R when
  score >= 85). Missing TPs on open positions are repaired every cycle (TP = entry + 2 x |entry - SL|).
  Breakeven at +1R, then a 2.2 x ATR chandelier trail. Stagnant trades (>= 4 closed 4H bars,
  within +-0.25R) are swapped out when an unheld coin scores >= 82.
  No static ticker blacklist. One coin per account, never the same coin in two accounts.

  NOTE: the v4.0 scoring/exit stack has NOT been backtested. The v3.2 research below validated the
  plain Donchian(20) + 3xATR stop + 4.5xATR trail (no fixed TP), not this configuration.

v3.2 research baseline (see research/ + V3.2_HANDOFF.md):
  4H Donchian(20) breakout, LONG only, close > EMA200, BTC daily >= SMA50 * 0.995 (regime gate, kept).
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

VERSION = "3.3.0"
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
STOP_ATR = 3.0                   # v3.3: validated v3.2 stop
TRAIL_ATR = 4.5                  # v3.3: validated chandelier trail (from entry, tighten-only)
TP_R = 10.0                      # v3.3: hard far take-profit = 10R (backtest: keeps the tail, 1-slot +0.54R)
TP_ATR = TP_R * STOP_ATR         # 30 x ATR — ATR fallback for TP repair
TP_ATR_HIGH = TP_ATR
TP_HIGH_SCORE = 1e9
TP_REPAIR_R = TP_R               # repaired TP = entry + 10 x |entry - stop|
BREAKEVEN_R = 0.0                # v3.3: no breakeven ratchet (untested, cuts the tail)
STAGNATION_SWAP = False          # v3.3: off (untested)
REGIME_SMA = 50
REGIME_BAND = 0.005

# ─── v4.0 Smart Analytics Engine ─────────────────────────────────────────────
INTERVAL_1H = "60"
H1_MS = 3600 * 1000
H1_LIMIT = 200
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
ADX_N = 14
ADX_MIN = 22.0
RVOL_N = 20
RVOL_MIN = 1.25
RVOL_MAX = 2.5
ATR_PCT_TARGET = 0.012
SMART_MIN_SCORE = 70.0
SWAP_MIN_SCORE = 82.0
STAGNANT_BARS = 4
STAGNANT_R = 0.25
H1_PENALTY = 10.0

# ─── Risk parameters (from the walk-forward prop-firm simulation) ─────────────
RISK_PCT_EVAL = float(os.getenv("RISK_PCT_EVAL", "0.40"))      # % of initial balance per trade (surviving eval: max 1 pos)
RISK_PCT_FUNDED = float(os.getenv("RISK_PCT_FUNDED", "0.50"))  # % of initial balance per trade (GEMINI rule 7)
MAX_POSITIONS = 3
MAX_POSITIONS_EVAL = 1          # surviving eval account: hard cap of 1 open position
MAX_PER_CLUSTER = 2
OPEN_RISK_DAILY_FRAC = 0.60      # today's DD + open risk + new risk <= 60% of the daily limit
OPEN_RISK_TOTAL_FRAC = 0.70      # total loss + open risk + new risk <= 70% of the max-loss limit
GIVEBACK_FRAC = 0.70             # all stops hit => today's DD stays <= 70% of the daily limit
BRAKE_DAILY_FRAC = 0.75          # flatten everything if today's DD reaches 75% of the daily limit
MAX_NOTIONAL_PCT = 25.0          # single-position notional cap, % of equity
MARGIN_ENTRY_FRAC = 0.16         # funded: entry gate — total effective margin <= 16% of initial balance
MARGIN_TRIM_FRAC = 0.18          # funded: force-trim — total effective margin > 18% of initial balance
MARGIN_TRIM_TARGET_FRAC = 0.15   # funded: trim target — bring margin back under 15% of initial balance
CPV_USE_FRAC = 0.80              # funded: total notional <= 80% of cpvMultiplier x initial
GIVEBACK_KILL_FRAC = 0.02        # flatten all + pause until next day if intraday give-back >= 2% of initial
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
    # v4.0: previously blacklisted names are eligible again — the score decides, not the ticker.
    "LINKUSDT", "NEARUSDT",
]
BLACKLISTED_SYMBOLS = set()      # v4.0: no static ticker blacklist
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
    """Only structurally invalid symbols are excluded (bare USDT, non-crypto JPY pairs).
    v4.0: no coin is ever blocked by its ticker name (BLACKLISTED_SYMBOLS is empty)."""
    s = symbol.upper()
    return s == "USDT" or "JPY" in s or s in BLACKLISTED_SYMBOLS


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


def _effective_margin(p) -> float:
    """Effective initial margin for one position. Never trust `positionIM` alone — Bybit/Match-Trader
    can return '' or '0' or omit it. Floor it at notional / leverage (== notional at 1x, which this
    account trades at)."""
    im = _f(p.get("positionIM"))
    notional = _f(p.get("size")) * (_f(p.get("markPrice")) or _f(p.get("avgPrice")))
    lev = max(1.0, _f(p.get("leverage"), 1.0))
    return max(im, notional / lev)


def _dedup_todo(todo: list, held, global_held) -> list:
    """Drop coins held by ANY account (cross-account de-dup; replaces per-account rotation)."""
    exclude = set(held) | set(global_held or ())
    return [s for s in todo if s not in exclude]


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


def _ema_raw(values: list, n: int) -> list:
    """EMA seeded with the first value, no warm-up masking (for MACD on full-length series)."""
    out, e, a = [], None, 2.0 / (n + 1.0)
    for v in values:
        e = v if e is None else (v - e) * a + e
        out.append(e)
    return out


def macd_histogram(closes: list, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL) -> list:
    """MACD(12,26,9) histogram = (EMA12 - EMA26) - EMA9(MACD). Same length as closes."""
    if not closes:
        return []
    line = [f - s for f, s in zip(_ema_raw(closes, fast), _ema_raw(closes, slow))]
    sig = _ema_raw(line, signal)
    return [m - s for m, s in zip(line, sig)]


def adx_series(bars: list, n: int = ADX_N) -> list:
    """Wilder ADX(n). None until 2n bars are available."""
    out = [None] * len(bars)
    if len(bars) < 2 * n + 1:
        return out
    tr_s = pdm_s = ndm_s = 0.0
    dx_hist, adx = [], None
    for i in range(1, len(bars)):
        _, _o, h, l, _c, _v = bars[i]
        ph, pl, pc = bars[i - 1][2], bars[i - 1][3], bars[i - 1][4]
        up, dn = h - ph, pl - l
        pdm = up if up > dn and up > 0 else 0.0
        ndm = dn if dn > up and dn > 0 else 0.0
        tr = max(h - l, abs(h - pc), abs(l - pc))
        if i <= n:
            tr_s, pdm_s, ndm_s = tr_s + tr, pdm_s + pdm, ndm_s + ndm
            if i < n:
                continue
        else:
            tr_s += tr - tr_s / n
            pdm_s += pdm - pdm_s / n
            ndm_s += ndm - ndm_s / n
        pdi = 100.0 * pdm_s / tr_s if tr_s > 0 else 0.0
        ndi = 100.0 * ndm_s / tr_s if tr_s > 0 else 0.0
        dx = 100.0 * abs(pdi - ndi) / (pdi + ndi) if pdi + ndi > 0 else 0.0
        if adx is None:
            dx_hist.append(dx)
            if len(dx_hist) == n:
                adx = sum(dx_hist) / n
                out[i] = adx
        else:
            adx = (adx * (n - 1) + dx) / n
            out[i] = adx
    return out


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def calculate_smart_score(klines_4h: list, klines_1h=None):
    """v4.0 5-Pillar score (0-100) of the LAST closed 4H bar, LONG only (side="Buy").
    Input: ASCENDING closed bars [(ts, o, h, l, c, v)] (parse_klines + closed_only output).
    Returns dict(score, eligible, pillars, atr, close, bar_ts, side, ...) or None if not enough data.
    `eligible` is False if a hard gate fails (MACD hist > 0 and rising for 3 bars; close above the
    Donchian(20) high and EMA200; RVOL >= 1.25) — an ineligible coin is never traded whatever its score."""
    if len(klines_4h) < max(EMA_TREND, DONCHIAN_N + ATR_N, 2 * ADX_N + 1) + 5:
        return None
    closes = [b[4] for b in klines_4h]
    atrs = atr_series(klines_4h)
    atr = atrs[-1]
    e200 = ema_series(closes, EMA_TREND)[-1]
    if atr is None or atr <= 0 or e200 is None:
        return None
    ts, o, h, l, c, v = klines_4h[-1]
    gates = {}

    # P1 — MACD histogram expansion (0-25)
    hist = macd_histogram(closes)
    gates["macd"] = hist[-1] > 0 and hist[-1] > hist[-2] > hist[-3]
    slope_atr = (hist[-1] - hist[-3]) / 2.0 / atr
    p1 = (10.0 + 15.0 * _clamp01(slope_atr / 0.08)) if gates["macd"] else 0.0

    # P2 — candle anatomy & impulse (0-20)
    rng = h - l
    body = (c - o) / rng if rng > 0 else 0.0
    upper_wick = (h - c) / rng if rng > 0 else 1.0
    p2 = 0.0
    if body > 0:
        p2 = 12.0 * _clamp01(body / 0.60) + 8.0 * _clamp01((0.50 - upper_wick) / 0.30)

    # P3 — trend stability & breakout structure (0-20)
    donchian_high = max(b[2] for b in klines_4h[-DONCHIAN_N - 1:-1])
    gates["breakout"] = c > donchian_high and c > e200
    e20 = ema_series(closes, 20)[-1]
    e50 = ema_series(closes, 50)[-1]
    adx = adx_series(klines_4h)[-1] or 0.0
    stacked = e20 is not None and e50 is not None and e20 > e50 > e200
    p3 = 0.0
    if gates["breakout"]:
        p3 = 8.0 + (6.0 if stacked else 0.0) + 6.0 * _clamp01((adx - 15.0) / (ADX_MIN - 15.0))

    # P4 — relative volume surge (0-20); baseline = SMA of the 20 bars BEFORE the signal bar
    base = [b[5] for b in klines_4h[-RVOL_N - 1:-1]]
    sma_v = sum(base) / len(base) if base else 0.0
    rvol = v / sma_v if sma_v > 0 else 0.0
    gates["rvol"] = rvol >= RVOL_MIN
    p4 = (8.0 + 12.0 * _clamp01((rvol - RVOL_MIN) / (RVOL_MAX - RVOL_MIN))) if gates["rvol"] else 0.0

    # P5 — ATR% efficiency (0-15): range to reach TP; +3 if ATR is expanding vs 5 bars ago
    atr_pct = atr / c if c > 0 else 0.0
    prev_atr = atrs[-6] if len(atrs) >= 6 and atrs[-6] else atr
    p5 = 12.0 * _clamp01(atr_pct / ATR_PCT_TARGET) + (3.0 if atr > prev_atr else 0.0)

    score = p1 + p2 + p3 + p4 + p5
    h1_note = None
    if klines_1h and len(klines_1h) >= MACD_SLOW + MACD_SIGNAL + 3:
        h1 = macd_histogram([b[4] for b in klines_1h])
        if h1[-1] < 0:
            score -= H1_PENALTY
            h1_note = "1H MACD hist < 0"
    score = max(0.0, min(100.0, score))
    return {"score": round(score, 2), "eligible": all(gates.values()), "gates": gates,
            "pillars": {"macd": round(p1, 2), "candle": round(p2, 2), "trend": round(p3, 2),
                        "rvol": round(p4, 2), "atr_pct": round(p5, 2)},
            "rvol": rvol, "adx": adx, "atr_pct": atr_pct, "body": body, "upper_wick": upper_wick,
            "h1": h1_note, "atr": atr, "close": c, "bar_ts": ts, "side": "Buy"}


def qualifies(sig) -> bool:
    """v3.3: the validated v3.2 breakout signal (breakout_signal) is the entry gate. The v4.0
    5-pillar score is computed for logging only — its fixed-2R version failed the backtest."""
    return bool(sig) and bool(sig.get("eligible"))


def entry_brackets(entry: float, atr: float, score: float, tick: str):
    """Hard SL + hard TP for a LONG entry. Returns (sl_str, tp_str, rr)."""
    tp_mult = TP_ATR
    sl = round_price(entry - STOP_ATR * atr, tick, ROUND_DOWN)
    tp = round_price(entry + tp_mult * atr, tick, ROUND_HALF_UP)   # half-up: float noise never costs a tick
    return sl, tp, tp_mult / STOP_ATR


def repair_tp_price(side: str, entry: float, sl: float, mark: float, atr: float = 0.0):
    """TP for an open position that has none: entry +/- 2 x |entry - SL|. If the SL is missing or
    already on the profit side of entry (trailed), fall back to TP_ATR x ATR from entry. The TP is
    never placed on the wrong side of the current mark (the venue would reject it). None if no basis."""
    sign = 1 if side == "Buy" else -1
    if sl > 0 and (entry - sl) * sign > 0:
        tp = entry + sign * TP_REPAIR_R * abs(entry - sl)
    elif atr > 0:
        tp = entry + sign * TP_ATR * atr
    else:
        return None
    if atr > 0 and (tp - mark) * sign <= 0:
        tp = mark + sign * 0.25 * atr
    if tp <= 0 or (mark > 0 and (tp - mark) * sign <= 0):
        return None
    return tp


def tp_missing(p) -> bool:
    return _f(p.get("takeProfit")) <= 0


def allocate_symbols(ranked: list, accounts: list, global_active) -> dict:
    """Greedy cross-account routing. ranked = symbols best-first (already >= SMART_MIN_SCORE);
    accounts = [(account_id, open_slots), ...] in priority order. Each account receives the
    highest-ranked symbol not yet held/pending anywhere, which is then reserved globally. Accounts
    left without a coin stay in cash. Returns {account_id: [symbols]}; mutates global_active."""
    out = {}
    for acct, slots in accounts:
        out[acct] = []
        for _ in range(max(0, int(slots))):
            sym = next((s for s in ranked if s not in global_active), None)
            if sym is None:
                break
            out[acct].append(sym)
            global_active.add(sym)
    return out


def account_passed(equity: float, init: float, trading_days, profit_target: float = 0.0,
                   min_days: int = 5) -> bool:
    """Eval target reached (equity >= initial + target, default +10%) with the minimum trading days."""
    target = init + profit_target if profit_target > 0 else init * 1.10
    return init > 0 and equity >= target and int(_f(trading_days)) >= min_days


def is_stagnant(side: str, entry: float, mark: float, r_price: float, bars_held: int) -> bool:
    if r_price <= 0 or bars_held < STAGNANT_BARS:
        return False
    sign = 1 if side == "Buy" else -1
    return abs((mark - entry) * sign / r_price) <= STAGNANT_R


def trail_candidate(side: str, entry: float, r_price: float, bars_since_entry: list, atr: float) -> float:
    """v3.3: plain chandelier (HH since entry - TRAIL_ATR x ATR), applied tighten-only by manage().
    With BREAKEVEN_R > 0 it also waits for +BREAKEVEN_R and floors at entry (off by default)."""
    if not bars_since_entry or atr <= 0:
        return 0.0
    if BREAKEVEN_R <= 0 or r_price <= 0:
        return chandelier_stop(bars_since_entry, atr, side)
    if side == "Buy":
        hh = max(b[2] for b in bars_since_entry)
        if hh < entry + BREAKEVEN_R * r_price:
            return 0.0
        return max(entry, hh - TRAIL_ATR * atr)
    ll = min(b[3] for b in bars_since_entry)
    if ll > entry - BREAKEVEN_R * r_price:
        return 0.0
    return min(entry, ll + TRAIL_ATR * atr)


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
        self.paused_until = {}     # challenge -> unix time (new entries blocked until then)
        self.scores = {}           # bar_ts -> {symbol: smart-score dict} (shared by all accounts)
        self.locked = set()        # passed eval accounts: never open another trade

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
        key = (symbol, interval)
        ms = {INTERVAL: BAR_MS, INTERVAL_1H: H1_MS}.get(interval, DAY_MS)
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
        """v4.0 cycle: (1) audit + protect every active account (SL/TP repair, trail, brakes),
        (2) score the whole universe ONCE with the 5-pillar engine, (3) route the ranked coins to
        open account slots with strict cross-account de-duplication."""
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
            global_active = set()      # symbols held OR pending in ANY account
            ctxs = []
            for cid in active:
                try:
                    ctx = await self.process(mcp, cid, global_active)
                    if ctx:
                        ctxs.append(ctx)
                except MCPError as e:
                    log.warning("[%s] manage pass skipped (fail-safe): %s", cid, e)
                except Exception as e:
                    log.error("[%s] unexpected error: %s", cid, e, exc_info=True)
            if ctxs:
                try:
                    await self.route(mcp, ctxs, global_active)
                except MCPError as e:
                    log.warning("routing skipped (fail-safe): %s", e)
                except Exception as e:
                    log.error("routing unexpected error: %s", e, exc_info=True)
            log.info("SCAN CYCLE END — %d MCP calls", mcp.calls)

    async def process(self, mcp, ch, global_active=None):
        """Audit + protect one account. Returns a routing context dict if the account may open new
        trades (or swap a stagnant one) this cycle, else None."""
        det = await mcp.call("get_challenge", {"challengePublicId": ch})
        stage = det.get("currentStage") or {}
        stage_id = stage.get("publicId")
        if not stage_id or str(stage.get("status", "")).lower() != "active":
            log.info("[%s] stage not active — skipped", ch)
            return None
        funded = str(stage.get("type", "")).lower() == "funded"
        max_pos = MAX_POSITIONS_EVAL if not funded else MAX_POSITIONS
        init = _f(det.get("initialBalance"))
        rules = stage.get("rules") or {}
        daily_lim = _f(rules.get("drawdownLimit"), 0.04 * init)
        loss_lim = _f(rules.get("equityLossLimit"), 0.06 * init)
        sheet = {r.get("key"): r.get("value") for r in stage.get("ruleSheet") or [] if isinstance(r, dict)}
        margin_lim = init * _f(sheet.get("marginLimit"), 0) / 100.0
        cpv_lim = init * _f(sheet.get("cpvMultiplier"), 0)
        progress = stage.get("progress") or {}
        trading_days = int(_f(progress.get("tradingDays")))

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
        if global_active is not None:
            global_active.update(p["symbol"] for p in positions)
        tag = "FUNDED" if funded else "EVAL"
        log.info("[%s %s] equity $%.2f | DD today $%.2f/$%.2f | loss $%.2f/$%.2f | positions %d | days %s",
                 tag, ch[:8], equity, dd_today, daily_lim, loss_tot, loss_lim, len(positions), trading_days)

        # 0) passed-account hard lock — target + min days reached: flatten and never trade again
        if not funded and (ch in self.locked or account_passed(
                equity, init, trading_days, _f(rules.get("profitTarget")), int(_f(rules.get("minTradingDays"), 5)))):
            if ch not in self.locked:
                log.warning("[%s] PASSED: equity $%.2f >= target with %d trading days — LOCKED (no new trades)",
                            ch[:8], equity, trading_days)
            self.locked.add(ch)
            await self.flatten(mcp, ch, positions, "passed-account lock")
            return None

        # 1) emergency brake — daily drawdown close to the limit
        if positions and dd_today >= BRAKE_DAILY_FRAC * daily_lim:
            log.warning("[%s] BRAKE: DD $%.2f >= %.0f%% of daily limit — flattening", ch[:8], dd_today,
                        BRAKE_DAILY_FRAC * 100)
            await self.flatten(mcp, ch, positions, "brake")
            return None

        # 1b) intraday give-back kill switch: flatten + pause until 00:00 UTC
        if positions and dd_today >= GIVEBACK_KILL_FRAC * init:
            log.warning("[%s] GIVE-BACK KILL: DD $%.2f >= %.0f%% of init — flattening + pause", ch[:8],
                        dd_today, GIVEBACK_KILL_FRAC * 100)
            await self.flatten(mcp, ch, positions, "give-back kill")
            self.paused_until[ch] = (int(time.time() // 86400) + 1) * 86400
            return None

        # 2) manage open positions: SL repair, TP repair, breakeven/trail, stagnation flag
        open_risk, infos = 0.0, []
        for p in positions:
            gb, info = await self.manage(mcp, ch, p, pos_meta.get(p["symbol"]))
            open_risk += gb
            if info:
                infos.append(info)
        open_risk = await self.cap_giveback(mcp, ch, infos, open_risk, daily_lim, cushion)
        margin_used = sum(_effective_margin(p) for p in positions)
        cpv_used = sum(_f(p.get("positionValue")) for p in positions)

        # 2b) exposure reduction on funded accounts
        if funded and margin_lim > 0:
            margin_used = await self.reduce_exposure(mcp, ch, positions, init)

        # 3) stale entry limits; anything still pending counts as held for de-dup
        pending = await self.cancel_stale(mcp, ch)
        if global_active is not None:
            global_active.update(pending)

        # 4) gates for new entries
        trades = await mcp.call("get_stage_trades", {"stagePublicId": stage_id, "pageSize": 50})
        rows = trades.get("data", []) if isinstance(trades, dict) else []
        last_close = max((parse_iso(t.get("timestamp")) for t in rows if isinstance(t, dict)), default=0)
        if last_close and (time.time() - last_close) / 86400 > INACTIVITY_WARN_DAYS:
            log.warning("[%s] INACTIVITY: last closed trade %.0f days ago (account closes at 30)", ch[:8],
                        (time.time() - last_close) / 86400)
        ref_ts = last_close or parse_iso(met.get("startedAt"))
        if ref_ts and (time.time() - ref_ts) / 86400 >= KEEPALIVE_DAYS:
            try:
                await self.keepalive(mcp, ch, {p["symbol"] for p in positions} | set(global_active or ()),
                                     init, funded, margin_lim, margin_used)
            except MCPError as e:
                log.warning("[%s] keep-alive failed: %s", ch[:8], e)
        if time.time() < self.paused_until.get(ch, 0):
            log.info("[%s] paused (give-back kill) until %s", ch[:8],
                     datetime.fromtimestamp(self.paused_until[ch], timezone.utc).strftime("%H:%M UTC"))
            return None
        n_loss, last_loss_ts = consecutive_losses(rows)
        if n_loss >= LOSS_STREAK_N and (time.time() - parse_iso(last_loss_ts)) < LOSS_STREAK_PAUSE_H * 3600:
            log.warning("[%s] %d consecutive losses — new entries paused %dh", ch[:8], n_loss, LOSS_STREAK_PAUSE_H)
            return None
        if funded and balance - init >= 0.05 * init:
            log.warning("[%s] PAYOUT READY: profit $%.2f >= 5%% cap — no new entries until payout", ch[:8],
                        balance - init)
            return None
        stagnant = [i for i in infos if i.get("stagnant")]
        slots = max(0, max_pos - len(positions))
        if slots == 0 and not stagnant:
            return None
        clusters = {}
        for p in positions:
            clusters[correlation_group(p["symbol"])] = clusters.get(correlation_group(p["symbol"]), 0) + 1
        risk_pct = RISK_PCT_FUNDED if funded else RISK_PCT_EVAL
        return {"ch": ch, "funded": funded, "slots": slots, "stagnant": stagnant, "init": init,
                "equity": equity, "daily_lim": daily_lim, "loss_lim": loss_lim, "cushion": cushion,
                "open_risk": open_risk, "margin_lim": margin_lim, "cpv_lim": cpv_lim,
                "margin_used": margin_used, "cpv_used": cpv_used, "clusters": clusters,
                "trading_days": trading_days,
                "risk_usd": init * risk_pct / 100.0 * risk_scale(loss_tot, loss_lim)}

    async def flatten(self, mcp, ch, positions, why):
        for p in positions:
            try:
                if not DRY_RUN:
                    await mcp.call("close_position", {"challengePublicId": ch, "symbol": p["symbol"]})
                log.warning("  closed %s (%s)%s", p["symbol"], why, " [DRY RUN]" if DRY_RUN else "")
            except MCPError as e:
                log.error("  %s could not close %s: %s", why, p["symbol"], str(e)[:160])

    async def score_universe(self, mcp, ch):
        """Score every eligible symbol for the latest closed 4H bar (cached per bar). Returns
        (bar_ts, {symbol: sig}) — sig is the calculate_smart_score() dict incl. the 1H adjustment."""
        btc4 = await self.bars(mcp, ch, "BTCUSDT")
        if not btc4:
            raise MCPError("no closed BTC 4H bar")
        bar_ts = btc4[-1][0]
        for k in [k for k in self.scores if k != bar_ts]:
            del self.scores[k]
        scores = self.scores.setdefault(bar_ts, {})
        todo = [s for s in UNIVERSE if s not in scores and not is_blacklisted(s)]
        t0 = time.time()
        for sym in todo:
            if time.time() - t0 > SCAN_BUDGET_S:
                log.info("  scan time budget reached — remaining symbols next cycle")
                break
            try:
                b = await self.bars(mcp, ch, sym)
            except MCPError as e:
                log.info("  %s: no data this cycle (%s) — retry next cycle", sym, str(e)[:80])
                continue
            if not b or b[-1][0] != bar_ts:
                continue  # feed lagging; retry next cycle
            sig = breakout_signal(b)            # v3.3 entry gate + rank (validated)
            if sig:
                sig["eligible"] = True
                smart = calculate_smart_score(b)  # informational only
                sig["smart"] = smart["score"] if smart else None
            scores[sym] = sig
        return bar_ts, scores

    async def route(self, mcp, ctxs, global_active):
        """Rank qualifying coins and give each open slot the best coin not held/pending anywhere."""
        ch0 = ctxs[0]["ch"]
        btc_daily = await self.bars(mcp, ch0, "BTCUSDT", interval="D", limit=80)
        regime = market_regime(btc_daily)
        if regime in ("risk-off", "unknown"):
            log.info("BTC regime %s — no new longs", regime)
            return
        bar_ts, scores = await self.score_universe(mcp, ch0)
        ranked = sorted(((s["score"], sym) for sym, s in scores.items() if qualifies(s)), reverse=True)
        top = sorted(((s["score"], sym) for sym, s in scores.items() if s), reverse=True)[:6]
        log.info("regime %s | bar %s | scanned %d/%d | breakouts: %s", regime,
                 datetime.fromtimestamp(bar_ts / 1000, timezone.utc).strftime("%m-%d %H:%M"), len(scores),
                 len([s for s in UNIVERSE if not is_blacklisted(s)]),
                 ", ".join(f"{s}({sc:.1f}, smart {scores[s].get('smart')})" for sc, s in ranked[:6]) or "none")
        if not ranked:
            return

        # stagnation swap: a full account frees a slot by closing a dead trade for a strong mover
        for ctx in (ctxs if STAGNATION_SWAP else []):
            for info in ctx["stagnant"]:
                if ctx["slots"] > 0:
                    break
                best = next(((sc, s) for sc, s in ranked if s not in global_active), None)
                if not best or best[0] < SWAP_MIN_SCORE:
                    break
                log.warning("[%s] STAGNATION SWAP: closing %s (%d bars, %.2fR) for %s (score %.0f)",
                            ctx["ch"][:8], info["sym"], info["bars_held"], info["r_now"], best[1], best[0])
                try:
                    if not DRY_RUN:
                        await mcp.call("close_position", {"challengePublicId": ctx["ch"], "symbol": info["sym"]})
                except MCPError as e:
                    log.error("  swap close failed: %s", str(e)[:160])
                    continue
                ctx["slots"] += 1
                ctx["open_risk"] = max(0.0, ctx["open_risk"] - info["gb"])
                g = correlation_group(info["sym"])
                ctx["clusters"][g] = max(0, ctx["clusters"].get(g, 0) - 1)

        syms = [s for _sc, s in ranked]
        for ctx in ctxs:
            ch, tried = ctx["ch"], set()
            while ctx["slots"] > 0:
                cands = [s for s in syms if s not in tried and
                         ctx["clusters"].get(correlation_group(s), 0) < MAX_PER_CLUSTER]
                pick = allocate_symbols(cands, [(ch, 1)], global_active)[ch]
                if not pick:
                    break
                sym = pick[0]
                tried.add(sym)
                risk_usd = ctx["risk_usd"]
                if ctx["open_risk"] + risk_usd - ctx["cushion"] > OPEN_RISK_DAILY_FRAC * ctx["daily_lim"]:
                    log.info("[%s] budget: daily DD + open risk would exceed %.0f%% of limit — stop", ch[:8],
                             OPEN_RISK_DAILY_FRAC * 100)
                    global_active.discard(sym)
                    break
                if ctx["open_risk"] + risk_usd - (ctx["equity"] - ctx["init"]) > OPEN_RISK_TOTAL_FRAC * ctx["loss_lim"]:
                    log.info("[%s] budget: total loss + open risk would exceed %.0f%% of limit — stop", ch[:8],
                             OPEN_RISK_TOTAL_FRAC * 100)
                    global_active.discard(sym)
                    break
                try:
                    placed = await self.enter(mcp, ch, sym, scores[sym], risk_usd, ctx["equity"], ctx["init"],
                                              ctx["funded"], ctx["margin_lim"], ctx["cpv_lim"], ctx["margin_used"],
                                              ctx["cpv_used"], trading_days=ctx["trading_days"])
                except MCPError as e:
                    log.warning("  %s: entry rejected (%s)", sym, str(e)[:200])
                    placed = None
                if not placed:
                    global_active.discard(sym)   # another account may still be able to take it
                    continue
                ctx["slots"] -= 1
                ctx["open_risk"] += risk_usd
                g = correlation_group(sym)
                ctx["clusters"][g] = ctx["clusters"].get(g, 0) + 1
                ctx["margin_used"] += placed[0]
                ctx["cpv_used"] += placed[1]

    @staticmethod
    def give_back(p) -> float:
        """$ lost from the current mark if the stop fills (10% of notional if no stop)."""
        size, mark, sl = _f(p.get("size")), _f(p.get("markPrice")), _f(p.get("stopLoss"))
        sign = 1 if p.get("side") == "Buy" else -1
        return max(0.0, (mark - sl) * sign * size) if sl > 0 else 0.10 * mark * size

    async def manage(self, mcp, ch, p, meta):
        """Protect one open position every cycle:
          - SL missing  -> hard stop at entry - STOP_ATR x ATR
          - TP missing  -> hard TP at entry + 2 x |entry - SL| (TP repair)
          - price reached +1R -> SL to breakeven, then chandelier trail TRAIL_ATR x ATR (tighten only)
          - flags stagnation (>= STAGNANT_BARS closed 4H bars, within +-STAGNANT_R) for the swap logic
        Returns (give_back_usd, info)."""
        sym, side = p["symbol"], p.get("side")
        size, entry, mark = _f(p.get("size")), _f(p.get("avgPrice")), _f(p.get("markPrice"))
        sl, tp = _f(p.get("stopLoss")), _f(p.get("takeProfit"))
        sign = 1 if side == "Buy" else -1
        try:
            inst = await self.instrument(mcp, ch, sym)
            bars = await self.bars(mcp, ch, sym)
        except MCPError as e:
            log.warning("  %s: cannot manage this cycle (%s)", sym, e)
            return (max(0.0, (mark - sl) * sign * size) if sl > 0 else 0.10 * mark * size), None
        atr = (atr_series(bars)[-1] if len(bars) > ATR_N else None) or 0.0
        tick = inst["tickSize"]
        # R = initial stop distance; once the stop has been trailed past entry, approximate with STOP_ATR x ATR
        r_price = (entry - sl) * sign if sl > 0 and (entry - sl) * sign > 0 else STOP_ATR * atr
        created = parse_iso((meta or {}).get("createdTime")) * 1000 if meta else 0
        since = [b for b in bars if b[0] + BAR_MS > created] if created else []
        new_sl, why = None, ""
        if sl <= 0 and atr > 0:  # never leave a position naked
            new_sl = entry - sign * STOP_ATR * atr
            if (side == "Buy" and new_sl >= mark) or (side == "Sell" and new_sl <= mark):
                new_sl = mark - sign * 1.0 * atr
            why = "initial stop (was missing)"
        else:
            cand = trail_candidate(side, entry, r_price, since, atr)
            if tighten_only(side, sl, cand, mark):
                new_sl = cand
                why = "breakeven at +1R" if abs(cand - entry) < 1e-12 else f"chandelier {TRAIL_ATR}xATR"
        args = {}
        if new_sl:
            sl_str = round_price(new_sl, tick, ROUND_DOWN if side == "Buy" else ROUND_UP)
            if abs(float(sl_str) - sl) > 1e-12:
                args["stopLoss"] = sl_str
        if tp <= 0:  # hard TP repair
            basis_sl = float(args.get("stopLoss", sl))
            tp_px = repair_tp_price(side, entry, basis_sl, mark, atr)
            if tp_px:
                args["takeProfit"] = round_price(tp_px, tick, ROUND_HALF_UP)
                why = (why + "; " if why else "") + "TP repair (was missing)"
            else:
                log.warning("  %s: TP missing and no valid basis to repair it this cycle", sym)
        if args:
            if DRY_RUN:
                log.info("  [DRY] %s %s: would set %s (%s)", sym, side, args, why)
            else:
                try:
                    await mcp.call("set_trading_stop", {"challengePublicId": ch, "symbol": sym, **args})
                    log.info("  PROTECT %s %s: SL %s -> %s | TP %s -> %s (%s)", sym, side, p.get("stopLoss"),
                             args.get("stopLoss", p.get("stopLoss")), p.get("takeProfit") or "none",
                             args.get("takeProfit", p.get("takeProfit")), why)
                    sl = _f(args.get("stopLoss"), sl)
                    tp = _f(args.get("takeProfit"), tp)
                except MCPError as e:
                    log.warning("  %s: SL/TP update rejected (%s)", sym, str(e)[:160])
        pnl = _f(p.get("unrealisedPnl"))
        r_now = (mark - entry) * sign / r_price if r_price > 0 else 0.0
        bars_held = len([b for b in since if b[0] >= created]) if created else 0
        stagnant = is_stagnant(side, entry, mark, r_price, bars_held)
        log.info("  POS %s %s size %s entry %s mark %s SL %s TP %s uPnL $%.2f (%.2fR, %d bars)%s", sym, side,
                 p.get("size"), p.get("avgPrice"), p.get("markPrice"), sl, tp or "none", pnl, r_now, bars_held,
                 " STAGNANT" if stagnant else "")
        gb = max(0.0, (mark - sl) * sign * size) if sl > 0 else 0.10 * mark * size
        return gb, {"sym": sym, "side": side, "sign": sign, "size": size, "mark": mark, "sl": sl,
                    "tick": tick, "stagnant": stagnant, "bars_held": bars_held, "r_now": r_now, "gb": gb}

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
            notional = min(notional, MARGIN_ENTRY_FRAC * init - margin_used)
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

    async def reduce_exposure(self, mcp, ch, positions, init):
        """Force-close positions until total effective margin <= MARGIN_TRIM_TARGET_FRAC of initial
        balance, when it exceeds MARGIN_TRIM_FRAC. Biggest exposure first. Covers manual trades and
        legacy positions the entry guard can't see. Returns the (reduced) total margin used."""
        threshold = MARGIN_TRIM_FRAC * init
        target = MARGIN_TRIM_TARGET_FRAC * init
        margin_used = sum(_effective_margin(p) for p in positions)
        if margin_used <= threshold or not positions:
            return margin_used
        log.warning("[%s] EXPOSURE $%.0f > $%.0f (%.0f%% of init) — reducing to $%.0f", ch[:8],
                    margin_used, threshold, MARGIN_TRIM_FRAC * 100, target)
        for p in sorted(positions, key=lambda x: _effective_margin(x), reverse=True):
            if margin_used <= target:
                break
            sym, im = p["symbol"], _effective_margin(p)
            log.warning("  closing %s (margin $%.0f)", sym, im)
            if DRY_RUN:
                margin_used -= im
                continue
            try:
                await mcp.call("close_position", {"challengePublicId": ch, "symbol": sym})
                margin_used -= im
            except MCPError as e:
                log.error("  could not close %s: %s", sym, str(e)[:160])
        return margin_used

    async def cancel_stale(self, mcp, ch) -> set:
        """Cancel stale entry limits. Returns the symbols of entry orders still pending (they count as
        held for cross-account de-duplication)."""
        d = await mcp.call("list_open_orders", {"challengePublicId": ch, "limit": 50})
        now = time.time() * 1000
        pending = set()
        for o in (d.get("list", []) if isinstance(d, dict) else []):
            if o.get("reduceOnly") or o.get("stopOrderType"):
                continue
            if str(o.get("orderType")) != "Limit" or now - _f(o.get("createdTime"), now) < STALE_ENTRY_MS:
                if o.get("symbol"):
                    pending.add(o.get("symbol"))
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
                if o.get("symbol"):
                    pending.add(o.get("symbol"))
        return pending

    async def enter(self, mcp, ch, sym, sig, risk_usd, equity, init, funded,
                    margin_lim, cpv_lim, margin_used, cpv_used, trading_days=0):
        """Market LONG with BOTH a hard stopLoss and a hard takeProfit attached to the order."""
        inst = await self.instrument(mcp, ch, sym)
        tk = await mcp.call("get_tickers", {"challengePublicId": ch, "symbol": sym})
        row = (tk.get("list") or [{}])[0] if isinstance(tk, dict) else {}
        last = _f(row.get("lastPrice")) or sig["close"]
        if abs(last / sig["close"] - 1) > 0.5 * STOP_ATR * sig["atr"] / sig["close"]:
            log.info("  %s: price ran %.2f%% from the signal close — skip (chasing)", sym, 100 * (last / sig["close"] - 1))
            return None
        sl_str, tp_str, rr = entry_brackets(last, sig["atr"], sig["score"], inst["tickSize"])
        if not (0 < float(sl_str) < last < float(tp_str)):
            log.warning("  %s: invalid brackets SL %s / TP %s around %s — skip", sym, sl_str, tp_str, last)
            return None
        qty, notional = size_position(risk_usd, last, float(sl_str), equity, inst)
        if qty is None:
            log.info("  %s: size rejected (%s)", sym, notional)
            return None
        if not funded and trading_days < 5 and notional < 0.052 * init:
            log.info("  %s: notional $%.0f < 5.2%% of initial — SKIP (eval needs a qualifying trading day, %d/5)",
                     sym, notional, trading_days)
            return None
        if notional < MIN_NOTIONAL_PCT_INITIAL / 100.0 * init:
            log.info("  %s: notional $%.0f < 5%% of initial (would not count as a trading day) — still OK", sym, notional)
        args = {"challengePublicId": ch, "symbol": sym, "side": "Buy", "orderType": "Market",
                "qty": qty, "stopLoss": sl_str, "takeProfit": tp_str, "orderLinkId": order_link_id(sym, sig["bar_ts"])}
        pv = await mcp.call("preview_order", {k: v for k, v in args.items() if k != "orderLinkId"})
        im = max(_f(pv.get("estimatedInitialMargin")) if isinstance(pv, dict) else 0.0, notional)
        if funded:
            if margin_lim > 0 and margin_used + im > MARGIN_ENTRY_FRAC * init:
                log.warning("  %s: MARGIN GUARD %.0f + %.0f > %.0f%% of $%.0f init — skip", sym, margin_used, im,
                            MARGIN_ENTRY_FRAC * 100, init)
                return None
            if cpv_lim > 0 and cpv_used + notional > CPV_USE_FRAC * cpv_lim:
                log.warning("  %s: CPV GUARD — skip", sym)
                return None
        log.info("  >>> ENTRY %s LONG qty %s ~$%.0f notional @ ~%s | SL %s (%.1fxATR) | TP %s (%.1fR) | risk $%.2f | "
                 "score %.0f %s%s", sym, qty, notional, last, sl_str, STOP_ATR, tp_str, rr, risk_usd, sig["score"],
                 sig.get("pillars", {}), " [DRY RUN]" if DRY_RUN else "")
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
    log.info("QuantumTrader <-> HyroTrader bridge v%s | 4H Donchian(%d) breakout, long-only | hard SL %.1fxATR + "
             "TP %.0fR, chandelier %.1fxATR | risk eval %.2f%% funded %.2f%% | scan %ds | DRY_RUN=%s", VERSION,
             DONCHIAN_N, STOP_ATR, TP_R, TRAIL_ATR, RISK_PCT_EVAL, RISK_PCT_FUNDED, SCAN_INTERVAL, DRY_RUN)
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
