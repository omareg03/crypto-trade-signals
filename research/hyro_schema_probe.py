"""Read-only probe: tool schemas, kline ordering, instrument filter support.
Never places, cancels, or modifies anything. Token is loaded from .env and never printed.
verify=False: Windows truststore recursion bug in httpx2 (same as the bot); read-only probe."""
import asyncio, json, re, time

ENV_PATH = r"C:\Users\oegar\OneDrive\Documents\Crypto 2026 - Pips, Coinbase\.env"
MCP_URL = "https://mcp-public.hyro.trade/mcp"
OUT = r"C:\Users\oegar\AppData\Local\hermes\cache\scratch\hyro_schema_probe_out.json"
CH10 = "28xldlj1SuSy25GQWEMm0E"


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
        try:
            d = extract(await session.call_tool(name, args))
        except Exception as e:  # SSE size errors etc.
            d = f"EXCEPTION: {type(e).__name__}: {e}"
            break
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
    client = httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, verify=False, timeout=60.0)
    out = {"probe_time_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())}
    async with streamable_http_client(MCP_URL, http_client=client) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            out["tools"] = {t.name: {"description": (t.description or "")[:600],
                                     "inputSchema": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None)}
                            for t in tools.tools}
            print("tools:", list(out["tools"].keys()), flush=True)
            out["klines_4h"] = await call(session, "get_klines", {"challengePublicId": CH10, "symbol": "BTCUSDT", "interval": "240", "limit": 5})
            out["klines_1d"] = await call(session, "get_klines", {"challengePublicId": CH10, "symbol": "BTCUSDT", "interval": "D", "limit": 3})
            out["klines_4h_1000"] = await call(session, "get_klines", {"challengePublicId": CH10, "symbol": "ETHUSDT", "interval": "240", "limit": 1000})
            schema = out["tools"].get("get_instruments", {}).get("inputSchema", {})
            props = (schema or {}).get("properties", {})
            print("get_instruments props:", list(props.keys()), flush=True)
            if "symbol" in props:
                out["instr_btc"] = await call(session, "get_instruments", {"challengePublicId": CH10, "symbol": "BTCUSDT"})
                out["instr_1000pepe"] = await call(session, "get_instruments", {"challengePublicId": CH10, "symbol": "1000PEPEUSDT"})
            out["ticker_btc"] = await call(session, "get_tickers", {"challengePublicId": CH10, "symbol": "BTCUSDT"})
    # summarize the long kline response instead of storing it all
    k = out.get("klines_4h_1000")
    if isinstance(k, dict) and isinstance(k.get("list"), list):
        lst = k["list"]
        out["klines_4h_1000"] = {"keys": list(k.keys()), "n": len(lst), "first": lst[:2], "last": lst[-2:]}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1, default=str)
    print("WROTE", OUT)


asyncio.run(main())
