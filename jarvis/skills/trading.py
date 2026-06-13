"""Stock-market skills: live quotes, history, and index summary.

Market DATA uses Yahoo Finance's public endpoints — no key, works anywhere
(symbols: AAPL, TSLA; Indian NSE: RELIANCE.NS, ^NSEI for Nifty). Read-only and
safe. ORDER PLACEMENT is not done here: live trading flows through a connected
broker (e.g. the Zerodha MCP tools, surfaced as `mcp.*` skills) and is hard-gated
by the autonomy layer so real money is never moved without approval.
"""
from __future__ import annotations

import httpx

from .base import skill

_UA = {"User-Agent": "Mozilla/5.0 (jarvis)"}
_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
_INDICES = {
    "S&P 500": "^GSPC", "Nasdaq": "^IXIC", "Dow": "^DJI",
    "Nifty 50": "^NSEI", "Sensex": "^BSESN", "FTSE 100": "^FTSE",
    "Bitcoin": "BTC-USD",
}


async def _chart(symbol: str, rng: str = "1d", interval: str = "1d") -> dict:
    async with httpx.AsyncClient(timeout=15, headers=_UA) as client:
        r = await client.get(_CHART.format(sym=symbol),
                             params={"range": rng, "interval": interval})
        r.raise_for_status()
        return r.json()["chart"]["result"][0]


def _fmt_quote(meta: dict) -> str:
    price = meta.get("regularMarketPrice")
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    cur = meta.get("currency", "")
    sym = meta.get("symbol", "?")
    if price is None:
        return f"{sym}: no price"
    chg = (price - prev) if prev else 0.0
    pct = (chg / prev * 100) if prev else 0.0
    arrow = "▲" if chg >= 0 else "▼"
    return (f"{sym}  {price:,.2f} {cur}  {arrow} {chg:+,.2f} ({pct:+.2f}%)  "
            f"[{meta.get('exchangeName', '')}]")


@skill(
    name="stock.quote",
    description="Get the latest price and daily change for a stock/ETF/crypto/index "
    "symbol (e.g. AAPL, TSLA, RELIANCE.NS, ^NSEI, BTC-USD).",
    parameters={"type": "object", "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"]},
    category="trading",
)
async def stock_quote(symbol: str) -> str:
    try:
        data = await _chart(symbol.strip())
        return _fmt_quote(data["meta"])
    except Exception as exc:
        return f"[quote failed for {symbol}: {exc}]"


@skill(
    name="stock.history",
    description="Summarise recent price history for a symbol. range: 1d,5d,1mo,3mo,"
    "6mo,1y,5y. Returns first/last/high/low/return%.",
    parameters={"type": "object", "properties": {
        "symbol": {"type": "string"}, "range": {"type": "string"}},
        "required": ["symbol"]},
    category="trading",
)
async def stock_history(symbol: str, range: str = "1mo") -> str:
    try:
        interval = "1d" if range not in ("1d", "5d") else "5m"
        data = await _chart(symbol.strip(), rng=range, interval=interval)
        closes = [c for c in data["indicators"]["quote"][0]["close"] if c is not None]
        if not closes:
            return f"[no history for {symbol}]"
        first, last = closes[0], closes[-1]
        ret = (last - first) / first * 100 if first else 0.0
        cur = data["meta"].get("currency", "")
        return (f"{symbol} [{range}]  open {first:,.2f} → {last:,.2f} {cur}  "
                f"({ret:+.2f}%)  high {max(closes):,.2f}  low {min(closes):,.2f}")
    except Exception as exc:
        return f"[history failed for {symbol}: {exc}]"


@skill(
    name="stock.market",
    description="Snapshot of major market indices (S&P 500, Nasdaq, Dow, Nifty, "
    "Sensex, FTSE) and Bitcoin.",
    parameters={"type": "object", "properties": {}},
    category="trading",
)
async def stock_market() -> str:
    lines = []
    for label, sym in _INDICES.items():
        try:
            data = await _chart(sym)
            lines.append(f"{label:10s} {_fmt_quote(data['meta'])}")
        except Exception:
            lines.append(f"{label:10s} [unavailable]")
    return "\n".join(lines)
