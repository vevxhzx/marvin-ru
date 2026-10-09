# -*- coding: utf-8 -*-
"""Погода: разбор кодов WMO, геокодинг с кэшем, строка прогноза, запись многострочных настроек."""
from __future__ import annotations

import asyncio
import json


class _Resp:
    def __init__(self, payload, status=200):
        self._p = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._p


class _FakeClient:
    def __init__(self, mapping):
        self._m = mapping

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None):
        return _Resp(self._m["geo" if "geocoding" in url else "fc"])


def _weather(monkeypatch, geo=None, fc=None):
    from core.services import weather

    monkeypatch.setattr(weather, "_w", lambda: type("W", (), {"enabled": True, "city": "Липецк"})())
    monkeypatch.setattr(weather, "_client", lambda: _FakeClient({"geo": geo or {}, "fc": fc or {}}))
    return weather


def test_wmo_mapping():
    from core.services import weather

    assert weather._describe(0) == "ясно"
    assert weather._describe(63) == "дождь"
    assert weather._describe(95) == "гроза"
    assert weather._describe(999) == "облачно"


def test_resolve_city_caches(fresh_db, monkeypatch):
    from core.db import get_setting

    w = _weather(monkeypatch, geo={"results": [{"latitude": 52.6, "longitude": 39.6}]})
    assert asyncio.run(w.resolve_city("Липецк")) == (52.6, 39.6)
    assert json.loads(get_setting("weather.coords")) == [52.6, 39.6]


def test_today_format(fresh_db, monkeypatch):
    fc = {"current": {"temperature_2m": 12.4, "weather_code": 63, "wind_speed_10m": 3.0},
          "daily": {"temperature_2m_max": [18.2], "temperature_2m_min": [9.6],
                    "precipitation_probability_max": [70], "weather_code": [63]}}
    w = _weather(monkeypatch, fc=fc)
    monkeypatch.setattr(w, "coords", lambda: (52.6, 39.6))
    txt = asyncio.run(w.today())
    assert txt and "Липецк" in txt and "дождь" in txt and "70%" in txt, txt
    assert "ветер" not in txt, "слабый ветер не упоминаем"


def test_today_off_when_disabled(monkeypatch):
    from core.services import weather

    monkeypatch.setattr(weather, "_w", lambda: type("W", (), {"enabled": False, "city": "Липецк"})())
    assert asyncio.run(weather.today()) is None


def test_write_settings_multiline_roundtrip(tmp_path, monkeypatch):
    """Многострочное значение переживает запись в yaml и читается построчно обратно."""
    import yaml

    from core import config

    f = tmp_path / "cfg.yaml"
    f.write_text("news:\n  enabled: false\n", encoding="utf-8")
    monkeypatch.setattr(config, "_config_file", lambda: f)
    monkeypatch.setattr(config, "_config_src", lambda: f)
    feeds = "Хабр | https://habr.com/ru/rss/all/all/\n3DNews | https://3dnews.ru/news/rss/"
    changed = config.write_settings({"news.enabled": True, "news.feeds": feeds})
    assert "news.feeds" in changed
    raw = yaml.safe_load(f.read_text(encoding="utf-8"))
    assert raw["news"]["feeds"].splitlines() == feeds.splitlines()
    assert raw["news"]["enabled"] is True
    # повторная запись поверх блочного скаляра не плодит хвосты
    config.write_settings({"news.feeds": "Одно | https://example.com/rss"})
    raw2 = yaml.safe_load(f.read_text(encoding="utf-8"))
    assert raw2["news"]["feeds"] == "Одно | https://example.com/rss"


def test_editable_weather_keys():
    from core.config import EDITABLE

    assert EDITABLE["weather.enabled"][0] == "bool"
    assert EDITABLE["weather.city"][0] == "str"
