"""
Walk-forward prop-firm simulator for the v3.2 candidate (4H Donchian trend system).
Mirrors the live bot: closed-bar signals, entry next open, ATR stop, chandelier trail,
max 3 positions / 2 per cluster, open-risk budget vs daily DD, 25% notional cap,
funding + fees + slippage, intrabar worst-case equity for the daily-DD / max-loss rules.
Windows start every 7 days. Challenge: +10% target, 4% daily DD, 6% max loss, 5 trading days.
Funded 5K: 0.5% risk, payout at +5% (80% split), 12-month windows.
"""
import glob, json, math, os, sys
import numpy as np
import pandas as pd

DATA = r"C:\Users\oegar\AppData\Local\hermes\cache\scratch\bt_data"
OUT = r"C:\Users\oegar\AppData\Local\hermes\cache\scratch\bt_results"
EXCLUDE = {"NEARUSDT", "LINKUSDT", "TONUSDT"}
FEE, SLIP_IN, SLIP_STOP, FUND_PER_BAR = 0.0006, 0.0002, 0.0005, 0.00005
CLUSTERS = {"BTC": {"BTCUSDT", "ORDIUSDT", "BCHUSDT"},
            "ETH": {"ETHUSDT", "ARBUSDT", "OPUSDT", "UNIUSDT", "AAVEUSDT", "ENAUSDT"},
            "SOL": {"SOLUSDT", "JUPUSDT", "WIFUSDT"}, "MEME": {"PEPEUSDT", "DOGEUSDT"}}


def cl(s):
    for g, m in CLUSTERS.items():
        if s in m:
            return g
    return s


def load(exclude_extra=()):
    dfs = {}
    for f in sorted(glob.glob(os.path.join(DATA, "*_4h.csv"))):
        s = os.path.basename(f).split("_")[0]
        if s in EXCLUDE or s in exclude_extra:
            continue
        df = pd.read_csv(f)
        df["t"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        dfs[s] = df.set_index("t")[["open", "high", "low", "close", "volume"]].astype(float).sort_index()
    return dfs


def prep(dfs, n, shorts=False):
    btc = dfs["BTCUSDT"]
    daily = btc["close"].resample("1D").last().dropna()
    sma = daily.rolling(50).mean()
    reg = pd.Series(np.where(daily > sma * 1.005, 1, np.where(daily < sma * 0.995, -1, 0)), index=daily.index)
    reg[sma.isna()] = 0
    reg.index = reg.index + pd.Timedelta(days=1)
    idx = sorted(set().union(*[set(d.index) for d in dfs.values()]))
    T = pd.DatetimeIndex(idx)
    regT = pd.Series(reg.reindex(T + pd.Timedelta(hours=4), method="ffill").fillna(0).values, index=T)
    A = {}
    for s, df in dfs.items():
        d = df.reindex(T)
        c, h, l = d["close"], d["high"], d["low"]
        pc = c.shift(1)
        tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1 / 14, adjust=False, min_periods=14).mean()
        e200 = c.ewm(span=200, adjust=False, min_periods=200).mean()
        dh, dl = h.rolling(n).max().shift(1), l.rolling(n).min().shift(1)
        lg = (c > dh) & (c > e200) & (regT != -1)
        sh = (c < dl) & (c < e200) & (regT == -1) if shorts else pd.Series(False, index=T)
        sig = np.where(lg, 1, np.where(sh, -1, 0))
        score = ((c - e200) / atr).abs()
        A[s] = dict(o=d["open"].values, h=h.values, l=l.values, c=c.values, atr=atr.values,
                    sig=sig, score=score.values, cl=cl(s))
    cand = []  # per bar: list of (score, sym, dir)
    for t in range(len(T)):
        row = [(A[s]["score"][t], s, int(A[s]["sig"][t])) for s in A if A[s]["sig"][t] != 0
               and not math.isnan(A[s]["atr"][t])]
        row.sort(reverse=True)
        cand.append(row)
    return T, A, cand


