"""
Offline research backtest (4H, 33 non-blacklisted coins, Jul-2023 -> Oct-2026).
Answers three questions with data instead of opinion:
  1. What did the LIVE v3.1 bot actually do? (klines newest-first => indicators on reversed series)
  2. Does the v3.1 signal stack have an edge even with correct time ordering?
  3. Which robust, a-priori trend system has an out-of-sample edge, and what prop-firm
     pass probability does it give at 0.5 / 0.75 / 1.0% risk?
In-sample: 2023-07-01 .. 2025-06-30   Out-of-sample: 2025-07-01 .. 2026-10-12
Costs: 0.06% taker fee per side + slippage (entry 0.02%, stop 0.05%, tp 0.02%). Gaps fill at the open.
"""
import glob, json, math, os, random, sys
import numpy as np
import pandas as pd

PROJ = r"C:\Users\oegar\OneDrive\Documents\Crypto 2026 - Pips, Coinbase"
sys.path.insert(0, PROJ)
from signal_engine import SignalEngine          # noqa: E402  (exact live engine, for cross-checks)
from technical_analysis import TechnicalAnalyzer  # noqa: E402

DATA = r"C:\Users\oegar\AppData\Local\hermes\cache\scratch\bt_data"
OUT = r"C:\Users\oegar\AppData\Local\hermes\cache\scratch\bt_results"
os.makedirs(OUT, exist_ok=True)
EXCLUDE = {"NEARUSDT", "LINKUSDT", "TONUSDT"}   # blacklist + TON (data gap after 2026-06-30)
SPLIT = pd.Timestamp("2025-07-01", tz="UTC")
FEE, SLIP_IN, SLIP_STOP, SLIP_TP = 0.0006, 0.0002, 0.0005, 0.0002
CLUSTERS = {
    "BTC": {"BTCUSDT", "ORDIUSDT", "BCHUSDT"},
    "ETH": {"ETHUSDT", "ARBUSDT", "OPUSDT", "UNIUSDT", "AAVEUSDT", "ENAUSDT"},
    "SOL": {"SOLUSDT", "JUPUSDT", "WIFUSDT"},
    "MEME": {"PEPEUSDT", "DOGEUSDT"},
}
random.seed(7)
np.random.seed(7)


def cluster_of(sym):
    for g, m in CLUSTERS.items():
        if sym in m:
            return g
    return sym


# ─── data ──────────────────────────────────────────────────────────────────
def load():
    dfs = {}
    for f in sorted(glob.glob(os.path.join(DATA, "*_4h.csv"))):
        sym = os.path.basename(f).split("_")[0]
        if sym in EXCLUDE:
            continue
        df = pd.read_csv(f)
        df["t"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df = df.set_index("t")[["open", "high", "low", "close", "volume"]].astype(float)
        df = df[~df.index.duplicated()].sort_index()
        dfs[sym] = df
    return dfs


def ema(s, n):
    return s.ewm(span=n, adjust=False, min_periods=n).mean()


def rsi_w(c, n=14):
    d = c.diff()
    ag = d.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    al = (-d).clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + ag / al)


