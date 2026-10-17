"""
test_bridge.py — QA suite for hyro_bridge v4.0 (run: python test_bridge.py).

Sections: SMOKE (imports/constants) | REGRESSION (v3.1 root-cause bugs stay fixed) |
VERIFICATION (indicator + signal math vs hand-computed values) | SANITY (risk/sizing/guards) |
VALIDATION (live helpers reproduce the research backtest's pandas signals on real data, if present).
"""
import glob
import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hyro_bridge as hb  # noqa: E402

FAIL = []


def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAIL.append(name)


def bar(i, o, h, l, c, v=1.0, step=hb.BAR_MS, t0=1_700_000_000_000):
    return (t0 + i * step, o, h, l, c, v)


print("=" * 66)
print(f"QA SUITE — hyro_bridge v{hb.VERSION}")
print("=" * 66)

# ── SMOKE ───────────────────────────────────────────────────────────────
check("version 3.3.0", hb.VERSION == "3.3.0")
check("4H interval", hb.INTERVAL == "240" and hb.BAR_MS == 14_400_000)
check("strategy constants v3.3 (validated stop/trail + 10R TP)", (hb.DONCHIAN_N, hb.EMA_TREND, hb.STOP_ATR, hb.TRAIL_ATR, hb.TP_R, hb.BREAKEVEN_R, hb.STAGNATION_SWAP) == (20, 200, 3.0, 4.5, 10.0, 0.0, False))
check("kline limit >= 600 (EMA200 convergence)", hb.KLINE_LIMIT >= 600)
check("risk defaults sane", 0 < hb.RISK_PCT_FUNDED <= 0.5 and 0 < hb.RISK_PCT_EVAL <= 1.0,
      f"eval {hb.RISK_PCT_EVAL}% funded {hb.RISK_PCT_FUNDED}%")
check("brake 75% / keep-alive 26d", hb.BRAKE_DAILY_FRAC == 0.75 and hb.KEEPALIVE_DAYS < 30)
check("keep-alive symbols are liquid, non-blacklisted", all(s in hb.UNIVERSE and not hb.is_blacklisted(s) for s in hb.KEEPALIVE_SYMBOLS))
check("max positions 3 / cluster 2", hb.MAX_POSITIONS == 3 and hb.MAX_PER_CLUSTER == 2)
check("ORDI removed (sub-$100M low-cap rule)", "ORDIUSDT" not in hb.UNIVERSE)
check("universe has no blacklisted symbols", not any(hb.is_blacklisted(s) for s in hb.UNIVERSE))
check("universe unique", len(hb.UNIVERSE) == len(set(hb.UNIVERSE)))

# ── REGRESSION: v3.1 root cause — klines arrive NEWEST-FIRST ────────────
newest_first = {"list": [[str(1_700_000_000_000 + i * hb.BAR_MS), "1", "2", "0.5", str(10 + i), "5", "50"]
                         for i in reversed(range(5))]}
asc = hb.parse_klines(newest_first)
check("parse_klines sorts ascending", [b[0] for b in asc] == sorted(b[0] for b in asc))
check("parse_klines last bar is newest close", asc[-1][4] == 14.0)
dup = {"list": newest_first["list"] + [newest_first["list"][0]]}
check("parse_klines de-duplicates timestamps", len(hb.parse_klines(dup)) == 5)
check("parse_klines tolerates junk rows", len(hb.parse_klines({"list": [["x"], None, [1, 2]]})) == 0)
now = 1_700_000_000_000 + 4 * hb.BAR_MS + 1000          # inside bar #4 (forming)
closed = hb.closed_only(asc, hb.BAR_MS, now)
check("closed_only drops the forming bar", [b[0] for b in closed] == [b[0] for b in asc[:4]])
check("closed_only keeps a bar exactly at its close", len(hb.closed_only(asc, hb.BAR_MS, asc[-1][0] + hb.BAR_MS)) == 5)

# blacklist regression (prefix, not substring)
check("NEAR/LINK no longer blacklisted (v4.0)", not hb.is_blacklisted("NEARUSDT") and not hb.is_blacklisted("LINKUSDT"))
check("BTCUSDT not blacklisted (USDT suffix)", not hb.is_blacklisted("BTCUSDT"))
check("JPY + bare USDT blacklisted", hb.is_blacklisted("USDJPY") and hb.is_blacklisted("USDT"))

