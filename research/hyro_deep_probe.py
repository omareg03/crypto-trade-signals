"""Read-only deep probe of HyroTrader accounts (positions, orders, trades, violations).
Never places, cancels, or modifies anything. Token loaded from .env, never printed."""
import asyncio, json, re

ENV_PATH = r"C:\Users\oegar\OneDrive\Documents\Crypto 2026 - Pips, Coinbase\.env"
MCP_URL = "https://mcp-public.hyro.trade/mcp"
OUT = r"C:\Users\oegar\AppData\Local\hermes\cache\scratch\hyro_deep_probe_out.json"

FUNDED, FUNDED_STAGE = "56AIZX7gmbbJjvBHSYQMER", "2lbdrNfS1jjPHyTFmJpASn"
CH10, CH10_STAGE = "28xldlj1SuSy25GQWEMm0E", "3m7cpOuzLV2YhdJgMLuk1Q"
FAILED_STAGE = "AZdLF4n1n9RNRLRXiO0JC"


def load_token():
    with open(ENV_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("HYRO_AGENT_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None


import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client


def extract(result):
    sc = getattr(result, "structuredContent", None)
    if sc:
        return sc
    content = getattr(result, "content", None)
    if content:
        joined = "\n".join(getattr(c, "text", "") or "" for c in content)
        if joined.strip():
            try:
                return json.loads(joined)
            except Exception:
                return joined
    return None


async def call(session, name, args, retries=4):
    d = None
    for _ in range(retries):
        d = extract(await session.call_tool(name, args))
        if isinstance(d, str) and ("429" in d or "rate-limit" in d.lower()):
            m = re.search(r"Retry after (\d+)s", d)
            wait = (int(m.group(1)) + 3) if m else 30
            print(f"  [429 on {name}; sleeping {wait}s]", flush=True)
            await asyncio.sleep(wait)
            continue
        break
    await asyncio.sleep(2.0)
    return d


async def main():
    token = load_token()
    if not token:
        print("NO TOKEN")
        return
    client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=60.0)
    out = {}
    async with streamable_http_client(MCP_URL, http_client=client) as (read, write):
        async with ClientSession(read, write) as session:
            plan = [
                ("funded_positions", "list_positions", {"challengePublicId": FUNDED}),
                ("funded_orders", "list_open_orders", {"challengePublicId": FUNDED}),
                ("funded_metrics", "get_stage_metrics", {"stagePublicId": FUNDED_STAGE}),
                ("funded_trades", "get_stage_trades", {"stagePublicId": FUNDED_STAGE}),
                ("ch10_orders", "list_open_orders", {"challengePublicId": CH10}),
                ("ch10_trades", "get_stage_trades", {"stagePublicId": CH10_STAGE}),
                ("failed_metrics", "get_stage_metrics", {"stagePublicId": FAILED_STAGE}),
                ("failed_trades", "get_stage_trades", {"stagePublicId": FAILED_STAGE}),
                ("btc_ticker", "get_tickers", {"challengePublicId": CH10, "symbol": "BTCUSDT"}),
            ]
            for key, tool, args in plan:
                print(f"-> {key}", flush=True)
                out[key] = await call(session, tool, args)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)
    print("WROTE", OUT)


asyncio.run(main())