def run(T, A, cand, t0, B, risk, k, m, mode, max_days=365, max_pos=3, max_cl=2,
        budget_frac=0.6, notional_cap=0.25, daily_lim=0.04, max_loss=0.06, target=0.10,
        brake=0.85, streak_n=6, payout_at=0.05, split=0.8, loss_budget=0.7, dd_scale=False):
    """mode 'eval' -> returns dict(result, days, ...); mode 'funded' -> payouts over max_days."""
    bal = B           # realized balance
    pos = []          # dicts
    pending = []      # entries to fill at next open
    day = None
    sod_eq = B
    trade_days = set()
    paid = 0.0
    payouts = 0
    streak = 0
    pause_until = -1
    brake_day = None
    n_tr = wins = 0
    days_real, day_bal0, cap = [], bal, 0.4 * target * B   # Hyro 40%-of-target daily profit cap
    end = min(len(T) - 1, t0 + max_days * 6)
    peak_dd = 0.0
    last_close_t, n_prev = t0, 0
    for t in range(t0, end + 1):
        ts = T[t]
        dkey = ts.date()
        # --- fills at this bar's open
        for (s, d, ref_t) in pending:
            a = A[s]
            o = a["o"][t]
            if math.isnan(o):
                continue
            atr = a["atr"][ref_t]
            dist = k * atr
            if not (dist > 0):
                continue
            eq_now = bal + sum(unreal(p, A, t, "open") for p in pos)
            risk_usd = risk * min(B, eq_now)
            qty = risk_usd / dist
            if qty * o > notional_cap * eq_now:
                qty = notional_cap * eq_now / o
            fill = o * (1 + SLIP_IN * d)
            pos.append(dict(s=s, d=d, fill=fill, stop=o - d * dist, qty=qty, hh=a["h"][t], ll=a["l"][t],
                            cl=a["cl"], t_in=t))
            bal -= FEE * fill * qty
        pending = []
        # --- new day bookkeeping (start-of-day equity at the day's first bar open)
        if dkey != day:
            if day is not None:
                days_real.append(bal - day_bal0)
            day = dkey
            day_bal0 = bal
            sod_eq = bal + sum(unreal(p, A, t, "open") for p in pos)
        # --- exits + intrabar worst-case equity
        worst = bal
        still = []
        for p in pos:
            a = A[p["s"]]
            o, h, l, c = a["o"][t], a["h"][t], a["l"][t], a["c"][t]
            if math.isnan(o):
                still.append(p)
                worst += unreal(p, A, t - 1, "close") if t > 0 else 0
                continue
            d, st = p["d"], p["stop"]
            ex = None
            if d > 0:
                if o <= st:
                    ex = o * (1 - SLIP_STOP)
                elif l <= st:
                    ex = st * (1 - SLIP_STOP)
            else:
                if o >= st:
                    ex = o * (1 + SLIP_STOP)
                elif h >= st:
                    ex = st * (1 + SLIP_STOP)
            if ex is not None:
                pnl = (ex - p["fill"]) * d * p["qty"] - FEE * ex * p["qty"]
                bal += pnl
                worst += pnl
                n_tr += 1
                if pnl > 0:
                    wins += 1
                    streak = 0
                else:
                    streak += 1
                    if streak >= streak_n:
                        pause_until = t + 6
                        streak = 0
                if abs(ex - p["fill"]) / p["fill"] >= 0.01 and p["qty"] * p["fill"] >= 0.05 * B:
                    trade_days.add(dkey)
                continue
            adverse = l if d > 0 else h
            worst += (adverse - p["fill"]) * d * p["qty"]
            bal -= FUND_PER_BAR * c * p["qty"]
            still.append(p)
        pos = still
        dd_day = sod_eq - worst
        loss_tot = B - worst
        peak_dd = max(peak_dd, loss_tot)
        if dd_day > daily_lim * B or loss_tot > max_loss * B:
            return dict(result="fail", days=(t - t0) / 6, paid=paid, payouts=payouts, n=n_tr,
                        why="daily" if dd_day > daily_lim * B else "maxloss", wins=wins)
        # --- bar close: trail, brake, pass/payout checks, new signals
        if n_tr != n_prev:
            last_close_t, n_prev = t, n_tr
        if t - last_close_t > 180:
            return dict(result="fail", days=(t - t0) / 6, paid=paid, payouts=payouts, n=n_tr, why="inactive", wins=wins)
        eq_close = bal + sum(unreal(p, A, t, "close") for p in pos)
        for p in pos:
            a = A[p["s"]]
            if math.isnan(a["c"][t]):
                continue
            p["hh"], p["ll"] = max(p["hh"], a["h"][t]), min(p["ll"], a["l"][t])
            atr = a["atr"][t]
            if p["d"] > 0:
                new = p["hh"] - m * atr
                if new > p["stop"] and new < a["c"][t]:
                    p["stop"] = new
            else:
                new = p["ll"] + m * atr
                if new < p["stop"] and new > a["c"][t]:
                    p["stop"] = new
        if (sod_eq - eq_close) >= brake * daily_lim * B and pos:
            for p in pos:
                a = A[p["s"]]
                cpx = a["c"][t] if not math.isnan(a["c"][t]) else p["fill"]
                ex = cpx * (1 - SLIP_STOP * p["d"])
                bal += (ex - p["fill"]) * p["d"] * p["qty"] - FEE * ex * p["qty"]
                n_tr += 1
            pos = []
            brake_day = dkey
        if mode == "eval" and len(trade_days) >= 5:
            capped = sum(min(x, cap) for x in days_real) + min(bal - day_bal0, cap)
            if capped >= target * B:
                return dict(result="pass", days=(t - t0) / 6, n=n_tr, wins=wins, why="", paid=0, payouts=0)
        if mode == "funded" and bal - B >= payout_at * B:
            for p in pos:
                a = A[p["s"]]
                cpx = a["c"][t] if not math.isnan(a["c"][t]) else p["fill"]
                bal += (cpx - p["fill"]) * p["d"] * p["qty"] - FEE * cpx * p["qty"]
            pos = []
            if bal - B >= 100:
                paid += split * (bal - B)
                payouts += 1
            bal = B
            pause_until = t + 6
            continue
        # new entries (signals known at this close -> fill next open)
        if t >= pause_until and brake_day != dkey:
            open_syms = {p["s"] for p in pos}
            cl_count = {}
            for p in pos:
                cl_count[p["cl"]] = cl_count.get(p["cl"], 0) + 1
            open_risk = sum(max(0.0, (A[p["s"]]["c"][t] - p["stop"]) * p["d"] * p["qty"])
                            for p in pos if not math.isnan(A[p["s"]]["c"][t]))
            cur_dd = max(0.0, sod_eq - eq_close)
            n_open = len(pos)
            for (sc, s, d) in cand[t]:
                if n_open >= max_pos:
                    break
                if s in open_syms or cl_count.get(A[s]["cl"], 0) >= max_cl:
                    continue
                sc_ = max(0.5, 1 - max(0.0, B - eq_close) / (max_loss * B)) if dd_scale else 1.0
                r_usd = risk * min(B, eq_close) * sc_
                if cur_dd + open_risk + r_usd > budget_frac * daily_lim * B:
                    break
                if (B - eq_close) + open_risk + r_usd > loss_budget * max_loss * B:
                    break
                pending.append((s, d, t))
                open_syms.add(s)
                cl_count[A[s]["cl"]] = cl_count.get(A[s]["cl"], 0) + 1
                open_risk += r_usd
                n_open += 1
    return dict(result="timeout" if mode == "eval" else "alive", days=(end - t0) / 6, paid=paid,
                payouts=payouts, n=n_tr, wins=wins, why="", end_bal=bal)