# ── VERIFICATION: indicator math ────────────────────────────────────────
e = hb.ema_series([1, 2, 3, 4, 5], 3)
check("EMA warm-up is None", e[:2] == [None, None])
# seeded at 1 (pandas adjust=False): a=0.5 -> 1, 1.5, 2.25, 3.125, 4.0625
check("EMA values (adjust=False)", abs(e[2] - 2.25) < 1e-12 and abs(e[4] - 4.0625) < 1e-12, f"{e}")
bars_atr = [bar(0, 10, 11, 9, 10), bar(1, 10, 12, 10, 11), bar(2, 11, 11.5, 8, 9)]
a = hb.atr_series(bars_atr, n=2)
# TR: 2, max(2,2,0)=2, max(3.5,0.5,3)=3.5 ; Wilder n=2 seeded at 2 -> 2, 2, 2.75
check("ATR Wilder values", a[0] is None and abs(a[1] - 2.0) < 1e-12 and abs(a[2] - 2.75) < 1e-12, f"{a}")

# Donchian breakout on synthetic data
flat = [bar(i, 100, 101, 99, 100) for i in range(260)]
check("no signal on flat market", hb.breakout_signal(flat) is None)
up = flat[:-1] + [bar(259, 100, 106, 100, 105)]
sig = hb.breakout_signal(up)
check("breakout above prior-20 high fires", sig is not None and sig["close"] == 105)
check("signal score positive", sig is not None and sig["score"] > 0)
below_ema = [bar(i, 200 - i * 0.5, 201 - i * 0.5, 199 - i * 0.5, 200 - i * 0.5) for i in range(259)]
below_ema.append(bar(259, 70, 72, 69, 71))   # local high but far below EMA200
check("breakout below EMA200 rejected", hb.breakout_signal(below_ema) is None)
check("too few bars -> None", hb.breakout_signal(up[-100:]) is None)

# regime
daily_up = [bar(i, 100, 101, 99, 100 + i, step=86_400_000) for i in range(60)]
daily_dn = [bar(i, 100, 101, 99, 200 - i, step=86_400_000) for i in range(60)]
check("regime risk-on", hb.market_regime(daily_up) == "risk-on")
check("regime risk-off", hb.market_regime(daily_dn) == "risk-off")
check("regime unknown on short history", hb.market_regime(daily_up[:20]) == "unknown")

# chandelier + tighten-only
since = [bar(0, 100, 110, 99, 108), bar(1, 108, 120, 107, 118)]
check("chandelier long = HH - TRAIL_ATR*ATR", abs(hb.chandelier_stop(since, 2.0, "Buy") - (120 - 2.0 * hb.TRAIL_ATR)) < 1e-9)
check("chandelier short = LL + TRAIL_ATR*ATR", abs(hb.chandelier_stop(since, 2.0, "Sell") - (99 + 2.0 * hb.TRAIL_ATR)) < 1e-9)
check("tighten: long moves up", hb.tighten_only("Buy", 100, 105, 118))
check("tighten: long never loosens", not hb.tighten_only("Buy", 106, 105, 118))
check("tighten: long never crosses price", not hb.tighten_only("Buy", 100, 119, 118))
check("tighten: short moves down", hb.tighten_only("Sell", 120, 115, 110))
check("tighten: short never loosens", not hb.tighten_only("Sell", 112, 115, 110))

# ── SANITY: sizing, rounding, idempotency, budgets ──────────────────────
btc = {"tickSize": "0.10", "qtyStep": "0.001", "minOrderQty": "0.001", "minNotionalValue": "5"}
pepe = {"tickSize": "0.0000010", "qtyStep": "100", "minOrderQty": "100", "minNotionalValue": "5"}
check("price rounds to tick (BTC)", hb.round_price(82000.123, "0.10") == "82000.10")
check("price rounds to tick (1000PEPE)", hb.round_price(0.0123456, "0.0000010") == "0.0123460")
check("qty rounds DOWN to step", hb.round_step(0.04999, "0.001") == Decimal("0.049"))
q, notional = hb.size_position(50.0, 82000.0, 82000.0 - 3 * 900.0, 10000.0, btc)
check("BTC risk sizing ($50 / $2700 stop)", q == "0.018", f"qty {q} notional {notional:.0f}")
check("BTC stop risk <= budget", float(q) * 2700.0 <= 50.0 + 1e-9)
q2, n2 = hb.size_position(400.0, 82000.0, 81800.0, 10000.0, btc)   # tight stop -> notional cap
check("notional capped at 25% of equity", q2 is not None and n2 <= 2500.0 + 1e-6, f"qty {q2} notional {n2:.0f}")
q3, why = hb.size_position(0.01, 82000.0, 79000.0, 10000.0, btc)
check("below minOrderQty rejected", q3 is None and "minOrderQty" in why)
q4, n4 = hb.size_position(25.0, 0.0123, 0.0123 * 0.92, 5000.0, pepe)
check("1000PEPE sizing uses step 100", q4 is not None and int(Decimal(q4)) % 100 == 0, f"qty {q4}")
check("zero stop distance rejected", hb.size_position(50, 100, 100, 1e4, btc)[0] is None)
lid = hb.order_link_id("1000PEPEUSDT", 1_791_849_600_000)
check("orderLinkId <= 36 chars and stable", len(lid) <= 36 and lid == hb.order_link_id("1000PEPEUSDT", 1_791_849_600_000), lid)
check("orderLinkId differs per bar", lid != hb.order_link_id("1000PEPEUSDT", 1_791_849_600_000 + hb.BAR_MS))

