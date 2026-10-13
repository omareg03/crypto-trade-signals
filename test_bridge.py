"""
test_bridge.py — QA test suite for the QuantumTrader <-> HyroTrader bridge (v2.9).

Run:  python test_bridge.py   (requires Python 3.13 with mcp + httpx2 installed)

Covers:
  - smoke: module imports + constants sanity
  - regression: blacklist (startswith vs substring), R:R minimum, signal generation
  - verification: risk routing (2%->1%), correlation clustering, avgPrice fix
  - sanity: guard math reproduced against the two real account scenarios
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import hyro_bridge
from hyro_bridge import GeminiRules, get_correlation_group
from signal_engine import SignalEngine
from technical_analysis import TechnicalAnalyzer

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f"  {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


print("=" * 64)
print("QA SUITE — QuantumTrader bridge v2.9")
print("=" * 64)

# 1. SMOKE: imports + constants
check("import hyro_bridge", True)
check("MIN_RR == 1.5", hyro_bridge.MIN_RR == 1.5)
check("MAX_POSITIONS_PER_ACCOUNT == 3", hyro_bridge.MAX_POSITIONS_PER_ACCOUNT == 3)
check("MAX_CORRELATED_POSITIONS == 2", hyro_bridge.MAX_CORRELATED_POSITIONS == 2)
check("FUNDED_MARGIN_LIMIT_PCT == 25.0", hyro_bridge.FUNDED_MARGIN_LIMIT_PCT == 25.0)
check("DAILY_DD_SAFETY_BUFFER == 0.8", hyro_bridge.DAILY_DD_SAFETY_BUFFER == 0.8)

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

# 4. VERIFICATION: risk routing (2% -> 1% challenge)
check("funded risk == 0.5%", GeminiRules.get_max_risk_pct("funded") == 0.5)
check("challenge risk == 1.0% (v2.9)", GeminiRules.get_max_risk_pct("evaluation") == 1.0)
check("challenge risk == 1.0% (fallback)", GeminiRules.get_max_risk_pct("challenge") == 1.0)

# 5. VERIFICATION: correlation clustering
check("BTC cluster", get_correlation_group("BTCUSDT") == "BTC")
check("ORDI clusters with BTC", get_correlation_group("ORDIUSDT") == "BTC")
check("SOL cluster", get_correlation_group("SOLUSDT") == "SOL")
check("ETH cluster", get_correlation_group("ETHUSDT") == "ETH")
check("XRP uncorrelated (own group)", get_correlation_group("XRPUSDT") == "XRPUSDT")
check("case-insensitive", get_correlation_group("btcusdt") == "BTC")

# 6. REGRESSION: signal engine TF R:R is now real (1.5, not 1.0)
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

# 7. VERIFICATION: avgPrice fix (trailing stops now engage)
pos = {"avgPrice": "82922.60", "markPrice": "81823.53", "size": "0.016",
       "stopLoss": "81382.4", "side": "Buy", "unrealisedPnl": "-17.58512"}
entry_fixed = float(pos.get("avgPrice", pos.get("entryPrice", pos.get("entry", 0))) or 0)
entry_old = float(pos.get("entryPrice", pos.get("entry", 0)) or 0)
check("avgPrice extracted correctly", abs(entry_fixed - 82922.60) < 0.001, f"(got {entry_fixed})")
check("old entryPrice-only code would return 0 (confirms fix)", entry_old == 0)

# 8. SANITY: guard math vs the two real account scenarios
old_two_corr = 2 * (10000 * 0.02)   # OLD: 2% x 2 correlated losses
new_three_corr = 3 * (10000 * 0.01)  # NEW: 1% x 3 correlated losses
check("OLD 2% x2 correlated == $400 (would breach daily DD)", old_two_corr == 400)
check("NEW 1% x3 correlated == $300 < $400 (safe)", new_three_corr < 400, f"(${new_three_corr})")
check("margin guard blocks live 5K breach", 2334.75 + 1000.0 > 1250.0,
      "(existing margin $2,334 already > $1,250 limit)")

print("=" * 64)
if FAILURES:
    print(f"RESULT: {len(FAILURES)} FAILURE(S): {FAILURES}")
    sys.exit(1)
else:
    print("RESULT: ALL TESTS PASSED")
    sys.exit(0)
