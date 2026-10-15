"""
test_bridge.py — QA suite for hyro_bridge v3.2 (run: python test_bridge.py).

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
check("version 3.2.3", hb.VERSION == "3.2.3")
check("4H interval", hb.INTERVAL == "240" and hb.BAR_MS == 14_400_000)
check("strategy constants", (hb.DONCHIAN_N, hb.EMA_TREND, hb.STOP_ATR, hb.TRAIL_ATR) == (20, 200, 3.0, 4.5))
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
check("blacklist NEAR/LINK", hb.is_blacklisted("NEARUSDT") and hb.is_blacklisted("LINKUSDT"))
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
check("chandelier long = HH - 4.5*ATR", hb.chandelier_stop(since, 2.0, "Buy") == 120 - 9.0)
check("chandelier short = LL + 4.5*ATR", hb.chandelier_stop(since, 2.0, "Sell") == 99 + 9.0)
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

print("=" * 66)
if FAIL:
    print(f"RESULT: {len(FAIL)} FAILURE(S): {FAIL}")
    sys.exit(1)
print("RESULT: ALL TESTS PASSED")