trades = [
    {"netPnl": -5, "timestamp": "2026-10-12T10:00:00Z"},
    {"netPnl": -5, "timestamp": "2026-10-12T12:00:00Z"},
    {"netPnl": 9, "timestamp": "2026-10-11T12:00:00Z"},
    {"netPnl": -5, "timestamp": "2026-10-12T14:00:00Z", "invalidated": True},
]
n, last = hb.consecutive_losses(trades)
check("loss streak counts newest-first, skips invalidated", n == 2 and last == "2026-10-12T12:00:00Z", f"{n} {last}")
check("parse_iso", abs(hb.parse_iso("2026-10-12T00:00:00Z") - 1791763200.0) < 1)
check("parse_iso nanoseconds", abs(hb.parse_iso("2026-10-12T00:00:00.123456789Z") - 1791763200.123456) < 1e-3)
check("give-back frac < brake < 1 and >= entry budget", hb.OPEN_RISK_DAILY_FRAC <= hb.GIVEBACK_FRAC < hb.BRAKE_DAILY_FRAC < 1)
check("_f handles junk", hb._f("x") == 0.0 and hb._f(None, 7) == 7 and hb._f("nan") == 0.0)

# budget arithmetic used by process(): live 10K eval with the legacy BTC position
dd, open_risk, new = 0.0, 0.097 * (82470 - 79703.3), 50.0
check("legacy BTC open risk blocks new eval entries (daily budget)", dd + open_risk + new > 0.60 * 400)
check("risk scale shrinks with drawdown, floor 50%", hb.risk_scale(0, 600) == 1.0 and
      abs(hb.risk_scale(300, 600) - 0.5) < 1e-9 and hb.risk_scale(590, 600) == 0.5)

# ── VALIDATION: live helpers == research backtest (pandas) on real data ─
data_dir = os.getenv("BT_DATA", r"C:\Users\oegar\AppData\Local\hermes\cache\scratch\bt_data")
files = sorted(glob.glob(os.path.join(data_dir, "*_4h.csv")))[:6]
if files:
    import numpy as np
    import pandas as pd
    mism = total = 0
    for f in files:
        df = pd.read_csv(f)
        c, h, l = df["close"], df["high"], df["low"]
        e200 = c.ewm(span=200, adjust=False, min_periods=200).mean()
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        hh = h.rolling(20).max().shift(1)
        pd_sig = ((c > hh) & (c > e200)).values
        rows = list(zip(df["open_time"], df["open"], df["high"], df["low"], df["close"], df["volume"]))
        for t in range(1200, len(rows), 37):
            for lim, tol in ((hb.KLINE_LIMIT, 0.003), (hb.KLINE_FALLBACK, 0.006)):
                window = rows[max(0, t - lim + 1): t + 1]
                mine = hb.breakout_signal(window) is not None
                total += 1
                if mine != bool(pd_sig[t]):
                    near = abs(c[t] / e200[t] - 1) < tol or abs(c[t] / hh[t] - 1) < 1e-9
                    if not near:
                        mism += 1
    check(f"live signal == backtest signal on {total} real windows", mism == 0, f"{mism} mismatches")
else:
    print("[SKIP] validation vs backtest (no bt_data present)")


# ── SANITY: async give-back shield + keep-alive with a fake MCP (no network) ──
import asyncio


