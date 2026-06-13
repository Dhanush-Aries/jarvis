"""More free, no-key public live-data skills — extends Jarvis's knowledge.

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
        ctype = r.headers.get("content-type", "")
        if "json" in ctype:
            return r.json()
        # Some APIs (e.g. adviceslip) return JSON under a text/html content-type.
        body = r.text.lstrip()
        if body[:1] in ("{", "["):
            try:
                return r.json()
            except Exception:
                pass
        return r.text


@skill(name="translate.text", category="general",
       description="Translate text to another language, e.g. to_lang='es'. "
                   "Uses the free MyMemory API.",
       parameters={"type": "object", "properties": {
           "text": {"type": "string"},
           "to_lang": {"type": "string"},
           "from_lang": {"type": "string"}},
                   "required": ["text", "to_lang"]})
async def translate_text(text: str, to_lang: str, from_lang: str = "auto") -> str:
    try:
        src = "Autodetect" if from_lang in ("", "auto") else from_lang
        d = await _get("https://api.mymemory.translated.net/get", {
            "q": text, "langpair": f"{src}|{to_lang}"})
        if isinstance(d, dict):
            out = (d.get("responseData") or {}).get("translatedText")
            if out:
                return out
        return f"[translate: no result for {text!r}]"
    except Exception as exc:
        return f"[translate failed: {exc}]"


@skill(name="geo.locate", category="general",
       description="Geocode a place name to latitude/longitude/country.",
       parameters={"type": "object", "properties": {"place": {"type": "string"}},
                   "required": ["place"]})
async def geo_locate(place: str) -> str:
    try:
        d = await _get("https://geocoding-api.open-meteo.com/v1/search",
                       {"name": place, "count": 1})
        if not d.get("results"):
            return f"[no location found: {place}]"
        g = d["results"][0]
        return (f"{g['name']}, {g.get('admin1', '')} {g.get('country', '')}".strip()
                + f": lat {g['latitude']}, lon {g['longitude']} "
                  f"(timezone {g.get('timezone', '?')})")
    except Exception as exc:
        return f"[geo failed: {exc}]"


@skill(name="time.zone", category="general",
       description="Current local time in a timezone, e.g. 'Asia/Kolkata'.",
       parameters={"type": "object", "properties": {"area": {"type": "string"}},
                   "required": ["area"]})
async def time_zone(area: str) -> str:
    # Robust local fallback first (no network) — worldtimeapi is often flaky.
    from datetime import datetime
    try:
        from zoneinfo import ZoneInfo
        now = datetime.now(ZoneInfo(area))
        return now.strftime(f"{area}: %Y-%m-%d %H:%M:%S %Z (UTC%z)")
    except Exception:
        pass
    try:
        d = await _get(f"https://worldtimeapi.org/api/timezone/{area}")
        if isinstance(d, dict) and d.get("datetime"):
            return (f"{area}: {d['datetime']} "
                    f"(abbr {d.get('abbreviation', '?')})")
        return f"[time: no data for {area}]"
    except Exception as exc:
        return f"[time failed: {exc}]"


def _math_fact(n: int) -> str:
    props = []
    if n < 0:
        props.append("negative")
    if n == 0:
        return "0 is the additive identity — adding it changes nothing."
    if n % 2 == 0:
        props.append("even")
    else:
        props.append("odd")
    a = abs(n)
    if a > 1 and all(a % i for i in range(2, int(a ** 0.5) + 1)):
        props.append("prime")
    r = int(a ** 0.5)
    if r * r == a:
        props.append(f"a perfect square ({r}²)")
    if a > 0 and (a & (a - 1)) == 0:
        props.append("a power of two")
    if a == sum(i for i in range(1, a) if a % i == 0):
        props.append("a perfect number")
    return f"{n} is {', '.join(props)}."


@skill(name="fact.number", category="general",
       description="A fact about a number.",
       parameters={"type": "object", "properties": {"n": {"type": "integer"}},
                   "required": ["n"]})
async def fact_number(n: int) -> str:
    # numbersapi.com is the classic source but is currently down (404). Try it,
    # then fall back to a locally computed mathematical fact (always works).
    try:
        d = await _get(f"http://numbersapi.com/{int(n)}", timeout=6)
        if isinstance(d, str) and d.strip() and "<" not in d[:10]:
            return d.strip()
    except Exception:
        pass
    try:
        return _math_fact(int(n))
    except Exception as exc:
        return f"[number fact failed: {exc}]"


@skill(name="fact.today", category="general",
       description="A historical 'on this day' fact for today's date.",
       parameters={"type": "object", "properties": {}})
async def fact_today() -> str:
    # numbersapi date endpoint is down; use byabbe.se on-this-day instead.
    from datetime import date
    t = date.today()
    try:
        d = await _get(f"https://byabbe.se/on-this-day/{t.month}/{t.day}/events.json")
        evs = d.get("events", []) if isinstance(d, dict) else []
        if evs:
            import random
            e = random.choice(evs)
            return f"On {d.get('date', '')} in {e.get('year')}: {e.get('description')}"
        return "[no on-this-day events]"
    except Exception as exc:
        return f"[today fact failed: {exc}]"


@skill(name="advice.random", category="general",
       description="A random piece of advice.",
       parameters={"type": "object", "properties": {}})
async def advice_random() -> str:
    try:
        d = await _get("https://api.adviceslip.com/advice")
        if isinstance(d, dict):
            return (d.get("slip") or {}).get("advice", "[no advice]")
        return "[no advice]"
    except Exception as exc:
        return f"[advice failed: {exc}]"


@skill(name="github.trending", category="general",
       description="Top GitHub repos by stars (optionally filter by language).",
       parameters={"type": "object", "properties": {"language": {"type": "string"}}})
async def github_trending(language: str = "") -> str:
    try:
        q = "stars:>10000"
        if language.strip():
            q += f" language:{language.strip()}"
        d = await _get("https://api.github.com/search/repositories", {
            "q": q, "sort": "stars", "order": "desc", "per_page": 5},
            headers={"Accept": "application/vnd.github+json"})
        items = d.get("items", []) if isinstance(d, dict) else []
        if not items:
            return "[no repos found]"
        out = []
        for it in items:
            desc = (it.get("description") or "").strip()
            out.append(f"- {it['full_name']} (★{it.get('stargazers_count', 0):,}) {desc}")
        return "\n".join(out)
    except Exception as exc:
        return f"[github failed: {exc}]"


@skill(name="crypto.market", category="general",
       description="Top 5 cryptocurrencies by market cap (USD).",
       parameters={"type": "object", "properties": {}})
async def crypto_market() -> str:
    try:
        d = await _get("https://api.coingecko.com/api/v3/coins/markets", {
            "vs_currency": "usd", "order": "market_cap_desc",
            "per_page": 5, "page": 1})
        if not isinstance(d, list) or not d:
            return "[no market data]"
        out = []
        for c in d:
            out.append(f"{c.get('market_cap_rank', '?')}. {c['name']} "
                       f"(${c['current_price']:,.2f}, "
                       f"mcap ${c.get('market_cap', 0):,}, "
                       f"{c.get('price_change_percentage_24h') or 0:+.1f}%/24h)")
        return "\n".join(out)
    except Exception as exc:
        return f"[crypto market failed: {exc}]"


@skill(name="holiday.next", category="general",
       description="Upcoming public holidays for a country, e.g. 'IN', 'US'.",
       parameters={"type": "object", "properties": {"country_code": {"type": "string"}},
                   "required": ["country_code"]})
async def holiday_next(country_code: str) -> str:
    try:
        d = await _get(
            f"https://date.nager.at/api/v3/NextPublicHolidays/{country_code.upper()}")
        if not isinstance(d, list) or not d:
            return f"[no holidays for {country_code}]"
        out = []
        for h in d[:5]:
            out.append(f"- {h.get('date')}: {h.get('localName')} ({h.get('name')})")
        return "\n".join(out)
    except Exception as exc:
        return f"[holiday failed: {exc}]"


@skill(name="iss.location", category="general",
       description="Current coordinates of the International Space Station.",
       parameters={"type": "object", "properties": {}})
async def iss_location() -> str:
    try:
        d = await _get("http://api.open-notify.org/iss-now.json")
        if isinstance(d, dict) and d.get("iss_position"):
            p = d["iss_position"]
            return f"ISS is at lat {p['latitude']}, lon {p['longitude']} (live)."
    except Exception:
        pass
    try:
        d = await _get("https://api.wheretheiss.at/v1/satellites/25544")
        if isinstance(d, dict) and "latitude" in d:
            return (f"ISS is at lat {d['latitude']}, lon {d['longitude']} "
                    f"(alt {d.get('altitude', '?'):.0f} km, "
                    f"vel {d.get('velocity', '?'):.0f} km/h).")
        return "[no ISS data]"
    except Exception as exc:
        return f"[iss failed: {exc}]"


def register_web2_skills() -> int:
    return 10
