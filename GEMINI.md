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

## Active Account Portfolio (Updated: Oct 4, 2026 — from user's Cleo screenshots, NO open positions)
> All three HyroTrader accounts are **One-Step** (per account names). Official One-Step rules (hyrotrader.com/trading-rules, verified Oct 4):
> max loss **6% of initial balance, fixed, equity-based (incl. unrealized)** | daily drawdown **4% static**, from start-of-day equity, reset 00:00 UTC |
> **5 minimum trading days** (a day counts only if you CLOSE ≥1 trade with notional ≥5% of initial balance that moved ≥1% of trade value) |
> 40% of profit target per day cap (excess doesn't count; losing days count in full) | account closes after 30 days with no trades.
> ⚠️ Previous notes assumed a 10% floor ($9,000) — WRONG for One-Step. User should confirm floors in the HyroTrader dashboard objectives.
- **5K Funded (xt0ipo8)**: Balance $5,131.54 | Floor $4,700 (buffer $431) | Daily limit $200 | Payout $107.19 RECEIVED on Coinbase ~24h after request → cleared to trade at 0.5% (~$25).
  History: NEAR +$102.56, AVAX −$28.68 (SL), LTC +$60.11, AVAX −$2.46 (closed for payout freeze). Confirm with HyroTrader whether next payout baseline is $5,131.54 or $5,000.
- **10K Challenge (8pbmfu0)**: Balance $10,083.55 | Floor $9,400 | Target $10,400 (needs only +$316.45 ≈ $317!) | AVAX closed +$83.55 on Oct 2 = trading day 1 of 5.
  Needs ≥4 more qualifying trading days. Per-day profit cap = $160 (40% of the $400 target). Plan ~$80/day × 4 days. Easy and safe pass.
- **10K Challenge (pd2x19s)**: Balance $9,604.71 | Floor **$9,400** (buffer only **$204.71**) | Target $11,000 (needs +$1,395.29) | AVAX closed +$50.39 Oct 2.
  Risk ≤ $25–50 per trade (rule 8a). Lowest priority account — protect it, don't chase it. No time limit; trade at least once per 30 days.
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
- **NEAR Protocol**: Stopped out 3+ times across multiple accounts (Sept-Oct 2026). Permanently removed.
- **LINK (Chainlink)**: Stopped out on pd2x19s ($14.06 SL hit). User rejected. Do not propose.
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
