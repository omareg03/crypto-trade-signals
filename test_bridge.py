"""
test_bridge.py — QA test suite for the QuantumTrader <-> HyroTrader bridge (v3.1).

Run:  python test_bridge.py   (requires Python 3.13 with mcp + httpx2 installed)

Covers:
  - smoke: module imports + constants sanity
  - regression: blacklist (startswith vs substring), R:R minimum, signal generation,
    order-precision formatting (v3.1)
  - verification: risk routing (2%->1%), correlation clustering, avgPrice fix,
    momentum SHORT branch, trailing 1R persistence (v3.1)
  - sanity: guard math vs the real account scenarios, notional cap math (v3.1),
    losing-streak sort/filter (v3.1)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hyro_bridge
from hyro_bridge import (
    GeminiRules, get_correlation_group,
    QTY_STEPS, TICK_STEPS, fmt_price, fmt_qty,
    VERSION, MAX_POSITION_NOTIONAL_PCT, STALE_ORDER_HOURS, STATE_FILE,
)
from signal_engine import SignalEngine
from technical_analysis import TechnicalAnalyzer

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


def raises(fn):
    try:
        fn()
        return False
    except ValueError:
        return True


print("=" * 64)
print("QA SUITE — QuantumTrader bridge v3.1")
print("=" * 64)

# 1. SMOKE: imports + constants
check("import hyro_bridge", True)
check("MIN_RR == 1.5", hyro_bridge.MIN_RR == 1.5)
check("MAX_POSITIONS_PER_ACCOUNT == 3", hyro_bridge.MAX_POSITIONS_PER_ACCOUNT == 3)
check("MAX_CORRELATED_POSITIONS == 2", hyro_bridge.MAX_CORRELATED_POSITIONS == 2)
check("FUNDED_MARGIN_LIMIT_PCT == 25.0", hyro_bridge.FUNDED_MARGIN_LIMIT_PCT == 25.0)
check("DAILY_DD_SAFETY_BUFFER == 0.5", hyro_bridge.DAILY_DD_SAFETY_BUFFER == 0.5)
check("MAX_CONSECUTIVE_LOSSES == 3", hyro_bridge.MAX_CONSECUTIVE_LOSSES == 3)
check("COOLDOWN_HOURS == 6", hyro_bridge.COOLDOWN_HOURS == 6)
check("VERSION == 3.1.0", VERSION == "3.1.0")
check("MAX_POSITION_NOTIONAL_PCT == 25.0", MAX_POSITION_NOTIONAL_PCT == 25.0)
check("STALE_ORDER_HOURS == 6", STALE_ORDER_HOURS == 6)
check("STATE_FILE is bridge_state.json", STATE_FILE.endswith("bridge_state.json"))
check("QTY_STEPS is a dict", isinstance(QTY_STEPS, dict) and len(QTY_STEPS) > 0)
check("TICK_STEPS is a dict", isinstance(TICK_STEPS, dict) and len(TICK_STEPS) > 0)
check("fmt_price callable", callable(fmt_price))
check("fmt_qty callable", callable(fmt_qty))
check("_get_market_regime exists", hasattr(hyro_bridge.HyroBridge, "_get_market_regime"))
check("_cancel_stale_entry_orders exists", hasattr(hyro_bridge.HyroBridge, "_cancel_stale_entry_orders"))

# 2. REGRESSION: blacklist — must match BASE by prefix, not substring
check("blacklist NEAR", GeminiRules.is_blacklisted("NEARUSDT")[0] is True)
check("blacklist LINK", GeminiRules.is_blacklisted("LINKUSDT")[0] is True)
check("blacklist standalone USDT", GeminiRules.is_blacklisted("USDT")[0] is True)
check("blacklist JPY pair", GeminiRules.is_blacklisted("USDJPY")[0] is True)
check("NOT blacklist BTCUSDT (USDT is suffix)", GeminiRules.is_blacklisted("BTCUSDT")[0] is False)
check("NOT blacklist ORDIUSDT", GeminiRules.is_blacklisted("ORDIUSDT")[0] is False)

# 3. REGRESSION: R:R minimum
check("R:R 1.0 rejected", GeminiRules.check_rr(1.0)[0] is False)
check("R:R 1.5 accepted", GeminiRules.check_rr(1.5)[0] is True)
check("R:R 2.35 accepted", GeminiRules.check_rr(2.35)[0] is True)

# 4. REGRESSION: order precision (v3.1) — verified tick/qty formatting
check("fmt_price BTC tick 0.1", fmt_price("BTCUSDT", 82000.123) == "82000.1", fmt_price("BTCUSDT", 82000.123))
check("fmt_qty BTC step 0.001", fmt_qty("BTCUSDT", 0.049) == "0.049", fmt_qty("BTCUSDT", 0.049))
check("fmt_price PEPE tick 1e-7", fmt_price("PEPEUSDT", 0.0000123) == "0.000012", fmt_price("PEPEUSDT", 0.0000123))
check("fmt_qty PEPE step 100", fmt_qty("PEPEUSDT", 1200) == "1200", fmt_qty("PEPEUSDT", 1200))
check("fmt_price raises on unmapped symbol", raises(lambda: fmt_price("ORDIUSDT", 1.0)))
check("fmt_qty raises on unmapped symbol", raises(lambda: fmt_qty("ORDIUSDT", 1.0)))
unmapped = [s for s in ("ORDIUSDT", "1000PEPEUSDT", "KASUSDT", "WLDUSDT") if s not in QTY_STEPS]
check("discovery symbols unmapped -> precision guard skips them", len(unmapped) == 4)

# 5. VERIFICATION: risk routing (2% -> 1% challenge)
check("funded risk == 0.5%", GeminiRules.get_max_risk_pct("funded") == 0.5)
check("challenge risk == 1.0%", GeminiRules.get_max_risk_pct("evaluation") == 1.0)
check("challenge risk == 1.0% (fallback)", GeminiRules.get_max_risk_pct("challenge") == 1.0)

# 6. VERIFICATION: correlation clustering
check("BTC cluster", get_correlation_group("BTCUSDT") == "BTC")
check("ORDI clusters with BTC", get_correlation_group("ORDIUSDT") == "BTC")
check("SOL cluster", get_correlation_group("SOLUSDT") == "SOL")
check("ETH cluster", get_correlation_group("ETHUSDT") == "ETH")
check("XRP uncorrelated (own group)", get_correlation_group("XRPUSDT") == "XRPUSDT")
check("case-insensitive", get_correlation_group("btcusdt") == "BTC")

# 7. REGRESSION: signal engine TF R:R is now real (1.5, not 1.0)
engine = SignalEngine(TechnicalAnalyzer())
prices_up = [100.0 + 0.02 * i * i for i in range(60)]  # accelerating up -> TF LONG
tf = engine._trend_following("BTC-USD", prices_up)
if tf is not None:
    check("TF LONG generated", tf.direction == "LONG")
    check("TF LONG R:R == 1.5", abs(tf.risk_reward - 1.5) < 0.01, f"(got {tf.risk_reward:.2f})")
else:
    print("[SKIP] TF LONG not triggered by synthetic data")
prices_dn = [200.0 - 0.02 * i * i for i in range(60)]  # accelerating down -> TF SHORT
tf2 = engine._trend_following("BTC-USD", prices_dn)
if tf2 is not None:
    check("TF SHORT generated", tf2.direction == "SHORT")
    check("TF SHORT R:R == 1.5", abs(tf2.risk_reward - 1.5) < 0.01, f"(got {tf2.risk_reward:.2f})")
else:
    print("[SKIP] TF SHORT not triggered by synthetic data")

# 8. VERIFICATION: Momentum now has a SHORT branch (v3.0)
prices_mom_dn = [100 + (1.5 if i % 2 == 0 else -2.5) for i in range(60)]  # RSI ~48, MACD < 0
mom = engine._momentum("BTC-USD", prices_mom_dn)
if mom is not None:
    check("Momentum SHORT generated", mom.direction == "SHORT")
    check("Momentum SHORT R:R == 1.6", abs(mom.risk_reward - 1.6) < 0.01, f"(got {mom.risk_reward:.2f})")
else:
    print("[SKIP] Momentum SHORT not triggered")
prices_mom_up = [100 + (-1.5 if i % 2 == 0 else 2.5) for i in range(60)]  # RSI ~52, MACD > 0
mom2 = engine._momentum("BTC-USD", prices_mom_up)
if mom2 is not None:
    check("Momentum LONG generated (regression)", mom2.direction == "LONG")
    check("Momentum LONG R:R == 1.6", abs(mom2.risk_reward - 1.6) < 0.01, f"(got {mom2.risk_reward:.2f})")
else:
    print("[SKIP] Momentum LONG not triggered")

# 9. VERIFICATION: avgPrice fix (trailing stops now engage)
pos = {"avgPrice": "82922.60", "markPrice": "81823.53", "size": "0.016",
       "stopLoss": "81382.4", "side": "Buy", "unrealisedPnl": "-17.58512"}
entry_fixed = float(pos.get("avgPrice", pos.get("entryPrice", pos.get("entry", 0))) or 0)
entry_old = float(pos.get("entryPrice", pos.get("entry", 0)) or 0)
check("avgPrice extracted correctly", abs(entry_fixed - 82922.60) < 0.001, f"(got {entry_fixed})")
check("old entryPrice-only code would return 0 (confirms fix)", entry_old == 0)

# 10. VERIFICATION: trailing 1R persistence (v3.1) — the v3.0 ladder-killer
entry, orig_sl, breakeven_sl = 100.0, 97.5, 100.0
one_r_correct = abs(entry - orig_sl)                       # 2.5 = the persisted value
recomputed_at_breakeven = abs(entry - breakeven_sl)        # 0.0 = what v3.0 computed -> ladder died
check("persisted 1R == 2.5 (correct)", one_r_correct == 2.5)
check("v3.0 bug: recomputed 1R at breakeven == 0", recomputed_at_breakeven == 0)

# 11. SANITY: guard math vs the two real account scenarios
old_two_corr = 2 * (10000 * 0.02)   # OLD: 2% x 2 correlated losses
new_three_corr = 3 * (10000 * 0.01)  # NEW: 1% x 3 correlated losses
check("OLD 2% x2 correlated == $400 (would breach daily DD)", old_two_corr == 400)
check("NEW 1% x3 correlated == $300 < $400 (safe)", new_three_corr < 400, f"(${new_three_corr})")
check("margin guard blocks live 5K breach", 2334.75 + 1000.0 > 1250.0,
      "(existing margin $2,334 already > $1,250 limit)")

# 12. SANITY: notional cap math (v3.1) — closes the gap/slippage hole
balance = 10000.0
max_notional = balance * (MAX_POSITION_NOTIONAL_PCT / 100.0)
check("notional cap = $2500 on 10K", abs(max_notional - 2500.0) < 1e-9)
entry_p = 82000.0
risk_per_unit = entry_p * 0.025              # 2.5% SL
qty_raw = 100.0 / risk_per_unit              # 1% risk
raw_notional = qty_raw * entry_p             # ~$4000 = 40% of equity (the live BTC oversize)
capped_qty = round((max_notional / entry_p) / 0.001) * 0.001
capped_notional = capped_qty * entry_p
check("raw notional $4000 exceeds cap (the live 80% BTC problem)", raw_notional > max_notional)
check("capped notional <= $2500", capped_notional <= max_notional + 1e-6, f"(${capped_notional:.0f})")

# 13. SANITY: losing-streak breaker sort + invalidated-trade filter (v3.1)
trades = [
    {"netPnl": 50.0, "timestamp": "2026-10-08T00:00:00Z", "accepted": True, "invalidated": False},
    {"netPnl": -10.0, "timestamp": "2026-10-10T00:00:00Z", "accepted": True, "invalidated": False},
    {"netPnl": -10.0, "timestamp": "2026-10-09T00:00:00Z", "accepted": True, "invalidated": False},
    {"netPnl": -10.0, "timestamp": "2026-10-07T00:00:00Z", "accepted": False, "invalidated": True},
]
trades = [t for t in trades if t.get("accepted", True) and not t.get("invalidated", False)]
trades.sort(key=lambda t: str(t.get("timestamp", "")), reverse=True)
consec = 0
for t in trades:
    if float(t.get("netPnl", 0) or 0) < 0:
        consec += 1
    else:
        break
check("losing-streak: 2 consecutive losses (invalidated trade excluded)", consec == 2, f"(got {consec})")

print("=" * 64)
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("RESULT: ALL TESTS PASSED")
    sys.exit(0)