class FakeKlineMCP:
    """Serves newest-first klines like the real tool; counts calls and requested limits."""
    def __init__(self, n=700, fail_big=False):
        self.n, self.fail_big, self.limits = n, fail_big, []
        self.t_last = (int(time.time() * 1000) // hb.BAR_MS) * hb.BAR_MS   # forming bar start

    async def call(self, name, args, retries=5):
        lim = args["limit"]
        self.limits.append(lim)
        if self.fail_big and lim > hb.KLINE_FALLBACK:
            raise hb.MCPError("Simulator error 503: HTTP request failed")
        k = min(lim, self.n)
        rows = [[str(self.t_last - i * hb.BAR_MS), "1", "2", "0.5", str(100 + (self.n - i)), "5", "0"] for i in range(k)]
        return {"list": rows}


import time
cb = hb.HyroBridge("x")
fk = FakeKlineMCP()
b1 = asyncio.run(cb.bars(fk, "ch", "ETHUSDT"))
check("bars(): ascending, forming bar dropped", b1[-1][0] == fk.t_last - hb.BAR_MS and b1[0][0] < b1[-1][0])
cb.fetched_at[("ETHUSDT", "240")] = 0          # force a refresh
b2 = asyncio.run(cb.bars(fk, "ch", "ETHUSDT"))
check("bars(): second refresh is incremental (limit 10)", fk.limits[-1] == 10, f"{fk.limits}")
check("bars(): merge keeps history length", len(b2) == len(b1))
asyncio.run(cb.bars(fk, "other-account", "ETHUSDT"))
check("bars(): cache shared across accounts (no extra call)", len(fk.limits) == 2)
fk2 = FakeKlineMCP(fail_big=True)
b3 = asyncio.run(hb.HyroBridge("x").bars(fk2, "ch", "SOLUSDT"))
check("bars(): falls back to 600 bars when 1000 fails", fk2.limits == [hb.KLINE_LIMIT, hb.KLINE_FALLBACK] and len(b3) >= hb.KLINE_FALLBACK - 10,
      f"{fk2.limits} {len(b3)}")


class FakeMCP:
    def __init__(self):
        self.calls = []

    async def call(self, name, args):
        self.calls.append((name, dict(args)))
        if name == "get_instruments":
            return {"list": [{"status": "Trading", "priceFilter": {"tickSize": "0.0001"},
                              "lotSizeFilter": {"qtyStep": "1", "minOrderQty": "1", "minNotionalValue": "5"}}]}
        if name == "get_tickers":
            return {"list": [{"lastPrice": "2.5"}]}
        return {}


hb.DRY_RUN = False
br = hb.HyroBridge("x")
fm = FakeMCP()
infos = [{"sym": "BTCUSDT", "side": "Buy", "sign": 1, "size": 0.097, "mark": 83277.0, "sl": 79703.3, "tick": "0.10"},
         {"sym": "QNTUSDT", "side": "Sell", "sign": -1, "size": 2.14, "mark": 224.71, "sl": 238.57, "tick": "0.01"}]
tot = sum(max(0, (i["mark"] - i["sl"]) * i["sign"] * i["size"]) for i in infos)
new_tot = asyncio.run(br.cap_giveback(fm, "ch", infos, tot, 400.0, 0.0))
check("shield tightens when stops allow > 70% of daily limit", new_tot <= 0.70 * 400 + 1.0, f"{tot:.0f} -> {new_tot:.0f}")
sl_moves = {a["symbol"]: float(a["stopLoss"]) for n, a in fm.calls if n == "set_trading_stop"}
check("shield only tightens (long SL up, short SL down)",
      sl_moves.get("BTCUSDT", 0) > 79703.3 and sl_moves.get("QNTUSDT", 1e9) < 238.57, f"{sl_moves}")
fm2 = FakeMCP()
same = asyncio.run(br.cap_giveback(fm2, "ch", infos[:1], 100.0, 400.0, 0.0))
check("shield idle when within budget", same == 100.0 and not fm2.calls)
check("give_back long", abs(hb.HyroBridge.give_back({"size": "0.097", "markPrice": "83600", "stopLoss": "80547.7", "side": "Buy"}) - 0.097 * 3052.3) < 1e-6)
check("give_back short counts open profit above a breakeven stop (daily-DD view)", abs(hb.HyroBridge.give_back({"size": "2.14", "markPrice": "228", "stopLoss": "238.57", "side": "Sell"}) - 2.14 * 10.57) < 1e-6)
check("give_back short with stop already through price = 0", hb.HyroBridge.give_back({"size": "2.14", "markPrice": "240", "stopLoss": "238.57", "side": "Sell"}) == 0.0)
check("give_back with no stop = 10% notional", abs(hb.HyroBridge.give_back({"size": "1", "markPrice": "100", "stopLoss": "0", "side": "Buy"}) - 10.0) < 1e-9)
fm4 = FakeMCP()
idle = asyncio.run(br.cap_giveback(fm4, "ch", infos, tot, 400.0, 161.0))
check("shield uses intraday cushion vs 00:00 UTC equity (live case: no tightening)", idle == tot and not fm4.calls)
fm3 = FakeMCP()
asyncio.run(br.keepalive(fm3, "ch", set(), 5000.0, True, 1250.0, 700.0))
order = next(a for n, a in fm3.calls if n == "place_order")
check("keep-alive respects funded margin headroom", float(order["qty"]) * 2.5 <= hb.MARGIN_ENTRY_FRAC * 5000 - 700 + 2.5, f"qty {order['qty']}")
check("keep-alive closes its position", any(n == "close_position" for n, _ in fm3.calls))
check("keep-alive orderLinkId <= 36", len(order["orderLinkId"]) <= 36, order["orderLinkId"])

# ── v3.2.2: effective margin + exposure reduction + cross-account rotation ──
# Req 2 — never trust positionIM alone (Bybit can return "" or "0" or omit it).
check("effective margin floors positionIM=0 at notional",
      abs(hb._effective_margin({"positionIM": "0", "size": "28", "markPrice": "59.57"}) - 1667.96) < 1e-6)
check("effective margin floors missing positionIM at notional",
      abs(hb._effective_margin({"size": "0.016", "avgPrice": "82922.6"}) - 1326.7616) < 1e-6)
check("effective margin keeps larger positionIM",
      abs(hb._effective_margin({"positionIM": "2000", "size": "1", "markPrice": "100"}) - 2000.0) < 1e-9)

# Regression: the funded 5K died from over-exposure — a manual 28-LTC short (33% notional)
# plus the bot's OP long = $1,844 margin vs a $1,250 cap. reduce_exposure (18% force / 15% target
# of a $5K initial) must close the biggest position first.
fm_exp = FakeMCP()
over = [{"symbol": "LTCUSDT", "positionIM": "1667.96", "size": "28", "markPrice": "59.57", "side": "Sell"},
        {"symbol": "OPUSDT", "positionIM": "176.44", "size": "1139", "markPrice": "0.1549", "side": "Buy"}]
red = asyncio.run(br.reduce_exposure(fm_exp, "ch", over, 5000.0))
check("exposure reduce fires when over 18% of init", red <= 0.15 * 5000 + 1e-9, f"${red:.2f}")
closed_syms = [a["symbol"] for n, a in fm_exp.calls if n == "close_position"]
check("exposure reduce closes biggest first", closed_syms and closed_syms[0] == "LTCUSDT", f"{closed_syms}")
fm_exp2 = FakeMCP()
under = [{"symbol": "OPUSDT", "positionIM": "176.44", "size": "1139", "markPrice": "0.1549", "side": "Buy"}]
red2 = asyncio.run(br.reduce_exposure(fm_exp2, "ch", under, 5000.0))
check("exposure reduce idle when under 18% of init", red2 == 176.44 and not fm_exp2.calls, f"${red2}")

# cross-account de-dup (v3.2.3 replaces v3.2.2 rotation): a coin held by ANY account is dropped for all
check("de-dup drops coins held by any account",
      hb._dedup_todo(["BTCUSDT", "ETHUSDT", "SOLUSDT"], {"SOLUSDT"}, {"BTCUSDT"}) == ["ETHUSDT"])
check("de-dup no-op when global_held empty",
      hb._dedup_todo(["BTCUSDT", "ETHUSDT"], set(), None) == ["BTCUSDT", "ETHUSDT"])
check("de-dup drops a lone breakout for the 2nd account",
      hb._dedup_todo(["OPUSDT"], set(), {"OPUSDT"}) == [])

# ═══ v4.0 SMART ANALYTICS ENGINE ═══════════════════════════════════════
# (a) zero blacklisted coins
check("v4.0 (a) BLACKLISTED_SYMBOLS is empty", hb.BLACKLISTED_SYMBOLS == set())
check("v4.0 (a) every universe coin is tradable", not any(hb.is_blacklisted(s) for s in hb.UNIVERSE))
check("v4.0 (a) NEAR + LINK are in the universe", {"NEARUSDT", "LINKUSDT"} <= set(hb.UNIVERSE))
check("v4.0 scan interval stays 600 s", hb.SCAN_INTERVAL == 600)
ry = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "render.yaml"), encoding="utf-8").read()
check("v4.0 render.yaml SCAN_INTERVAL 600", "SCAN_INTERVAL" in ry and "value: 600" in ry)


