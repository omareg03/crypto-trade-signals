"""
bt_v40_compare.py - v3.2.3 vs v4.0 head-to-head on the same 4H history (offline, read-only).

v3.2.3: close > Donchian(20) high & > EMA200, BTC regime != risk-off; stop 3.0xATR, chandelier 4.5xATR, no TP.
v4.0  : 5-pillar smart score (vectorised mirror of hyro_bridge.calculate_smart_score, 4H only - the 1H
        -10 penalty is NOT modelled, so v4 scores are optimistic by up to 10); gates MACD/breakout/RVOL;
        stop 2.2xATR, TP 4.4xATR (5.5x if score >= 85), breakeven at +1R then 2.2xATR chandelier.
Entry = next bar open after the signal bar. Costs: 0.06% fee/side, slippage 0.02% in / 0.05% stop / 0.02% TP.
Reports per-signal stats (all signals) and a 1-slot account (eval MAX_POSITIONS_EVAL=1, best score first).
Usage: python research/bt_v40_compare.py [--thr 70,65,60,55,50]
"""
import glob
import math
import os
import sys

import numpy as np
import pandas as pd

DATA = os.getenv("BT_DATA", r"C:\Users\oegar\AppData\Local\hermes\cache\scratch\bt_data")
EXCLUDE = {"TONUSDT"}                       # data gap after 2026-06-30
SPLIT = pd.Timestamp("2025-07-01", tz="UTC")
FEE, SLIP_IN, SLIP_STOP, SLIP_TP = 0.0006, 0.0002, 0.0005, 0.0002
MAX_HOLD = 180                              # bars (30 days) safety cap


def load():
    dfs = {}
    for f in sorted(glob.glob(os.path.join(DATA, "*_4h.csv"))):
        s = os.path.basename(f).split("_")[0]
        if s in EXCLUDE:
            continue
        df = pd.read_csv(f)
        df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        dfs[s] = df[["open", "high", "low", "close", "volume"]].astype(float)
    return dfs


def regime(btc):
    daily = btc["close"].resample("1D").last().dropna()
    sma = daily.rolling(50).mean()
    reg = pd.Series(np.where(daily < sma * 0.995, -1, 1), index=daily.index)
    reg[sma.isna()] = -1
    reg.index = reg.index + pd.Timedelta(days=1)            # known only after the daily close
    return reg


def indicators(df, reg):
    c, h, l, o, v = df["close"], df["high"], df["low"], df["open"], df["volume"]
    pc = c.shift(1)
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
    e20, e50 = c.ewm(span=20, adjust=False).mean(), c.ewm(span=50, adjust=False).mean()
    e200 = c.ewm(span=200, adjust=False, min_periods=200).mean()
    dh = h.rolling(20).max().shift(1)
    line = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    hist = line - line.ewm(span=9, adjust=False).mean()
    up, dn = h.diff(), -l.diff()
    pdm = up.where((up > dn) & (up > 0), 0.0)
    ndm = dn.where((dn > up) & (dn > 0), 0.0)
    trs = tr.ewm(alpha=1 / 14, adjust=False).mean()
    pdi = 100 * pdm.ewm(alpha=1 / 14, adjust=False).mean() / trs
    ndi = 100 * ndm.ewm(alpha=1 / 14, adjust=False).mean() / trs
    adx = (100 * (pdi - ndi).abs() / (pdi + ndi)).ewm(alpha=1 / 14, adjust=False).mean()
    rvol = v / v.rolling(20).mean().shift(1)
    rng = (h - l).replace(0, np.nan)
    body, wick = (c - o) / rng, (h - c) / rng
    cl01 = lambda x: x.clip(0, 1)
    g_macd = (hist > 0) & (hist > hist.shift(1)) & (hist.shift(1) > hist.shift(2))
    p1 = np.where(g_macd, 10 + 15 * cl01((hist - hist.shift(2)) / 2 / atr / 0.08), 0)
    p2 = np.where(body > 0, 12 * cl01(body / 0.6) + 8 * cl01((0.5 - wick) / 0.3), 0)
    g_brk = (c > dh) & (c > e200)
    stacked = (e20 > e50) & (e50 > e200)
    p3 = np.where(g_brk, 8 + 6 * stacked + 6 * cl01((adx - 15) / 7), 0)
    g_rv = rvol >= 1.25
    p4 = np.where(g_rv, 8 + 12 * cl01((rvol - 1.25) / 1.25), 0)
    p5 = 12 * cl01(atr / c / 0.012) + 3 * (atr > atr.shift(5))
    score = pd.Series(p1 + p2 + p3 + p4 + p5, index=df.index).fillna(0).clip(0, 100)
    regT = reg.reindex(df.index + pd.Timedelta(hours=4), method="ffill").fillna(-1).values
    ok = (regT != -1) & atr.notna().values & e200.notna().values
    return dict(o=o.values, h=h.values, l=l.values, c=c.values, atr=atr.values,
                v32=(g_brk.values & ok), v32_score=((c - e200) / atr).values,
                elig=(g_macd & g_brk & g_rv).values & ok, score=score.values, idx=df.index)


