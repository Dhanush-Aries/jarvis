"""Free, no-key public live-data skills — makes Jarvis broadly knowledgeable.

Every endpoint here is keyless and public. Network/endpoint failures degrade to a
clear "[... failed]" string rather than raising, so one dead API never breaks a
turn. All are read-only and safe.
"""
from __future__ import annotations

from typing import Any

import httpx

from .base import skill

_UA = {"User-Agent": "Mozilla/5.0 (jarvis)"}


async def _get(url: str, params: dict | None = None, headers: dict | None = None,
               timeout: float = 15) -> Any:
    async with httpx.AsyncClient(timeout=timeout, headers={**_UA, **(headers or {})},
                                 follow_redirects=True) as c:
        r = await c.get(url, params=params)
        r.raise_for_status()
        return r.json()


@skill(name="weather.now", category="general",
       description="Current weather + today's range for a place (e.g. 'London', 'Mumbai').",
       parameters={"type": "object", "properties": {"location": {"type": "string"}},
                   "required": ["location"]})
async def weather_now(location: str) -> str:
    try:
        geo = await _get("https://geocoding-api.open-meteo.com/v1/search",
                         {"name": location, "count": 1})
        if not geo.get("results"):
            return f"[no location found: {location}]"
        g = geo["results"][0]
        w = await _get("https://api.open-meteo.com/v1/forecast", {
            "latitude": g["latitude"], "longitude": g["longitude"],
            "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min", "timezone": "auto",
            "forecast_days": 1})
        cur = w["current"]
        d = w["daily"]
        return (f"{g['name']}, {g.get('country', '')}: {cur['temperature_2m']}°C now "
                f"(humidity {cur['relative_humidity_2m']}%, wind "
                f"{cur['wind_speed_10m']} km/h). Today {d['temperature_2m_min'][0]}–"
                f"{d['temperature_2m_max'][0]}°C.")
    except Exception as exc:
        return f"[weather failed: {exc}]"


@skill(name="web.wiki", category="general",
       description="Get a short Wikipedia summary for a topic.",
       parameters={"type": "object", "properties": {"topic": {"type": "string"}},
                   "required": ["topic"]})
async def web_wiki(topic: str) -> str:
    try:
        d = await _get("https://en.wikipedia.org/api/rest_v1/page/summary/"
                       + topic.strip().replace(" ", "_"))
        return d.get("extract") or f"[no summary for {topic}]"
    except Exception as exc:
        return f"[wiki failed: {exc}]"


@skill(name="fx.convert", category="general",
       description="Convert currency at the latest ECB rate, e.g. 100 USD to INR.",
       parameters={"type": "object", "properties": {
           "amount": {"type": "number"}, "from_ccy": {"type": "string"},
           "to_ccy": {"type": "string"}}, "required": ["amount", "from_ccy", "to_ccy"]})
async def fx_convert(amount: float, from_ccy: str, to_ccy: str) -> str:
    try:
        d = await _get("https://api.frankfurter.app/latest", {
            "amount": amount, "from": from_ccy.upper(), "to": to_ccy.upper()})
        val = d["rates"].get(to_ccy.upper())
        return f"{amount} {from_ccy.upper()} = {val:,.2f} {to_ccy.upper()} (ECB {d['date']})"
    except Exception as exc:
        return f"[fx failed: {exc}]"


@skill(name="crypto.price", category="general",
       description="Crypto prices in USD, e.g. 'bitcoin,ethereum,solana'.",
       parameters={"type": "object", "properties": {"ids": {"type": "string"}},
                   "required": ["ids"]})
async def crypto_price(ids: str) -> str:
    try:
        d = await _get("https://api.coingecko.com/api/v3/simple/price", {
            "ids": ids.lower().replace(" ", ""), "vs_currencies": "usd",
            "include_24hr_change": "true"})
        if not d:
            return f"[no crypto data for {ids}]"
        return "  ".join(
            f"{k}: ${v['usd']:,.2f} ({v.get('usd_24h_change', 0):+.1f}%/24h)"
            for k, v in d.items())
    except Exception as exc:
        return f"[crypto failed: {exc}]"


@skill(name="news.top", category="general",
       description="Top Hacker News headlines (tech/startup news).",
       parameters={"type": "object", "properties": {"count": {"type": "integer"}}})
async def news_top(count: int = 5) -> str:
    try:
        ids = await _get("https://hacker-news.firebaseio.com/v0/topstories.json")
        out = []
        for i in ids[: max(1, min(count, 10))]:
            it = await _get(f"https://hacker-news.firebaseio.com/v0/item/{i}.json")
            out.append(f"- {it.get('title', '?')} ({it.get('score', 0)} pts)")
        return "\n".join(out)
    except Exception as exc:
        return f"[news failed: {exc}]"


@skill(name="dict.define", category="general",
       description="Define an English word.",
       parameters={"type": "object", "properties": {"word": {"type": "string"}},
                   "required": ["word"]})
async def dict_define(word: str) -> str:
    try:
        d = await _get("https://api.dictionaryapi.dev/api/v2/entries/en/" + word.strip())
        m = d[0]["meanings"][0]
        return f"{word} ({m['partOfSpeech']}): {m['definitions'][0]['definition']}"
    except Exception as exc:
        return f"[define failed: {exc}]"


@skill(name="net.ip_info", category="general",
       description="Geolocation/ISP info for an IP (blank = this machine's public IP).",
       parameters={"type": "object", "properties": {"ip": {"type": "string"}}})
async def net_ip_info(ip: str = "") -> str:
    try:
        d = await _get(f"http://ip-api.com/json/{ip.strip()}")
        if d.get("status") != "success":
            return f"[ip lookup failed: {d.get('message')}]"
        return (f"{d['query']}: {d.get('city')}, {d.get('regionName')}, {d.get('country')} "
                f"— {d.get('isp')} (lat {d.get('lat')}, lon {d.get('lon')})")
    except Exception as exc:
        return f"[ip_info failed: {exc}]"


@skill(name="fun.joke", category="general", description="Tell a random clean joke.",
       parameters={"type": "object", "properties": {}})
async def fun_joke() -> str:
    try:
        d = await _get("https://icanhazdadjoke.com/", headers={"Accept": "application/json"})
        return d.get("joke", "[no joke]")
    except Exception as exc:
        return f"[joke failed: {exc}]"


@skill(name="country.info", category="general",
       description="Capital, population, currency and region for a country.",
       parameters={"type": "object", "properties": {"name": {"type": "string"}},
                   "required": ["name"]})
async def country_info(name: str) -> str:
    try:
        d = await _get("https://restcountries.com/v3.1/name/" + name.strip(),
                       {"fields": "name,capital,population,currencies,region"})
        if not isinstance(d, list) or not d:
            return f"[no country data for {name}]"
        c = d[0]
        ccy = ", ".join(c.get("currencies", {}).keys())
        return (f"{c['name']['common']}: capital {', '.join(c.get('capital', ['?']))}, "
                f"pop {c.get('population', 0):,}, currency {ccy}, region {c.get('region')}")
    except Exception as exc:
        return f"[country failed: {exc}]"
