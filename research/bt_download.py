"""Download 4H spot klines from Binance public market-data mirror (no auth, read-only).
Used ONLY for offline backtest research. Saves CSV per symbol to scratch/bt_data/."""
import json, os, sys, time, urllib.request

OUT_DIR = r"C:\Users\oegar\AppData\Local\hermes\cache\scratch\bt_data"
os.makedirs(OUT_DIR, exist_ok=True)
BASE = "https://data-api.binance.vision/api/v3/klines"
SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", "AVAXUSDT",
    "LTCUSDT", "BNBUSDT", "DOTUSDT", "ARBUSDT", "INJUSDT", "SUIUSDT", "APTUSDT",
    "FILUSDT", "ATOMUSDT", "AAVEUSDT", "UNIUSDT", "TRXUSDT", "ETCUSDT", "BCHUSDT",
    "XLMUSDT", "HBARUSDT", "OPUSDT", "TIAUSDT", "SEIUSDT", "WLDUSDT", "PEPEUSDT",
    "WIFUSDT", "ORDIUSDT", "JUPUSDT", "ENAUSDT", "TONUSDT", "NEARUSDT", "LINKUSDT",
]
INTERVAL = "4h"
START_MS = int(time.mktime(time.strptime("2023-07-01", "%Y-%m-%d")) * 1000)


def fetch(symbol, start_ms):
    url = f"{BASE}?symbol={symbol}&interval={INTERVAL}&startTime={start_ms}&limit=1000"
    req = urllib.request.Request(url, headers={"User-Agent": "qt-research/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


for sym in SYMBOLS:
    path = os.path.join(OUT_DIR, f"{sym}_4h.csv")
    rows, start = [], START_MS
    try:
        while True:
            batch = fetch(sym, start)
            if not batch:
                break
            rows.extend(batch)
            last_open = batch[-1][0]
            if len(batch) < 1000:
                break
            start = last_open + 1
            time.sleep(0.15)
    except Exception as e:
        print(f"{sym}: ERROR {e}", flush=True)
        continue
    with open(path, "w", encoding="utf-8") as f:
        f.write("open_time,open,high,low,close,volume\n")
        for k in rows:
            f.write(f"{k[0]},{k[1]},{k[2]},{k[3]},{k[4]},{k[5]}\n")
    first = time.strftime("%Y-%m-%d", time.gmtime(rows[0][0] / 1000)) if rows else "-"
    last = time.strftime("%Y-%m-%d %H:%M", time.gmtime(rows[-1][0] / 1000)) if rows else "-"
    print(f"{sym}: {len(rows)} bars {first} -> {last}", flush=True)
print("DONE")
