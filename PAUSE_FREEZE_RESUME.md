# How to Pause / Freeze / Resume the Bot (and do a payout)

Everything below is for the Render worker **hyro-bridge-bot**.
The bot checks the `FROZEN_ACCOUNTS` setting every cycle (~10 min) and skips any account listed there.

## Account IDs
| Account | ID to type | Status |
|---|---|---|
| $5K funded | `56AIZX7gmbbJjvBHSYQMER` | FAILED Oct 14 2026 (do not use) |
| $10K One-Step eval | `28xldlj1SuSy25GQWEMm0E` | ACTIVE (only live account) |

---

## 1. Freeze ONE account (the others keep trading)
1. Go to https://dashboard.render.com
2. Click **hyro-bridge-bot**
3. Left menu → **Environment**
4. Add a variable:
   - **Key:** `FROZEN_ACCOUNTS`
   - **Value:** the account ID from the table above
   - To freeze more than one, separate IDs with a comma:
     `56AIZX7gmbbJjvBHSYQMER,28xldlj1SuSy25GQWEMm0E`
5. Click **Save Changes** → **Save and deploy**
6. Wait about 2 minutes (the bot restarts).

**What freezing does:**
- The bot stops opening NEW trades on that account.
- The bot stops moving that account's stop-losses.
- Stop-losses that were already set **stay active** on HyroTrader.
- The other accounts keep trading normally.

**What freezing does NOT do:** it does not close any open positions.
If you want the account flat (for a payout), close its positions yourself in the Hyro terminal first.

---

## 2. Unfreeze (resume) one account
1. Same place → **Environment**
2. Delete the account's ID from `FROZEN_ACCOUNTS`
   - (if it's the only one, delete the whole variable)
3. **Save Changes** → **Save and deploy**

---

## 3. Stop EVERYTHING (all accounts)
1. **hyro-bridge-bot** → **Settings** → **Suspend Service**
2. To start again: **Settings** → **Resume Service**

---

## 4. Payout flow (only ONE account pays; others keep running)
1. In the Hyro terminal: close all positions on that account, cancel any open orders.
2. Freeze that account (steps in section 1).
3. Hyro website → **Payouts** tab → request payout (USDT or USDC).
4. Wait 12–24 hours for the money to arrive.
5. Unfreeze (section 2) — the bot resumes that account.

---

## Q: I closed a trade myself — will the bot buy it right back?
- **On the same 4-hour candle:** no. It already evaluated that coin for that candle and won't repeat it.
- **On a later 4-hour candle:** yes, it CAN re-enter the same coin, if that coin is still
  breaking out (close above the prior 20-candle high, above the 200-EMA) and still ranks in the
  top picks. There is no "never trade this coin again" command — the only true off-switch is
  freezing the whole account.

**Advice:** don't close winners by hand. The bot's profit comes from letting winners run to the
trailing stop. Closing early means you miss the 2–3R winners that pay for the losses.

---

## Shortcut
You don't have to click anything. Just message the assistant:
- "freeze the 5K" → freezes the funded account
- "freeze the 10K" → freezes the eval
- "resume the 5K" → unfreezes it
- "stop everything" → suspends the worker