def unreal(p, A, t, which):
    a = A[p["s"]]
    px = a["o"][t] if which == "open" else a["c"][t]
    if math.isnan(px):
        return 0.0
    return (px - p["fill"]) * p["d"] * p["qty"]


def main():
    res = {}
    for n in (20, 55):
        dfs = load()
        T, A, cand = prep(dfs, n, shorts=False)
        first = 260
        starts = list(range(first, len(T) - 6 * 30, 42))  # weekly starts, >=30d of runway
        for risk in (0.005, 0.0075, 0.01):
            out = [run(T, A, cand, t0, 10000, risk, 3.0, 4.5, "eval") for t0 in starts]
            df = pd.DataFrame(out)
            df["start"] = [T[s] for s in starts]
            key = f"EVAL n{n} risk{risk*100:.2f}%"
            done = df[df.result != "timeout"]
            passed = df[df.result == "pass"]
            res[key] = {"windows": len(df), "pass%": round(100 * (df.result == "pass").mean(), 1),
                        "fail%": round(100 * (df.result == "fail").mean(), 1),
                        "timeout%": round(100 * (df.result == "timeout").mean(), 1),
                        "pass%_of_resolved": round(100 * len(passed) / max(1, len(done)), 1),
                        "median_days_to_pass": round(float(passed.days.median()), 0) if len(passed) else None,
                        "p75_days_to_pass": round(float(passed.days.quantile(0.75)), 0) if len(passed) else None,
                        "fail_daily": int((df.why == "daily").sum()), "fail_maxloss": int((df.why == "maxloss").sum()),
                        "OOS_pass%": round(100 * (df[df.start >= pd.Timestamp('2025-07-01', tz='UTC')].result == 'pass').mean(), 1)}
            print(key, res[key], flush=True)
        for risk in (0.005,):
            out = [run(T, A, cand, t0, 5000, risk, 3.0, 4.5, "funded", max_days=365) for t0 in starts
                   if t0 + 365 * 6 < len(T)]
            df = pd.DataFrame(out)
            key = f"FUNDED5K n{n} risk{risk*100:.2f}%"
            res[key] = {"windows": len(df), "survive12m%": round(100 * (df.result == "alive").mean(), 1),
                        "avg_paid_12m_$": round(float(df.paid.mean()), 0),
                        "median_paid_12m_$": round(float(df.paid.median()), 0),
                        "avg_payouts": round(float(df.payouts.mean()), 2),
                        "p10_paid_$": round(float(df.paid.quantile(0.1)), 0),
                        "p90_paid_$": round(float(df.paid.quantile(0.9)), 0)}
            print(key, res[key], flush=True)
    with open(os.path.join(OUT, "walkforward.json"), "w") as f:
        json.dump(res, f, indent=1, default=str)


