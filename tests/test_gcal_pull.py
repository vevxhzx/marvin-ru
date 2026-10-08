# -*- coding: utf-8 -*-
"""Двусторонний синк Google Календаря: забор создаёт/обновляет/удаляет.

Созданное в Google появляется локально, правки зеркалятся (Google главнее),
удаления зеркалятся тоже. Пуш-эха нет: пишем напрямую в базу, минуя
calendar.add/update (те сами пушат в Google).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from tests.test_core import fresh_db  # noqa: E402,F401  (autouse-изоляция БД)


def _ev(summary, days=1, hour=15, gid=None, status="confirmed", repeat=None):
    start = (datetime.now() + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    item = {"id": gid or summary, "status": status, "summary": summary,
            "start": {"dateTime": start.isoformat()}, "end": {"dateTime": end.isoformat()}}
    if repeat:
        item["recurrence"] = [f"RRULE:{repeat}"]
    return item


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._p = payload or {}

    def raise_for_status(self):
        pass

    def json(self):
        return self._p


class _FakeClient:
    def __init__(self, seen, items):
        self._seen = seen
        self._items = items

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None, params=None):
        self._seen.append(("GET", url))
        return _Resp(200, {"items": self._items})

    async def post(self, url, headers=None, json=None):
        self._seen.append(("POST", url))
        return _Resp(200, {"id": "new-gid"})

    async def put(self, url, headers=None, json=None):
        self._seen.append(("PUT", url))
        return _Resp(200, {"id": "x"})

    async def delete(self, url, headers=None):
        self._seen.append(("DELETE", url))
        return _Resp(204, {})


def _gcal(monkeypatch, seen, items, pull=True):
    from core.services import gcal

    async def fake_token():
        return "tok"
    monkeypatch.setattr(gcal, "_token", fake_token)
    monkeypatch.setattr(gcal, "enabled", lambda: True)
    monkeypatch.setattr(gcal, "connected", lambda: True)
    monkeypatch.setattr(gcal, "_g", lambda: type("G", (), {"pull": pull})())
    monkeypatch.setattr(gcal, "_client", lambda timeout=20: _FakeClient(seen, items))
    return gcal


def _by_gid():
    from core import db
    from sqlmodel import select
    with db.session() as s:
        return {e.google_id: e for e in s.exec(select(db.Event)).all()}


def test_pull_creates_new(monkeypatch):
    gcal = _gcal(monkeypatch, [], [_ev("Стоматолог", days=2)])
    res = asyncio.run(gcal.pull())
    assert res["ok"] and res["created"] == 1
    evs = _by_gid()
    assert "Стоматолог" in evs and evs["Стоматолог"].source == "gcal"


def test_pull_updates_changed_google_wins(monkeypatch):
    from core.services import calendar

    seen: list = []
    gcal = _gcal(monkeypatch, seen, [])
    ev = calendar.add_event("Встреча", datetime.now() + timedelta(days=2), source="web")
    # привязываем как запушенное
    from core import db
    with db.session() as s:
        row = s.get(db.Event, ev.id)
        row.google_id = "g1"
        s.add(row); s.commit()
    seen.clear()
    gcal2 = _gcal(monkeypatch, seen, [_ev("Встреча перенесена", days=3, gid="g1")])
    res = asyncio.run(gcal2.pull())
    assert res["updated"] == 1
    assert _by_gid()["g1"].title == "Встреча перенесена"
    # эха нет: забор ничего не отправляет в Google
    assert not [u for m, u in seen if m in ("POST", "PUT")]


def test_pull_skips_unchanged(monkeypatch):
    from core.services import calendar

    gcal = _gcal(monkeypatch, [], [])
    start = (datetime.now() + timedelta(days=2)).replace(hour=15, minute=0, second=0, microsecond=0)
    ev = calendar.add_event("Созвон", start, source="web")
    from core import db
    with db.session() as s:
        row = s.get(db.Event, ev.id)
        row.google_id = "g2"
        s.add(row); s.commit()
    item = _ev("Созвон", days=2, hour=15, gid="g2")
    gcal2 = _gcal(monkeypatch, [], [item])
    res = asyncio.run(gcal2.pull())
    assert res["ok"] and res["updated"] == 0 and res["created"] == 0


def test_pull_mirrors_delete(monkeypatch):
    from core.services import calendar

    gcal = _gcal(monkeypatch, [], [])
    ev = calendar.add_event("Лишнее", datetime.now() + timedelta(days=2), source="gcal")
    from core import db
    with db.session() as s:
        row = s.get(db.Event, ev.id)
        row.google_id = "g3"
        s.add(row); s.commit()
    gcal2 = _gcal(monkeypatch, [], [_ev("Лишнее", gid="g3", status="cancelled")])
    res = asyncio.run(gcal2.pull())
    assert res["deleted"] == 1
    assert "g3" not in _by_gid()


def test_pull_ignores_unknown_cancelled(monkeypatch):
    gcal = _gcal(monkeypatch, [], [_ev("Чужое", gid="gx", status="cancelled")])
    res = asyncio.run(gcal.pull())
    assert res["ok"] and res["deleted"] == 0 and _by_gid() == {}


def test_pull_yearly_rrule(monkeypatch):
    gcal = _gcal(monkeypatch, [], [_ev("День рождения", days=30, gid="g4",
                                        repeat="FREQ=YEARLY")])
    res = asyncio.run(gcal.pull())
    assert res["created"] == 1
    assert _by_gid()["g4"].repeat == "yearly"


def test_pull_disabled_by_default(monkeypatch):
    from core.services import gcal

    async def fake_token():
        return "tok"
    monkeypatch.setattr(gcal, "_token", fake_token)
    monkeypatch.setattr(gcal, "enabled", lambda: True)
    monkeypatch.setattr(gcal, "connected", lambda: True)
    monkeypatch.setattr(gcal, "_g", lambda: type("G", (), {"pull": False})())
    res = asyncio.run(gcal.pull())
    assert res["ok"] is False