def atr_w(df, n=14):
    pc = df["close"].shift(1)
    tr = pd.concat([df["high"] - df["low"], (df["high"] - pc).abs(), (df["low"] - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()


def btc_regime(btc):
    """Daily BTC close vs SMA50 (completed days only), mapped onto 4H bar CLOSE times."""
    daily = btc["close"].resample("1D").last().dropna()
    sma = daily.rolling(50).mean()
    reg = pd.Series(np.where(daily > sma * 1.005, 1, np.where(daily < sma * 0.995, -1, 0)), index=daily.index)
    reg[sma.isna()] = 0
    reg.index = reg.index + pd.Timedelta(days=1)          # known at the day's completion
    close_times = btc.index + pd.Timedelta(hours=4)
    return pd.Series(reg.reindex(close_times, method="ffill").fillna(0).values, index=btc.index)


# ─── trade simulator ────────────────────────────────────────────────────────
def sim(o, h, l, c, atr, i, d, sl, tp, trail, max_i):
    """Enter at open[i]. d=+1 long/-1 short. sl/tp absolute prices from the planned entry ref.
    trail: None | ('ladder',) | ('chand', m) | ('be',)   Returns (R, exit_index, reason)."""
    ref = o[i]
    one_r = abs(ref - sl)
    if one_r <= 0:
        return None
    fill = ref * (1 + SLIP_IN * d)
    hh, ll = h[i], l[i]
    j = i
    while j <= max_i:
        oj, hj, lj, cj = o[j], h[j], l[j], c[j]
        exit_px, why = None, None
        if d > 0:
            if oj <= sl:
                exit_px, why = oj * (1 - SLIP_STOP), "gap"
            elif lj <= sl:
                exit_px, why = sl * (1 - SLIP_STOP), "sl"
            elif tp is not None and hj >= tp:
                exit_px, why = max(tp, oj) * (1 - SLIP_TP), "tp"
        else:
            if oj >= sl:
                exit_px, why = oj * (1 + SLIP_STOP), "gap"
            elif hj >= sl:
                exit_px, why = sl * (1 + SLIP_STOP), "sl"
            elif tp is not None and lj <= tp:
                exit_px, why = min(tp, oj) * (1 + SLIP_TP), "tp"
        if exit_px is not None:
            pnl = (exit_px - fill) * d - FEE * (fill + exit_px)
            return pnl / one_r, j, why
        # end-of-bar stop management (known at the close, applied from next bar)
        hh, ll = max(hh, hj), min(ll, lj)
        if trail:
            r_now = (cj - fill) * d / one_r
            if trail[0] == "ladder":
                if r_now >= 2:
                    new = fill + d * one_r
                elif r_now >= 1:
                    new = fill
                else:
                    new = None
            elif trail[0] == "be":
                new = fill if r_now >= trail[1] else None
            else:  # chandelier
                a = atr[j]
                new = (hh - trail[1] * a) if d > 0 else (ll + trail[1] * a)
                if len(trail) > 2 and r_now >= trail[2]:   # optional breakeven floor
                    new = max(new, fill) if d > 0 else min(new, fill)
            if new is not None and not math.isnan(new):
                sl = max(sl, new) if d > 0 else min(sl, new)
        j += 1
    pnl = (c[max_i] - fill) * d - FEE * (fill + c[max_i])
    return pnl / one_r, max_i, "eod"


# ─── strategy signal builders (vectorised, bar-close decisions) ────────────
def v31_frame(df, reg, reversed_mode=False):
    """v3.1 engine + bot filters. reversed_mode replicates the live bug exactly (see notes)."""
    c, h, l, v = df["close"], df["high"], df["low"], df["volume"]
    e9, e21 = ema(c, 9), ema(c, 21)
    macd = ema(c, 12) - ema(c, 26)
    hist = macd - macd.ewm(span=9, adjust=False, min_periods=9).mean()
    r = rsi_w(c)
    mid, sd = c.rolling(20).mean(), c.rolling(20).std(ddof=0)
    up, lo = mid + 2 * sd, mid - 2 * sd
    conf = pd.DataFrame(index=df.index)
    conf["mr_l"] = np.where((r < 30) & (c <= lo * 1.01), np.minimum(95, 70 + ((30 - r) * 2).fillna(0).astype(int)), -1)
    conf["mr_s"] = np.where((r > 70) & (c >= up * 0.99), np.minimum(95, 70 + ((r - 70) * 2).fillna(0).astype(int)), -1)
    tfc = np.minimum(90, 60 + (hist / c * 1000).abs().fillna(0).astype(int))
    conf["tf_l"] = np.where((e9 > e21) & (hist > 0), tfc, -1)
    conf["tf_s"] = np.where((e9 < e21) & (hist < 0), tfc, -1)
    conf["mo_l"] = np.where((r > 50) & (r < 70) & (hist > 0), np.minimum(85, 55 + (r - 50).fillna(0).astype(int)), -1)
    conf["mo_s"] = np.where((r > 30) & (r < 50) & (hist < 0), np.minimum(85, 55 + (50 - r).fillna(0).astype(int)), -1)
    # engine picks MR, then TF, then Momentum; ties keep the earlier strategy
    mr = conf[["mr_l", "mr_s"]].max(axis=1)
    mr_d = np.where(conf["mr_l"] >= conf["mr_s"], 1, -1)
    tf = conf[["tf_l", "tf_s"]].max(axis=1)
    tf_d = np.where(conf["tf_l"] >= conf["tf_s"], 1, -1)
    mo = conf[["mo_l", "mo_s"]].max(axis=1)
    mo_d = np.where(conf["mo_l"] >= conf["mo_s"], 1, -1)
    stack = np.vstack([mr.values, tf.values, mo.values])
    pick = np.argmax(stack, axis=0)
    best = stack.max(axis=0)
    d = np.choose(pick, [mr_d, tf_d, mo_d])
    is_mom = pick == 2
    sma50 = c.rolling(50).mean()
    trend = np.where(c > sma50 * 1.005, 1, np.where(c < sma50 * 0.995, -1, 0))
    atrp = (h - l).rolling(14).mean() / c
    regv = reg.values
    if reversed_mode:
        # Live bug: the bot passed klines newest-first. For the trend filter it used
        # mean(closes 150..199 bars ago) vs close 199 bars ago; ATR from candles 86..99 bars ago;
        # BTC regime from ~59 days ago. (Signals themselves come from the exact engine sample.)
        trend = np.where(c.shift(199) > c.shift(150).rolling(50).mean() * 1.005, 1,
                         np.where(c.shift(199) < c.shift(150).rolling(50).mean() * 0.995, -1, 0))
        atrp = ((h - l).shift(86).rolling(14).mean()) / c
        regv = pd.Series(regv, index=df.index).shift(59 * 6).fillna(0).values
    sl_pct = np.clip(1.5 * atrp, 0.015, 0.05)
    tp_pct = np.maximum(1.6 * sl_pct, 2.6 * atrp)
    vol_ratio = v / v.shift(1).rolling(19).mean()
    ok = (best >= 60) & ~((trend != 0) & (trend != d)) & ~((regv == -1) & (d == 1))
    score = best * 0.5 + (tp_pct / sl_pct) * 30 + np.where(is_mom, 20, 10) + 20 \
        + np.where(trend == d, 20, np.where(trend == 0, 5, 0)) \
        + np.where(vol_ratio > 1.5, 15, np.where(vol_ratio < 0.5, -10, 0))
    return pd.DataFrame({"ok": ok, "d": d, "sl_pct": sl_pct, "tp_pct": tp_pct, "score": score}, index=df.index)


def donchian_frame(df, reg, n, k, shorts):
    c, h, l = df["close"], df["high"], df["low"]
    e200 = ema(c, 200)
    hh, llow = h.rolling(n).max().shift(1), l.rolling(n).min().shift(1)
    a = atr_w(df)
    long_ok = (c > hh) & (c > e200) & (reg.values != -1)
    short_ok = (c < llow) & (c < e200) & (reg.values == -1) if shorts else pd.Series(False, index=df.index)
    d = np.where(long_ok, 1, np.where(short_ok, -1, 0))
    strength = ((c - e200) / a).abs()
    return pd.DataFrame({"ok": d != 0, "d": d, "atr": a, "k": k, "score": strength}, index=df.index)


def pullback_frame(df, reg):
    c, l, h = df["close"], df["low"], df["high"]
    e20, e50, e200 = ema(c, 20), ema(c, 50), ema(c, 200)
    r = rsi_w(c)
    a = atr_w(df)
    up = (e50 > e200) & (c > e200) & (r.rolling(5).min() < 40) & (c > e20) & (c.shift(1) <= e20.shift(1)) & (reg.values != -1)
    dn = (e50 < e200) & (c < e200) & (r.rolling(5).max() > 60) & (c < e20) & (c.shift(1) >= e20.shift(1)) & (reg.values == -1)
    d = np.where(up, 1, np.where(dn, -1, 0))
    swing_lo, swing_hi = l.rolling(5).min(), h.rolling(5).max()
    return pd.DataFrame({"ok": d != 0, "d": d, "atr": a, "slo": swing_lo, "shi": swing_hi,
                         "score": ((c - e200) / a).abs()}, index=df.index)


# ─── candidate generation: one simulated trade per signal bar ──────────────
def candidates(dfs, regs, kind, params):
    out = []
    for sym, df in dfs.items():
        o, h, l, c = (df[x].values.tolist() for x in ("open", "high", "low", "close"))
        atr = atr_w(df).values.tolist()
        reg = regs[sym]
        if kind == "v31":
            fr = v31_frame(df, reg)
        elif kind == "donch":
            fr = donchian_frame(df, reg, params["n"], params["k"], params["shorts"])
        else:
            fr = pullback_frame(df, reg)
        ok, dd = fr["ok"].values, fr["d"].values
        idx = df.index
        last = len(df) - 1
        start = 210
        for t in range(start, last - 1):
            if not ok[t]:
                continue
            d = int(dd[t])
            i = t + 1
            ref = o[i]
            if kind == "v31":
                slp, tpp = fr["sl_pct"].values[t], fr["tp_pct"].values[t]
                if not (slp > 0):
                    continue
                sl, tp = ref * (1 - d * slp), ref * (1 + d * tpp)
                trail = ("ladder",) if params.get("ladder", True) else None
            elif kind == "donch":
                a = fr["atr"].values[t]
                if not (a > 0):
                    continue
                sl, tp = ref - d * params["k"] * a, None
                trail = ("chand", params["m"]) + ((params["be"],) if params.get("be") else ())
            else:
                a = fr["atr"].values[t]
                if not (a > 0):
                    continue
                raw = (fr["slo"].values[t] - 0.2 * a) if d > 0 else (fr["shi"].values[t] + 0.2 * a)
                dist = min(max(abs(ref - raw), 1.0 * a), 3.0 * a)
                sl = ref - d * dist
                tp = ref + d * params["tpR"] * dist
                trail = ("be", 1.0) if params.get("be") else None
            res = sim(o, h, l, c, atr, i, d, sl, tp, trail, last)
            if res is None:
                continue
            R, j, why = res
            out.append({"sym": sym, "t_sig": idx[t], "t_in": idx[i], "t_out": idx[j], "d": d, "R": R,
                        "why": why, "score": float(fr["score"].values[t]), "cl": cluster_of(sym),
                        "risk_pct_px": abs(ref - sl) / ref})
    return pd.DataFrame(out)


def one_at_a_time(cand):
    """Per-symbol, non-overlapping trades (the raw per-trade edge)."""
    keep = []
    for sym, g in cand.sort_values("t_in").groupby("sym"):
        busy_until = None
        for r in g.itertuples():
            if busy_until is None or r.t_in > busy_until:
                keep.append(r.Index)
                busy_until = r.t_out
    return cand.loc[keep]


def portfolio(cand, max_pos=3, max_cl=2):
    """Greedy, score-ranked selection respecting max positions / cluster / one-per-symbol."""
    cand = cand.sort_values(["t_in", "score"], ascending=[True, False])
    open_tr, taken = [], []
    for r in cand.itertuples():
        open_tr = [x for x in open_tr if x[2] >= r.t_in]       # still open at this entry time
        if len(open_tr) >= max_pos:
            continue
        if any(x[0] == r.sym for x in open_tr):
            continue
        if sum(1 for x in open_tr if x[1] == r.cl) >= max_cl:
            continue
        open_tr.append((r.sym, r.cl, r.t_out))
        taken.append(r.Index)
    return cand.loc[taken]


def stats(tr, label):
    if tr is None or len(tr) == 0:
        return {"label": label, "n": 0}
    R = tr["R"].values
    wins, losses = R[R > 0], R[R <= 0]
    eq = np.cumsum(R)
    dd = (np.maximum.accumulate(np.concatenate([[0], eq])) - np.concatenate([[0], eq])).max()
    months = max(1e-9, (tr["t_out"].max() - tr["t_in"].min()).days / 30.44)
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    return {"label": label, "n": int(len(R)), "win%": round(100 * len(wins) / len(R), 1),
            "expR": round(float(R.mean()), 3), "PF": round(float(pf), 2), "totR": round(float(R.sum()), 1),
            "maxDD_R": round(float(dd), 1), "trades/mo": round(len(R) / months, 1),
            "avgW": round(float(wins.mean()), 2) if len(wins) else 0, "avgL": round(float(losses.mean()), 2) if len(losses) else 0,
            "syms+%": round(100 * float((tr.groupby('sym')['R'].sum() > 0).mean()), 0)}


def split_stats(tr, label):
    a = stats(tr[tr["t_in"] < SPLIT], label + " | IS")
    b = stats(tr[tr["t_in"] >= SPLIT], label + " | OOS")
    return a, b


# ─── exact-engine checks on reversed windows (what the live bot computed) ──
def reversed_engine_sample(dfs, regs, n_samples=2500):
    eng = SignalEngine(TechnicalAnalyzer())
    rows = []
    syms = list(dfs.keys())
    for _ in range(n_samples):
        sym = random.choice(syms)
        df = dfs[sym]
        if len(df) < 420:
            continue
        t = random.randint(400, len(df) - 3)
        closes = df["close"].values[t - 99:t + 1].tolist()       # oldest..newest (correct)
        rev = list(reversed(closes))                              # what the bot fed the engine
        s_rev = eng.score_symbol(f"{sym}-USD", rev)
        s_fwd = eng.score_symbol(f"{sym}-USD", closes)
        rows.append({"sym": sym, "t": t, "rev_d": None if not s_rev else (1 if s_rev.direction == "LONG" else -1),
                     "rev_conf": 0 if not s_rev else s_rev.confidence,
                     "fwd_d": None if not s_fwd else (1 if s_fwd.direction == "LONG" else -1),
                     "fwd_conf": 0 if not s_fwd else s_fwd.confidence})
    return pd.DataFrame(rows)


def main():
    dfs = load()
    btc = dfs["BTCUSDT"]
    reg_btc = btc_regime(btc)
    regs = {s: reg_btc.reindex(df.index, method="ffill").fillna(0) for s, df in dfs.items()}
    print(f"Loaded {len(dfs)} symbols; BTC regime share risk-on/range/risk-off = "
          f"{(reg_btc == 1).mean():.2f}/{(reg_btc == 0).mean():.2f}/{(reg_btc == -1).mean():.2f}", flush=True)
    results = {}

    # (1) exact engine on reversed vs forward windows: agreement + forward-return test
    smp = reversed_engine_sample(dfs, regs)
    both = smp.dropna(subset=["rev_d", "fwd_d"])
    agree = float((both["rev_d"] == both["fwd_d"]).mean())
    fr = []
    for r in smp.itertuples():
        df = dfs[r.sym]
        c0, c6 = df["close"].values[r.t], df["close"].values[min(r.t + 6, len(df) - 1)]
        fr.append((c6 / c0 - 1))
    smp["fwd_ret_24h"] = fr
    def dir_ret(col):
        x = smp.dropna(subset=[col])
        return float((x[col] * x["fwd_ret_24h"]).mean() * 100), int(len(x))
    results["engine_check"] = {"samples": int(len(smp)), "direction_agreement_rev_vs_fwd": round(agree, 3),
                               "rev_signal_mean_24h_dir_return_%": dir_ret("rev_d"),
                               "fwd_signal_mean_24h_dir_return_%": dir_ret("fwd_d")}
    print("ENGINE CHECK:", results["engine_check"], flush=True)

    rows = []
    # (2) v3.1 stack with CORRECT ordering
    c31 = candidates(dfs, regs, "v31", {"ladder": True})
    c31.to_pickle(os.path.join(OUT, "cand_v31.pkl"))
    for lab, tr in (("v31 per-trade", one_at_a_time(c31)), ("v31 portfolio", portfolio(c31))):
        rows.extend(split_stats(tr, lab))
    print("v31 done", flush=True)

    # (3) Donchian trend system grid (a-priori family; small grid)
    for n in (20, 55):
        for k in (2.0, 3.0):
            for m in (3.0, 4.5):
                for shorts in (False, True):
                    p = {"n": n, "k": k, "m": m, "shorts": shorts}
                    cd = candidates(dfs, regs, "donch", p)
                    lab = f"donch n{n} k{k} m{m} sh{int(shorts)}"
                    cd.to_pickle(os.path.join(OUT, f"cand_{lab.replace(' ', '_')}.pkl"))
                    rows.extend(split_stats(one_at_a_time(cd), lab + " per-trade"))
                    rows.extend(split_stats(portfolio(cd), lab + " portfolio"))
            print(f"donch n{n} k{k} done", flush=True)

    # (4) pullback-in-trend grid
    for tpR in (1.5, 2.0, 3.0):
        for be in (False, True):
            p = {"tpR": tpR, "be": be}
            cd = candidates(dfs, regs, "pull", p)
            lab = f"pull tp{tpR} be{int(be)}"
            cd.to_pickle(os.path.join(OUT, f"cand_{lab.replace(' ', '_')}.pkl"))
            rows.extend(split_stats(one_at_a_time(cd), lab + " per-trade"))
            rows.extend(split_stats(portfolio(cd), lab + " portfolio"))
    print("pullback done", flush=True)

    table = pd.DataFrame(rows)
    table.to_csv(os.path.join(OUT, "summary.csv"), index=False)
    with open(os.path.join(OUT, "engine_check.json"), "w") as f:
        json.dump(results, f, indent=1, default=str)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_rows", 500)
    print(table.to_string(index=False))


if __name__ == "__main__":
    main()