def main2():
    res = {}
    dfs = load()
    T, A, cand = prep(dfs, 20, shorts=False)
    starts = list(range(260, len(T) - 6 * 30, 42))
    oos = pd.Timestamp("2025-07-01", tz="UTC")
    for k in (3.0, 2.0):
        for risk in (0.0035, 0.005, 0.0075, 0.01):
            out = [run(T, A, cand, t0, 10000, risk, k, 4.5, "eval") for t0 in starts]
            df = pd.DataFrame(out)
            df["start"] = [T[s] for s in starts]
            for lab, sub in (("ALL", df), ("OOS", df[df.start >= oos])):
                p = sub[sub.result == "pass"]
                key = f"EVAL k{k} risk{risk*100:.2f}% {lab}"
                res[key] = {"n": len(sub), "pass%": round(100 * (sub.result == "pass").mean(), 1),
                            "fail%": round(100 * (sub.result == "fail").mean(), 1),
                            "open%": round(100 * (sub.result == "timeout").mean(), 1),
                            "med_days": round(float(p.days.median()), 0) if len(p) else None,
                            "p75_days": round(float(p.days.quantile(.75)), 0) if len(p) else None,
                            "fail_daily": int((sub.why == "daily").sum()), "fail_max": int((sub.why == "maxloss").sum())}
                print(key, res[key], flush=True)
        for risk in (0.0025, 0.005):
            fs = [t0 for t0 in starts if t0 + 365 * 6 < len(T)]
            out = [run(T, A, cand, t0, 5000, risk, k, 4.5, "funded", max_days=365) for t0 in fs]
            df = pd.DataFrame(out)
            key = f"FUNDED5K k{k} risk{risk*100:.2f}%"
            res[key] = {"n": len(df), "survive%": round(100 * (df.result == "alive").mean(), 1),
                        "avg_paid": round(float(df.paid.mean()), 0), "med_paid": round(float(df.paid.median()), 0),
                        "p10": round(float(df.paid.quantile(.1)), 0), "p90": round(float(df.paid.quantile(.9)), 0),
                        "avg_payouts": round(float(df.payouts.mean()), 2)}
            print(key, res[key], flush=True)
    with open(os.path.join(OUT, "walkforward.json"), "w") as f:
        json.dump(res, f, indent=1, default=str)


def main3():
    dfs = load()
    T, A, cand = prep(dfs, 20, shorts=False)
    starts = list(range(260, len(T) - 6 * 30, 42))
    oos = pd.Timestamp("2025-07-01", tz="UTC")
    res = {}
    for risk, lb, dds in ((0.005, 0.7, False), (0.005, 0.9, True), (0.004, 0.9, True), (0.0075, 0.9, True), (0.0035, 0.95, True)):
        out = [run(T, A, cand, t0, 10000, risk, 3.0, 4.5, "eval", loss_budget=lb, dd_scale=dds) for t0 in starts]
        df = pd.DataFrame(out); df["start"] = [T[x] for x in starts]
        for lab, sub in (("ALL", df), ("OOS", df[df.start >= oos])):
            pz = sub[sub.result == "pass"]
            key = f"risk{risk*100:.2f}% lb{lb} ddscale{int(dds)} {lab}"
            res[key] = dict(n=len(sub), pass_=round(100*(sub.result=="pass").mean(),1), fail=round(100*(sub.result=="fail").mean(),1),
                            inactive=int((sub.why=="inactive").sum()), daily=int((sub.why=="daily").sum()), maxloss=int((sub.why=="maxloss").sum()),
                            open_=round(100*(sub.result=="timeout").mean(),1), med_days=(round(float(pz.days.median())) if len(pz) else None),
                            trades_per_month=round(float((sub.n/(sub.days.clip(lower=1)/30.4)).median()),1))
            print(key, res[key], flush=True)
    import json as _j
    _j.dump(res, open(os.path.join(OUT, "walkforward3.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    main3()
