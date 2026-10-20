# QuantumTrader v2.0 Risk Manager Rules

## Core Rules
1. **NEVER modify `main.py`** — the core logic is battle-tested and locked.
2. **Only modify `dashboard.py`** for display/cosmetic changes (symbol names, formatting).
3. **Always cross-check Mean Reversion signals against live macroeconomic context.**
   - If the macro trend is bullish for an asset, REJECT Mean Reversion SHORT signals.
   - If the macro trend is bearish for an asset, REJECT Mean Reversion LONG signals.
   - Only trust Mean Reversion when macro is neutral/rangebound.
   - **FOREX Mean Reversion: Auto-reject.** Historical data shows forex MR signals consistently produce R:R of 0.3-0.5, well below the 1.5:1 minimum. Only trade forex on Trend Following or Momentum signals (provided Momentum R:R is >= 1.5).
3a. **Crypto Mean Reversion trend filter:** REJECT an MR SHORT if the asset just broke a downtrend / trades above its 50-day MA with bullish MACD (breakouts keep RSI > 70). REJECT an MR LONG if it just broke down. MR entries must sit at a structural S/R level, with SL beyond it and TP before the next opposing level, never the engine's fixed 4% SL / middle-band TP. The engine "confidence" is RSI extremity (`70 + (RSI-70)*2`), not win probability.
4. **Always verify dashboard signals with web search** for current prices, news, and trends before advising entry.
4a. **Price-source check:** dashboard prices (Yahoo) can differ from Match-Trader/Cleo (gold showed ~$40-60 above spot on Oct 6, 2026, cause unconfirmed). Recompute entry/SL/TP from the live broker price before ordering.

## Trading Rules
5. **Tuesday–Thursday entries only** for forex. Crypto can trade 24/7 but prefer Tue–Thu.
   Weekends: crypto limit orders allowed (user is off work and can analyze calmly), standard size, max 1 new position per account.
6. **London/NY overlap (12:00–16:00 GMT = 8am–12pm ET)** is the preferred FILL window for forex.
   The user works Mon–Fri 8am–6pm ET and CANNOT trade it live. Always propose LIMIT orders
   (with SL+TP attached) placed the evening before (Mon/Tue/Wed nights) so they fill during the overlap.
   Evening review after the 4H candle close at 8:00 PM ET (7:00 PM ET after DST ends Nov 1).
7. **0.5% risk on funded accounts** until a 3-win streak is established, then scale to 1%.
8. **1.5%–2% risk on challenge accounts** — never exceed 2%.
8a. **Thin-buffer exception:** if a challenge account's buffer to its max-loss floor is < 3R at normal size,
    cut risk so the buffer holds ≥ 4R (e.g. buffer $205 → risk ≤ $50). Run the Monte Carlo before sizing.
    (Oct 4 sim, pd2x19s floor $9,400: $100 risk → 64–85% pass; $50 → 82–96%; $25 → 95–99.6%.)
8b. **No daily dollar quotas.** Never force trades to hit "$X per day". Targets are weekly/monthly expectancy only.
9. **Minimum 1:1.5 Risk-to-Reward ratio** — reject any trade below this.
10. **Always use stop loss** — no exceptions, ever.
11. **Max 2-3 correlated positions** per account.
12. **Swap stagnant trades** when: position flat 48+ hours with no momentum, a higher-confidence signal (>70%) appears on a different asset with better R:R. Close old trade first, THEN enter new one.
13. **ABSOLUTE BAN ON MANUAL TRADES ON BOT-CONNECTED ACCOUNTS.**
    - Never enter or close trades manually inside any HyroTrader account connected to `hyro_bridge.py`.
    - **Why**: HyroTrader checks Initial Margin in real-time. Manual trades placed at 1x leverage consume 100% of notional as margin. Stacking a manual trade on top of bot positions immediately trips the 25% margin cap ($1,250 on $5K) and triggers instant account failure.
    - Discretionary or dashboard trades must be taken ONLY on separate, dedicated accounts with zero bot automation.

## Prop Firm Context
- **HyroTrader**: Crypto futures via Hyro Terminal (my.hyrotrader.com). Migrated from Cleo.finance/Bybit on Oct 7, 2026. Best for crypto.
- **Funding Pips**: Forex/multi-asset via Match-Trader. Best for forex.
- **FundedNext**: Backup legitimate firm.
- **Swing Drawdown Upgrade** is always enabled (balance-based, not equity-based).
- The user is a **swing trader** on 4H timeframe with overnight holds.
- **Reinvestment Rule**: 30% → scaling fund (next challenge) | 20% → tax reserve
  (prop payouts = US self-employment income, 15.3% SE tax, no withholding; challenge fees deductible — keep receipts)
  | 50% → income/emergency fund. Scaling fund: $32.16 of $321.10 needed for the 25K HyroTrader challenge.
