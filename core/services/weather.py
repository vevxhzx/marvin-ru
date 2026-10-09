"""Погода: краткий прогноз на день (Open-Meteo — бесплатно, без ключей).

Город — weather.city (по умолчанию Липецк), координаты подбираю через их же
геокодинг и кладу в settings (weather.coords) — дальше без лишних запросов.
Строка прогноза вшивается верхом в утренний новостной дайджест и отдаётся
командой /weather. Выключено — weather.enabled (по умолчанию выкл).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any

import httpx

from ..config import cfg
from ..db import get_setting, set_setting

log = logging.getLogger("jarvis.weather")

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FC_URL = "https://api.open-meteo.com/v1/forecast"

_WMO = {0: "ясно", 1: "почти ясно", 2: "переменная облачность", 3: "пасмурно",
        45: "туман", 48: "туман с изморозью", 51: "лёгкая морось", 53: "морось", 55: "сильная морось",
        56: "ледяная морось", 57: "ледяная морось", 61: "лёгкий дождь", 63: "дождь", 65: "сильный дождь",
        66: "ледяной дождь", 67: "ледяной дождь", 71: "лёгкий снег", 73: "снег", 75: "сильный снег",
        77: "снежная крупа", 80: "ливень", 81: "ливень", 82: "сильный ливень",
        85: "снегопад", 86: "снегопад", 95: "гроза", 96: "гроза с градом", 99: "гроза с градом"}


def _w():
    return getattr(cfg, "weather", None)


def enabled() -> bool:
    w = _w()
    return bool(w and getattr(w, "enabled", False))


def city() -> str:
    w = _w()
    return str(getattr(w, "city", "") or "").strip() or "Липецк"


def _client() -> httpx.AsyncClient:
    kw: dict[str, Any] = {"timeout": 20.0, "trust_env": False, "follow_redirects": True,
                          "headers": {"User-Agent": "MarvinRSS/1.0 (+local assistant)"}}
    tg = str(getattr(cfg.telegram, "proxy", "") or "").strip()
    if tg:
        kw["proxy"] = tg
    return httpx.AsyncClient(**kw)


def coords() -> tuple[float, float] | None:
    """Координаты города: кэш settings → геокодинг → None (погоду пропускаем молча)."""
    try:
        raw = get_setting("weather.coords")
        if raw:
            lat, lon = json.loads(raw)
            return float(lat), float(lon)
    except (ValueError, TypeError):
        pass
    return None


async def resolve_city(name: str) -> tuple[float, float] | None:
    try:
        async with _client() as c:
            r = await c.get(GEO_URL, params={"name": name, "count": 1, "language": "ru"})
            r.raise_for_status()
            res = (r.json().get("results") or [None])[0]
    except Exception as e:
        log.warning("погода: город не нашёлся (%s)", str(e)[:100])
        return None
    if not res:
        return None
    lat, lon = float(res["latitude"]), float(res["longitude"])
    try:
        set_setting("weather.coords", json.dumps([lat, lon]))
    except Exception as e:  # pragma: no cover
        log.warning("погода: не сохранил координаты (%s)", e)
    return lat, lon


def _describe(code: int) -> str:
    return _WMO.get(int(code), "облачно")


async def today() -> str | None:
    """Одна-две строки: сейчас + днём + осадки. None — не настроено или сеть не ответила."""
    if not enabled():
        return None
    latlon = coords() or await resolve_city(city())
    if not latlon:
        return None
    lat, lon = latlon
    try:
        async with _client() as c:
            r = await c.get(FC_URL, params={"latitude": lat, "longitude": lon, "timezone": "auto",
                                            "current": "temperature_2m,weather_code,wind_speed_10m",
                                            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
                                            "forecast_days": 1})
            r.raise_for_status()
            d = r.json()
    except Exception as e:
        log.warning("погода: прогноз не забрался (%s)", str(e)[:100])
        return None
    try:
        cur, day = d["current"], d["daily"]
        now_t = round(float(cur["temperature_2m"]))
        tmin, tmax = round(float(day["temperature_2m_min"][0])), round(float(day["temperature_2m_max"][0]))
        pop = int(day["precipitation_probability_max"][0] or 0)
        wind = round(float(cur.get("wind_speed_10m") or 0))
        what = _describe(int(day["weather_code"][0]))
    except (KeyError, IndexError, ValueError, TypeError) as e:
        log.warning("погода: странный ответ (%s)", e)
        return None
    rain = f", осадки {pop}%" if pop >= 30 else ""
    wind_s = f", ветер {wind} м/с" if wind >= 7 else ""
    return (f"🌤 {city()}: сейчас {now_t:+d}°, днём {tmin:+d}…{tmax:+d}° — {what}{rain}{wind_s} "
            f"· {datetime.now():%d.%m}")