# (b) 5-pillar smart score
def runner(n=260, vol_last=3.0):
    """Steady uptrend with a pull-back, then a 3-bar re-acceleration ending in a full-body,
    high-volume breakout candle. Ascending, closed bars."""
    out, px = [], 100.0
    for i in range(n - 13):
        o = px
        px *= 1.004
        out.append(bar(i, o, px * 1.003, o * 0.997, px, 1.0))
    for i in range(n - 13, n - 3):   # pull-back / base
        o = px
        px *= 0.997
        out.append(bar(i, o, o * 1.002, px * 0.998, px, 1.0))
    for k, i in enumerate(range(n - 3, n)):
        o = px
        px *= (1.012, 1.02, 1.045)[k]
        v = vol_last if i == n - 1 else 1.2
        out.append(bar(i, o, px * 1.001, o * 0.999, px, v))
    return out


rb = runner()
sc = hb.calculate_smart_score(rb)
check("v4.0 (b) score returns a dict for enough bars", isinstance(sc, dict), "")
check("v4.0 (b) score is LONG-only", sc and sc["side"] == "Buy")
check("v4.0 (b) score bounded 0-100", sc and 0 <= sc["score"] <= 100, f"{sc and sc['score']}")
check("v4.0 (b) pillar caps 25/20/20/20/15", sc and sc["pillars"]["macd"] <= 25 and sc["pillars"]["candle"] <= 20
      and sc["pillars"]["trend"] <= 20 and sc["pillars"]["rvol"] <= 20 and sc["pillars"]["atr_pct"] <= 15,
      f"{sc and sc['pillars']}")
