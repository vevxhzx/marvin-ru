# -*- coding: utf-8 -*-
"""Причёска заметок/ссылок не дёргает LLM вечно: счётчик попыток, стоп после 5."""
import asyncio
import os

os.environ.setdefault("ASSISTANT_TEST", "1")


def _mk_note(text="трата"):
    from core.db import Note, session
    with session() as s:
        n = Note(text=text, raw=text, tags="", source="tg", polished=False)
        s.add(n)
        s.commit()
        s.refresh(n)
        return n


def _note(nid):
    from core.db import Note, session
    with session() as s:
        return s.get(Note, nid)


def _ready(monkeypatch):
    from core.services import polish

    async def _yes():
        return True

    monkeypatch.setattr(polish, "_llm_ready", _yes)


def test_failed_polish_increments_tries(fresh_db, monkeypatch):
    from core.services import polish
    _ready(monkeypatch)

    async def _fail(system, user):
        return None

    monkeypatch.setattr(polish, "_llm_json", _fail)
    n = _mk_note()
    assert asyncio.run(polish.polish_pending()) == 0
    assert _note(n.id).polish_tries == 1
    assert not _note(n.id).polished


def test_polish_stops_after_five_tries(fresh_db, monkeypatch):
    from core.services import polish
    from core.db import session
    _ready(monkeypatch)
    calls = []

    async def _fail(system, user):
        calls.append(user)
        return None

    monkeypatch.setattr(polish, "_llm_json", _fail)
    n = _mk_note()
    with session() as s:
        row = s.get(__import__("core.db", fromlist=["Note"]).Note, n.id)
        row.polish_tries = 5
        s.add(row)
        s.commit()
    assert asyncio.run(polish.polish_pending()) == 0
    assert calls == []  # LLM вообще не зовём
    assert _note(n.id).polish_tries == 5


def test_success_sets_polished(fresh_db, monkeypatch):
    from core.services import polish
    _ready(monkeypatch)

    async def _ok(system, user):
        return {"title": "Трата", "text": "Трата.", "tags": ["деньги"]}

    monkeypatch.setattr(polish, "_llm_json", _ok)
    n = _mk_note()
    assert asyncio.run(polish.polish_pending()) == 1
    row = _note(n.id)
    assert row.polished and row.title == "Трата"


def test_link_stops_after_five_tries(fresh_db, monkeypatch):
    from core.db import Link, session
    from core.services import polish
    _ready(monkeypatch)
    calls = []

    async def _fail(system, user):
        calls.append(user)
        return None

    monkeypatch.setattr(polish, "_llm_json", _fail)
    with session() as s:
        link = Link(url="https://example.com/x", title="x", tags="", polished=False)
        link.polish_tries = 5
        s.add(link)
        s.commit()
        lid = link.id
    assert asyncio.run(polish.polish_pending()) == 0
    assert calls == []
    with session() as s:
        assert s.get(Link, lid).polish_tries == 5
