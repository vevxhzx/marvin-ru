# -*- coding: utf-8 -*-
"""RSS-дайджест новостей: разбор RSS/Atom, дайджест, API, планировщик.

Ленты — только из настроек, выключены по умолчанию: без news.enabled ничего
не качается. Сеть во всех тестах подменена фейковым httpx-клиентом.
"""
from __future__ import annotations

import asyncio

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>Тест</title>
<item><title>Релиз Марвина 1.0</title><link>https://example.com/1</link>
<description><![CDATA[<p>Вышел <b>релиз</b> &mdash; качайте смело.</p>]]></description></item>
<item><title>Без ссылки</title><description>пропустить</description></item>
<item><title>Второй заголовок</title><link>https://example.com/2</link><description>Коротко.</description></item>
</channel></rss>"""

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>Атом</title>
<entry><title>Атом-заголовок</title><link href="https://example.com/a"/><summary>Суть в двух словах.</summary></entry>
<entry><title>Без ссылки</title><summary>пропустить</summary></entry>
</feed>"""


class _Resp:
    def __init__(self, content: bytes = b"", status: int = 200):
        self.content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")


class _FakeClient:
    def __init__(self, mapping: dict):
        self._mapping = mapping

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url):
        if url not in self._mapping:
            return _Resp(b"nope", 404)
        return _Resp(self._mapping[url])


def _news(monkeypatch, mapping=None, feeds="Тест | https://example.com/rss"):
    from core.services import news

    monkeypatch.setattr(news, "enabled", lambda: True)
    monkeypatch.setattr(news, "_n",
                        lambda: type("N", (), {"enabled": True, "time": "08:00", "feeds": feeds})())
    monkeypatch.setattr(news, "_client", lambda: _FakeClient(mapping or {}))
    return news


def test_parse_rss_cleans_html():
    from core.services import news

    items = news.parse_feed(RSS.encode(), "тест")
    assert len(items) == 2, "запись без ссылки пропускаем"
    assert items[0]["title"] == "Релиз Марвина 1.0"
    assert "<" not in items[0]["desc"] and "релиз" in items[0]["desc"]
    assert items[0]["link"] == "https://example.com/1"


def test_parse_strips_utm():
    from core.services import news

    assert news._bare_link("https://example.com/a?utm_source=rss&utm_medium=x&x=1") == "https://example.com/a?x=1"


def test_parse_atom():
    from core.services import news

    items = news.parse_feed(ATOM.encode(), "атом")
    assert len(items) == 1 and items[0]["link"] == "https://example.com/a"


def test_parse_broken_xml_is_empty():
    from core.services import news

    assert news.parse_feed(b"<rss><oops", "битая") == []


def test_feed_list_parsing(monkeypatch):
    from core.services import news

    monkeypatch.setattr(news, "_n", lambda: type("N", (), {
        "enabled": True, "time": "", "feeds": "Хабр | https://habr.com/rss\nhttps://example.com/f.xml\n# коммент\nмусор"})())
    feeds = news.feed_list()
    assert feeds[0][0] == "Хабр"
    assert feeds[1][0] == "example.com", "голый URL — имя из адреса"
    assert len(feeds) == 2, "коммент и мусор пропускаем"


def test_digest_and_seen(fresh_db, monkeypatch):
    news = _news(monkeypatch, {"https://example.com/rss": RSS.encode()})
    first = asyncio.run(news.fetch_digest(mark=True))
    assert first["ok"] and first["total"] == 2
    assert "Релиз Марвина 1.0" in first["text"] and "https://example.com/1" in first["text"]
    second = asyncio.run(news.fetch_digest(mark=True))
    assert second["total"] == 0 and "уже показывал" in second["text"], "повторы не шлём"


def test_digest_failed_feed(monkeypatch):
    news = _news(monkeypatch, {})
    res = asyncio.run(news.fetch_digest())
    assert res["ok"] is False and "Тест" in res["errors"]


def test_digest_unknown_topic(monkeypatch):
    news = _news(monkeypatch, {"https://example.com/rss": RSS.encode()})
    res = asyncio.run(news.fetch_digest(topic="спорт"))
    assert res["ok"] is False and "спорт" in res["text"]


def test_api_requires_config(fresh_db, monkeypatch):
    from fastapi.testclient import TestClient

    from core.api.app import app
    from core.services import news

    monkeypatch.setattr(news, "enabled", lambda: False)

    r = TestClient(app, client=("127.0.0.1", 5555), base_url="http://testserver").get("/api/news")
    assert r.status_code == 400, "без лент — подсказка, а не пустота"


def test_api_returns_digest(fresh_db, monkeypatch):
    from fastapi.testclient import TestClient

    from core.api.app import app

    _news(monkeypatch, {"https://example.com/rss": RSS.encode()})
    r = TestClient(app, client=("127.0.0.1", 5555), base_url="http://testserver").get("/api/news")
    assert r.status_code == 200, r.text
    assert r.json()["total"] == 2


def test_scheduler_registers_only_when_on(fresh_db, monkeypatch):
    from core.services import news, scheduler

    async def notify(text, buttons=None):
        pass

    monkeypatch.setattr(news, "enabled", lambda: False)
    assert "news_digest" not in {j.id for j in scheduler.build(notify).get_jobs()}, \
        "когда выключено — задачи нет"
    monkeypatch.setattr(news, "enabled", lambda: True)
    monkeypatch.setattr(news, "digest_time", lambda: "08:00")
    jobs = {j.id: j for j in scheduler.build(notify).get_jobs()}
    assert "news_digest" in jobs
    cron = {f.name: str(f) for f in jobs["news_digest"].trigger.fields}
    assert (cron["hour"], cron["minute"]) == ("8", "0")


def test_editable_keys():
    from core.config import EDITABLE

    assert EDITABLE["news.enabled"][0] == "bool"
    assert EDITABLE["news.time"][0] == "str"
    assert EDITABLE["news.feeds"][0] == "str"