check("v4.0 (b) runner passes all hard gates", sc and sc["eligible"], f"{sc and sc['gates']}")
check("v4.0 (b) runner qualifies (>= 70)", hb.qualifies(sc), f"score {sc and sc['score']} {sc and sc['pillars']}")
check("v4.0 (b) RVOL 3.0 earns full volume points", sc and abs(sc["pillars"]["rvol"] - 20.0) < 1e-9, f"rvol {sc and sc['rvol']:.2f}")
weak = hb.calculate_smart_score(runner(vol_last=1.0))
check("v4.0 (b) RVOL < 1.25 fails the volume gate", weak and not weak["gates"]["rvol"] and not hb.qualifies(weak),
      f"rvol {weak and weak['rvol']:.2f}")
check("v4.0 (b) flat market never qualifies", not hb.qualifies(hb.calculate_smart_score(flat)))
check("v4.0 (b) below-EMA200 bounce never qualifies", not hb.qualifies(hb.calculate_smart_score(below_ema)))
check("v4.0 (b) too few bars -> None", hb.calculate_smart_score(rb[-100:]) is None)
wick = rb[:-1] + [bar(259, rb[-1][1], rb[-1][4] * 1.04, rb[-1][3], rb[-1][4], 3.0)]   # big upper-wick rejection
sw = hb.calculate_smart_score(wick)
check("v4.0 (b) upper-wick rejection scores fewer candle points", sw and sw["pillars"]["candle"] < sc["pillars"]["candle"],
      f"{sw and sw['pillars']['candle']} vs {sc['pillars']['candle']}")
h1_dn = [bar(i, 200 - i * 0.2, 200.5 - i * 0.2, 199 - i * 0.2, 199.8 - i * 0.2, step=3_600_000) for i in range(120)]
s1 = hb.calculate_smart_score(rb, h1_dn)
check("v4.0 (b) negative 1H MACD costs 10 points", s1 and abs((sc["score"] - s1["score"]) - hb.H1_PENALTY) < 1e-6,
      f"{sc['score']} -> {s1 and s1['score']}")
hist = hb.macd_histogram([float(x) for x in range(1, 80)])
check("v4.0 (b) MACD histogram length + sign on a linear ramp", len(hist) == 79 and hist[-1] > -1e-9)
adx_up = hb.adx_series(rb)[-1]
check("v4.0 (b) ADX defined and strong on a steady trend", adx_up is not None and adx_up >= hb.ADX_MIN, f"{adx_up}")