def sim(a, i, mode, score, tp_r=0.0):
    """Enter at open[i+1]. Returns (R, exit_bar) or None."""
    o, h, l, c, atr = a["o"], a["h"], a["l"], a["c"], a["atr"]
    j0 = i + 1
    if j0 >= len(o) or math.isnan(atr[i]):
        return None
    ref, A = o[j0], atr[i]
    k = 3.0 if mode == "v32" else 2.2
    sl = ref - k * A
    tp = (ref + tp_r * k * A if tp_r else None) if mode == "v32" else ref + (5.5 if score >= 85 else 4.4) * A
    one_r = ref - sl
    fill, hh = ref * (1 + SLIP_IN), -1e18
    for j in range(j0, min(len(o), j0 + MAX_HOLD)):
        if o[j] <= sl:
            px = o[j] * (1 - SLIP_STOP)
        elif l[j] <= sl:
            px = sl * (1 - SLIP_STOP)
        elif tp is not None and h[j] >= tp:
            px = max(tp, o[j]) * (1 - SLIP_TP)
        else:
            px = None
        if px is not None:
            return ((px - fill) - FEE * (fill + px)) / one_r, j
        hh = max(hh, h[j])
        if not math.isnan(atr[j]):
            if mode == "v32":
                sl = max(sl, hh - 4.5 * atr[j])
            elif hh >= fill + one_r:
                sl = max(sl, fill, hh - 2.2 * atr[j])
    j = min(len(o), j0 + MAX_HOLD) - 1
    return ((c[j] - fill) - FEE * (fill + c[j])) / one_r, j


def collect(A, mode, thr=70.0, tp_r=0.0):
    rows = []
    for s, a in A.items():
        if mode == "v32":
            idx = np.where(a["v32"])[0]
            sc = a["v32_score"]
        else:
            idx = np.where(a["elig"] & (a["score"] >= thr))[0]
            sc = a["score"]
        for i in idx:
            r = sim(a, i, mode, sc[i], tp_r)
            if r:
                rows.append((a["idx"][i], s, float(sc[i]), r[0], a["idx"][r[1]]))
    return pd.DataFrame(rows, columns=["t", "sym", "score", "R", "t_out"])


def one_slot(tr):
    tr = tr.sort_values(["t", "score"], ascending=[True, False])
    free, keep = pd.Timestamp.min.tz_localize("UTC"), []
    for r in tr.itertuples():
        if r.t >= free:
            keep.append(r.Index)
            free = r.t_out
    return tr.loc[keep]


def k_slot(tr, k):
    """k concurrent positions, one per symbol, best score first."""
    tr = tr.sort_values(["t", "score"], ascending=[True, False])
    open_, keep = [], []
    for r in tr.itertuples():
        open_ = [x for x in open_ if x[1] > r.t]
        if len(open_) >= k or any(x[0] == r.sym for x in open_):
            continue
        open_.append((r.sym, r.t_out))
        keep.append(r.Index)
    return tr.loc[keep]


def stats(tr, weeks):
    if len(tr) == 0:
        return "n=0"
    R = tr["R"].values
    w = R[R > 0]
    return (f"n={len(R):4d} win%={100 * len(w) / len(R):5.1f} expR={R.mean():+.3f} "
            f"avgW={w.mean() if len(w) else 0:.2f} avgL={R[R <= 0].mean() if (R <= 0).any() else 0:+.2f} "
            f"trades/wk={len(R) / weeks:.2f}")


def main():
    thrs = [70.0]
    if "--thr" in sys.argv:
        thrs = [float(x) for x in sys.argv[sys.argv.index("--thr") + 1].split(",")]
    dfs = load()
    reg = regime(dfs["BTCUSDT"])
    A = {s: indicators(df, reg) for s, df in dfs.items()}
    t0 = max(df.index[0] for df in dfs.values() if len(df) > 1000)
    t_all0 = min(df.index[0] for df in dfs.values())
    t1 = max(df.index[-1] for df in dfs.values())
    print(f"coins={len(A)} span {t_all0.date()} -> {t1.date()}")
    runs = [("v3.2.3", "v32", 0)] + [(f"v4.0 thr{t:.0f}", "v4", t) for t in thrs]
    for label, mode, thr in runs:
        tr = collect(A, mode, thr)
        for part, sub in (("ALL", tr), ("IS ", tr[tr.t < SPLIT]), ("OOS", tr[tr.t >= SPLIT])):
            lo = t_all0 if part != "OOS" else SPLIT
            hi = t1 if part != "IS " else SPLIT
            weeks = max(1e-9, (hi - lo).days / 7)
            print(f"{label:12s} {part} signals : {stats(sub, weeks)}")
            print(f"{label:12s} {part} 1-slot  : {stats(one_slot(sub), weeks)}")


def main_v33():
    """v3.3 decision: v3.2.3 rules with an optional far TP (in R) and 1 vs 2 eval slots."""
    dfs = load()
    reg = regime(dfs["BTCUSDT"])
    A = {s: indicators(df, reg) for s, df in dfs.items()}
    t_all0 = min(df.index[0] for df in dfs.values())
    t1 = max(df.index[-1] for df in dfs.values())
    for tp_r in (0.0, 4.0, 6.0, 8.0, 10.0):
        tr = collect(A, "v32", tp_r=tp_r)
        for k in (1, 2):
            for part, sub in (("ALL", tr), ("IS ", tr[tr.t < SPLIT]), ("OOS", tr[tr.t >= SPLIT])):
                lo = t_all0 if part != "OOS" else SPLIT
                hi = t1 if part != "IS " else SPLIT
                weeks = max(1e-9, (hi - lo).days / 7)
                print(f"v32 TP={tp_r:4.1f}R slots={k} {part}: {stats(k_slot(sub, k), weeks)}", flush=True)


if __name__ == "__main__":
    main_v33() if "--v33" in sys.argv else main()