- **Never risk personal money, rent, or the emergency fund in trading.** Long-term goal = buy a house.
  The W-2 job (Mon–Fri 8am–6pm ET) is the mortgage-qualifying income; trading must never compromise it.
- **Scaling Path**: 5K → 10K → 25K → 50K → 100K → 200K (use profits, not out-of-pocket).
- **Monthly Target**: 5-10% net return, 6-8 trades/month, 65% win rate. (Realistic at 1% risk: 2.5–4.5%/month.)
- **Time Commitment**: 15-30 min/night, 4-5 nights/week (Tue-Thu preferred) + weekend analysis.

## Active Account Portfolio (Updated: Oct 14, 2026 — Post-v3.2.3 Deployment)
> All HyroTrader accounts are **One-Step**. Official One-Step rules (hyrotrader.com/trading-rules):
> max loss **6% of initial balance, fixed, equity-based (incl. unrealized)** | daily drawdown **4% static**, from start-of-day equity, reset 00:00 UTC |
> **5 minimum trading days** (a day counts only if you CLOSE ≥1 trade with notional ≥5% of initial balance that moved ≥1% of trade value) |
> 40% of profit target per day cap (excess doesn't count; losing days count in full) | account closes after 30 days with no trades.
- **5K Funded (xt0ipo8)**: **TERMINATED (Oct 14, 2026)**. Failed due to Max Exposure violation ($1,844.40 Initial Margin vs $1,250.00 cap) triggered when a manual 28-LTC short executed at 1x leverage and stacked on top of the bot's OP position.
- **10K Challenge (28xldlj1SuSy25GQWEMm0E, Bybit Simulator)**: **ACTIVE (SOLE SURVIVING HYRO ACCOUNT)**. (The old Cleo ID 8pbmfu0 is EXPIRED — never use it.) Floor $9,400 | Target $11,000 (+$1,000) | Trading Days: 3 of 5 completed (Oct 19). Bot v3.3.0 at 0.40% risk ($40), MAX_POSITIONS_EVAL = 1. No manual trading allowed on this account.
- **10K Challenge (pd2x19s / 5IvGsKwh)**: TERMINATED (Oct 12, 2026). Failed due to daily drawdown give-back breach under v3.1 backwards-kline bug.
- **Funding Pips Challenge**: ACTIVE. Web dashboard is configured for **$5K 2-Step Flex** (likely the user's account; phase/balance still unconfirmed). Forex Trend Following only.
  Official 2-Step Flex rules (fundingpips.com, checked Oct 4, 2026): P1 target 10%, P2 target 8%, **daily loss 4%**, max loss 12% static,
  1 min trading day, no time limit. Dashboard config says 5% daily / 10% max → use the STRICTER of each (4% daily = $200, 10% max = $500) until the user confirms.
  On $5K: max 2 open positions at ~$75 risk each (3 stops in one day would breach the $200 daily limit). Gold min lot 0.01 = $65 risk on a $65 stop.
  Master (funded) accounts auto-close at Friday close unless Swing add-on purchased; high-impact news window restricted.
- **Payout Pipeline**: HyroTrader (my.hyrotrader.com, Payouts tab) → USDC → Coinbase → Bank. Legacy pipeline was Cleo → Solana USDC. New payout method TBD — confirm in Payouts tab.
- **Profit Split**: 80/20 (up to 90%). Min payout: $100. One-Step deposit is refunded with the first funded payout.
- **Match-Trader UI Rules**:
  - Limit Orders are located under the **"Pending"** tab (not "Limit").
  - Position sizing: toggle **"Risk Mode"** ON to see risk in USD, or manually adjust the Volume (+/-) until the USD risk amount matches the target (e.g., 0.02 Volume = $50 risk for our standard swing trades).

## System Architecture
- **QuantumTrader CMD** (local): `C:\Users\oegar\OneDrive\Documents\Antigravity Folder Projects\KDP Optimization - Amazon\QuantumTrader\`
  Launch: `python main.py --mode live` (path verified on disk Oct 4, 2026)
- **QuantumTrader Web v2.0** (Render): Located at `Crypto 2026 - Pips, Coinbase\`
- **Live Web URL**: https://crypto-trade-signals-epok.onrender.com/ (the URLs in DEPLOYMENT_GUIDE/README do not load).
- These are SEPARATE projects with different configs but identical signal logic.
- CMD has 9 cryptos (CoinGecko), Web has 46 assets across 5 categories (Yahoo Finance).
- Web covers: 12 Crypto, 12 Forex, 7 Commodities, 7 Indices, 8 Stocks.
- Both are trustworthy for signals. Web has full multi-asset coverage.
- Web dashboard (checked Oct 6, 2026) shows 3 strategies: Trend Following, Mean Reversion, **Momentum** (RSI/MACD bullish zone, R:R 1.6). The target column is **TP1**. It has a prop-firm selector (Funding Pips / Cleo.finance — NOTE: Cleo no longer active as of Oct 7, 2026; HyroTrader now uses Hyro Terminal). Signals load via JavaScript: read them with the browser subagent and the "All" tab (view-only), not `read_url_content`.

## Known System Limitations
- **Trend Following R:R is hardcoded at 1.0** in signal_engine.py (line 87).
  The formula `rr = round((current * 0.03) / (current * 0.03), 2)` always equals 1.0.
  When a Trend Following signal appears, the R:R on the dashboard will always show 1.0.
  **Workaround**: Manually recalculate R:R using live support/resistance levels before entry.
  The pd2x19s LINK trade used manual levels (Entry $14.49, SL $14.06, TP $15.50 → R:R 2.35).

## Blacklisted Assets (Do NOT Trade)
- **NEAR / LINK**: Manual-trading history: NEAR stopped out 3+ times, LINK stopped on pd2x19s. As of bot v4.0 (Oct 17, 2026) the user REMOVED all static coin blacklists from the bot: NEAR and LINK are bot-eligible when they score >= 70. Do not re-add a ticker blacklist to hyro_bridge.py.
- **JPY Pairs (Japan)**: User explicitly refused to trade Japan. Do not propose USD/JPY, EUR/JPY, GBP/JPY, etc.

## HyroTrader-Specific Rules (verified against hyrotrader.com/trading-rules, Oct 4, 2026)
- **Profit Distribution Rule (Evaluation Only)**: No single trading day may count for more than **40% of the profit target**. Profit above the cap stays in the account but doesn't count toward the target; losing days count in full. Spread challenge gains across 3+ trading days.
- **What happens if violated**: HyroTrader caps that day's contribution at 40% and may assign a new account with a revised profit target (this is how 8pbmfu0 was created).
- **Does NOT apply to funded accounts** — only during evaluation.
- **Minimum trading days**: One-Step = 5. A day counts only if a trade is CLOSED that day (UTC) with notional ≥ 5% of initial balance (≥ $500 on 10K) and a move ≥ 1% of the trade's value (before fees).
  Tactic: small "qualifying" trades (e.g. $600–1,000 notional with a normal stop) can collect required days cheaply. They are NOT an income strategy.
- **Max realized loss per single position**: 3% of initial balance.
- **Inactivity**: account closes after 30 days without trading.
102a. **Payout freeze (HyroTrader official):** After requesting a payout, HyroTrader requires all positions closed and no new trades until the USDC arrives (~12-24h). To comply: suspend the bot on Render, close positions on the ONE account withdrawing, request payout, wait for USDC, then resume the bot. The other accounts can resume immediately after — only the withdrawing account must stay frozen during the 12-24h payout window.

## Outside Signal Services, Micro-Trading & Coinbase
- Do NOT follow StocksToTrade / Tim Bohen / similar alert services. Claims (e.g. "88.7% win rate") are unverified marketing; they require market-hours screen time and options trading, incompatible with the user's 8am–6pm job and prop-firm swing system. Free education only.
- **Do NOT micro-trade the personal Coinbase balance.** Coinbase US Advanced lowest tier = 0.50% maker / 0.90% taker (Sept 2026). On $107 a mixed round trip costs ~$1.50; a 2% winning move nets ~$0.64 while a 2% loss costs ~$3.64. Negative expectancy.
- "$50/day" = 46.7%/day on $107 (impossible), 0.97%/day on the 5K funded (~21%/month, unrealistic), 0.20%/day across all HyroTrader sim capital (~4.4%/month, upper-realistic as an AVERAGE, never as a quota). Only FUNDED accounts produce cash. $1,500/month cash needs ~$42K–75K funded capital → scale, don't grind.
- Coinbase stocks/ETFs (zero commission, fractional, 24/5): long-term passive investing ONLY, after an emergency fund exists. USDC on Coinbase is not FDIC-insured; move the emergency fund to an FDIC-insured HYSA once it exceeds ~$500.
- **Day trading: not now.** Peak liquidity (13:00–16:00 UTC = 9am–12pm ET) falls inside the user's work hours; evenings are the thinnest sessions. Chague et al. (Brazil): 97% of 300+-day day traders lost money, ~0.5% earned > ~$54/day. FINRA PDT $25K rule eliminated June 4, 2026 (broker phase-in to Oct 20, 2027), which does not change the odds. Never check trades at work (the W-2 job is the mortgage income).
  Allowed exception: small qualifying trades to collect HyroTrader minimum trading days. Revisit after 3 months of journaled swing results + free weekday hours.

## Tri-Hermes Oversight Protocol
- **Local Agent Synergy:** Antigravity (Gemini) acts as the primary quantitative strategist (running the dashboard, checking macro, calculating R:R).
- **Mandatory Review:** Before presenting the final `weekly_game_plan.md` to the user, Antigravity MUST send the draft plan to the local Tri-Hermes instance via a local API bridge (e.g., `scratch/hermes_bridge.py`).
- **Integration:** Antigravity will append Hermes's feedback, warnings, or approvals to the bottom of the game plan under a dedicated "Hermes Oversight" section.

## Consultation Protocol
- The user MUST be consulted before every trade entry.
- Always provide: coin, direction, entry, SL, TP, risk %, position size, and reasoning.
- Always flag if the signal is Mean Reversion (requires macro cross-check).

## Bot v3.3.0 (Oct 17, 2026) — HyroTrader automation rules (chosen by backtest over v4.0)
- Strategy: 4H Donchian(20) breakout, LONG only; close > EMA200 (4H); BTC daily close not below SMA50*0.995. No ticker blacklist.
- Exits: hard SL 3.0xATR(14) AND hard TP at 10R (30xATR) on EVERY order; any open position missing a TP gets one each cycle
  (TP = entry + 10x|entry - SL|). Chandelier trail 4.5xATR, tighten-only. No breakeven ratchet, no stagnation swap.
- Routing: one scan per cycle, ranked breakouts go to open slots across ALL accounts; a coin held or pending anywhere is never
  assigned again. Passed-account hard lock (target + 5 trading days -> flatten, never trade again).
- Backtest (research/v33_decision_run1.txt, 34 coins, Jul-2023..Oct-2026, 1 eval slot): v3.3 +0.54R/trade (IS +0.41R, OOS +0.71R),
  ~36% win rate, ~0.6 trades/week. v4.0 (score>=70, 2.2xATR stop, 2R TP) scored +0.04R and was REJECTED. A 2nd eval slot
  doubles trades but cuts expectancy to ~+0.33R — not enabled.
- Sizing & Position Limits:
  - Evaluation Account: `RISK_PCT_EVAL = 0.40%` ($40 on $10K), `MAX_POSITIONS_EVAL = 1` position hard cap.
  - Funded Account: `RISK_PCT_FUNDED = 0.50%` ($25 on $5K), `MAX_POSITIONS = 3`, max 2 per correlation cluster.
  - Sized down as total loss grows (floor 50%).
- Protection & Compliance Safeguards:
  - **Cross-Account De-Dup (`global_held`)**: Live position registry across all accounts plus intraday entries; no two accounts can hold or enter the same coin.
  - **Qualifying Trading Day Gate**: Evaluation accounts with < 5 trading days skip breakouts where notional < 5.2% of initial ($520 on $10K) so positions are never wasted on non-counting days.
  - **Effective Margin Floor**: Entry margin preview is floored at `max(preview_im, notional)` to guard against 1x leverage reporting zero margin.
  - **Emergency Exposure Trimmer**: `reduce_exposure()` automatically force-closes the largest position if total margin exceeds 18% of initial, trimming it down to 15%.
  - **Daily-DD Give-Back Shield**: Keeps total stop risk <= 70% of daily limit measured from 00:00 UTC equity; Rule B kill switch flattens and pauses at 2% intraday give-back; emergency brake flattens at 75% of daily limit.
  - **Keep-Alive**: Automatic round trip at 26 days without a closed trade to prevent the 30-day inactivity account closure.
- Rule: Do NOT raise evaluation risk above 0.40% or funded risk above 0.50% without comprehensive out-of-sample backtesting that includes daily drawdown constraints.