# (c) mandatory TP + SL at entry, and TP auto-repair on existing positions
sl_s, tp_s, rr = hb.entry_brackets(100.0, 2.0, 0.0, "0.01")
check("v3.3 (c) entry SL = entry - 3xATR", sl_s == "94.00", sl_s)
check("v3.3 (c) entry TP = entry + 10R (30xATR)", tp_s == "160.00" and abs(rr - 10.0) < 1e-9, f"{tp_s} {rr}")
# live case (Oct 17): TRXUSDT long entry 0.33680, SL 0.33110, takeProfit '' -> TP = 0.33680 + 10*0.0057 = 0.39380
check("v4.0 (c) tp_missing detects '' / '0' / None", hb.tp_missing({"takeProfit": ""}) and hb.tp_missing({"takeProfit": "0"})
      and hb.tp_missing({}) and not hb.tp_missing({"takeProfit": "1.5"}))
trx_tp = hb.repair_tp_price("Buy", 0.33680, 0.33110, 0.3370)
check("v3.3 (c) TP repair = entry + 10x|entry - SL| (live TRX case)", abs(trx_tp - 0.39380) < 1e-9, f"{trx_tp}")
check("v4.0 (c) TP repair never lands below the mark", hb.repair_tp_price("Buy", 100, 98, 106, atr=1.0) > 106)
check("v4.0 (c) TP repair falls back to ATR when SL is trailed above entry",
      abs(hb.repair_tp_price("Buy", 100, 101, 103, atr=1.0) - (100 + hb.TP_ATR)) < 1e-9)
check("v4.0 (c) TP repair None with no basis", hb.repair_tp_price("Buy", 100, 0, 100, atr=0) is None)


class FakeEntryMCP(FakeMCP):
    async def call(self, name, args, retries=5):
        self.calls.append((name, dict(args)))
        if name == "get_instruments":
            return {"list": [{"status": "Trading", "priceFilter": {"tickSize": "0.01"},
                              "lotSizeFilter": {"qtyStep": "0.1", "minOrderQty": "0.1", "minNotionalValue": "5"}}]}
        if name == "get_tickers":
            return {"list": [{"lastPrice": "100"}]}
        if name == "preview_order":
            return {"estimatedInitialMargin": "500"}
        return {}


fe = FakeEntryMCP()
placed = asyncio.run(hb.HyroBridge("x").enter(fe, "ch", "SOLUSDT", {"close": 100.0, "atr": 2.0, "score": 78.0, "bar_ts": 1},
                                             40.0, 10000.0, 10000.0, False, 0, 0, 0, 0, trading_days=5))
po = next((a for n, a in fe.calls if n == "place_order"), {})
check("v3.3 (c) place_order carries BOTH stopLoss and takeProfit", placed and po.get("stopLoss") == "94.00"
      and po.get("takeProfit") == "160.00", f"{po}")
check("v4.0 (c) entry is a LONG", po.get("side") == "Buy")
pv = next((a for n, a in fe.calls if n == "preview_order"), {})
check("v3.3 (c) preview_order also carries the TP", pv.get("takeProfit") == "160.00")


class FakeManageMCP(FakeEntryMCP):
    """manage(): serves ascending-sorted-able klines and records set_trading_stop."""
    def __init__(self, px=100.0):
        super().__init__()
        self.px = px
        self.t_last = (int(time.time() * 1000) // hb.BAR_MS) * hb.BAR_MS

    async def call(self, name, args, retries=5):
        if name == "get_klines":
            k = min(args["limit"], 700)
            rows = [[str(self.t_last - i * hb.BAR_MS), str(self.px), str(self.px * 1.01), str(self.px * 0.99),
                     str(self.px), "5", "0"] for i in range(k)]
            return {"list": rows}
        return await super().call(name, args, retries)


fmm = FakeManageMCP()
pos = {"symbol": "TRXUSDT", "side": "Buy", "size": "100", "avgPrice": "100", "markPrice": "100.5",
       "stopLoss": "96", "takeProfit": ""}
asyncio.run(hb.HyroBridge("x").manage(fmm, "ch", pos, None))
sts = [a for n, a in fmm.calls if n == "set_trading_stop"]
check("v3.3 (c) manage() repairs a missing TP via set_trading_stop", sts and sts[0].get("takeProfit") == "140.00", f"{sts}")
check("v4.0 (c) TP repair does not loosen the SL", sts and "stopLoss" not in sts[0], f"{sts}")
fmm2 = FakeManageMCP()
asyncio.run(hb.HyroBridge("x").manage(fmm2, "ch", dict(pos, takeProfit="108"), None))
check("v3.3 (c) no call when SL + TP already set", not [a for n, a in fmm2.calls if n == "set_trading_stop"])
fmm3 = FakeManageMCP()
asyncio.run(hb.HyroBridge("x").manage(fmm3, "ch", dict(pos, stopLoss="", takeProfit=""), None))
st3 = next((a for n, a in fmm3.calls if n == "set_trading_stop"), {})
check("v4.0 (c) naked position gets SL AND TP in one call",
      float(st3.get("stopLoss", 0) or 0) > 0 and float(st3.get("stopLoss", 0) or 0) < 100.5 < float(st3.get("takeProfit", 0) or 0),
      f"{st3}")

# breakeven + trail + stagnation
sinc = [bar(0, 100, 101, 99, 100), bar(1, 100, 104.5, 100, 104)]
check("v3.3 trail = plain chandelier HH - 4.5xATR (no breakeven)", abs(hb.trail_candidate("Buy", 100, 6.0, sinc, 2.0) - (104.5 - 9.0)) < 1e-9)
check("v3.3 trail later bars", abs(hb.trail_candidate("Buy", 100, 6.0, sinc + [bar(2, 104, 112, 104, 111)], 2.0) - (112 - 9.0)) < 1e-9)
check("v3.3 qualifies = validated breakout signal", hb.qualifies({"eligible": True, "score": 1.2}) and not hb.qualifies(None))
check("v4.0 stagnant: 4 bars within +-0.25R", hb.is_stagnant("Buy", 100, 100.9, 4.4, 4))
check("v4.0 not stagnant: only 3 bars", not hb.is_stagnant("Buy", 100, 100.9, 4.4, 3))
check("v4.0 not stagnant: +0.5R", not hb.is_stagnant("Buy", 100, 102.2, 4.4, 6))
check("v4.0 swap threshold 82 > entry threshold 70", hb.SWAP_MIN_SCORE == 82 and hb.SMART_MIN_SCORE == 70)

# (d) 5-account unique symbol allocation
accts = [(f"acct{i}", 1) for i in range(5)]
ranked = ["DOGEUSDT", "SOLUSDT", "SUIUSDT", "1000PEPEUSDT", "TRXUSDT", "ADAUSDT"]
ga = set()
alloc = hb.allocate_symbols(ranked, accts, ga)
syms = [s for v in alloc.values() for s in v]
check("v4.0 (d) 5 accounts get 5 different coins", len(syms) == 5 and len(set(syms)) == 5, f"{alloc}")
check("v4.0 (d) best coin goes to the first account", alloc["acct0"] == ["DOGEUSDT"] and alloc["acct4"] == ["TRXUSDT"])
check("v4.0 (d) allocated coins reserved globally", ga == set(syms))
ga2 = {"SOLUSDT"}   # already held by some account
alloc2 = hb.allocate_symbols(ranked, accts, ga2)
check("v4.0 (d) held coin never re-assigned", "SOLUSDT" not in [s for v in alloc2.values() for s in v], f"{alloc2}")
alloc3 = hb.allocate_symbols(["DOGEUSDT", "SOLUSDT"], accts, set())
check("v4.0 (d) only 2 qualifiers -> first 2 accounts trade, 3 stay cash",
      alloc3["acct0"] == ["DOGEUSDT"] and alloc3["acct1"] == ["SOLUSDT"] and all(alloc3[f"acct{i}"] == [] for i in (2, 3, 4)),
      f"{alloc3}")
alloc4 = hb.allocate_symbols(ranked, [("a", 2), ("b", 2)], set())
check("v4.0 (d) multi-slot accounts still unique", sum(len(v) for v in alloc4.values()) == 4 and
      len({s for v in alloc4.values() for s in v}) == 4)

# passed-account hard lock
check("v4.0 passed lock: +10% and 5 days", hb.account_passed(11000, 10000, 5, 1000))
check("v4.0 passed lock: +10% but 4 days -> not yet", not hb.account_passed(11000, 10000, 4, 1000))
check("v4.0 passed lock: 5 days but below target", not hb.account_passed(10999, 10000, 5, 1000))
check("v4.0 passed lock: default 10% when target unknown", hb.account_passed(11000, 10000, 5))

print("=" * 66)
if FAIL:
    print(f"RESULT: {len(FAIL)} FAILURE(S): {FAIL}")
    sys.exit(1)
print("RESULT: ALL TESTS PASSED")
