# -*- coding: utf-8 -*-
"""Polish: живой ассистент — сам помнит, сам спрашивает, тихо.
TDD: чек-ин по затухшему health-факту; remind из фразы без команды;
mute глушит повтор; quiet hours молчат; extract молча (без suggest_fact).
"""
import asyncio
import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("ASSISTANT_TEST", "1")

from core import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlalchemy import event
    from sqlmodel import create_engine
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


def _offline_embeds_off(monkeypatch):
    from core.brain import llm
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)

    async def no_ollama(force=False):
        return False
    monkeypatch.setattr(llm, "ollama_available", no_ollama)

    async def no_embed():
        return False
    monkeypatch.setattr(llm, "embed_available", no_embed)


def _day_noon():
    return datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)


def test_health_checkin_stale_fact(fresh_db, monkeypatch):
    """Между делом «неважно чувствую» 3 дня назад → чек-ин «как самочувствие?»."""
    from core.services import memory, proactive
    _offline_embeds_off(monkeypatch)
    monkeypatch.setattr(proactive, "vibe_enabled", lambda: False)
    f = memory.add_fact_sync("Неважно чувствую себя последние дни", layer="short", category="здоровье")
    assert f is not None
    with db.session() as s:
        row = s.get(db.Fact, f.id)
        row.created_at = datetime.now() - timedelta(days=3)
        s.add(row)
        s.commit()
    cands = [c for c in proactive.candidates(_day_noon()) if c["key"].startswith("health:")]
    assert cands, "затухший health-факт 3 дня должен дать чек-ин"
    assert "самочувствие" in (cands[0]["fact"].get("question") or "") or "самочувствие" in cands[0]["text"].lower() or "как" in cands[0]["text"].lower()


def test_remind_from_casual_phrase(fresh_db, monkeypatch):
    """«надо бы маме позвонить» между делом (без команды) → remind-задача."""
    from core.services import memory, tasks
    _offline_embeds_off(monkeypatch)

    async def fake_ask(system, user):
        return {"add": [], "update": [],
                "remind": {"title": "Позвонить маме", "when": None}}, "cloud"
    monkeypatch.setattr(memory, "_ask", fake_ask)
    text = "кстати, надо бы на неделе маме позвонить, а то давно не общались"
    assert memory.worth_extracting(text), "casual-фраза должна идти в extract"
    res = asyncio.run(memory.extract(text))
    assert res["remind"] is not None
    assert any("мам" in t.title.lower() and t.source == "proactive" for t in tasks.list_tasks()), tasks.list_tasks()
    # дубль не плодим
    res2 = asyncio.run(memory.extract(text))
    assert res2["remind"] is None


def test_mute_silences_repeat(fresh_db, monkeypatch):
    """Кнопка «не надо про это» (mute/Lesson) глушит тему даже с новым ключом."""
    from core.services import proactive, tasks
    monkeypatch.setattr(proactive, "vibe_enabled", lambda: False)
    t = tasks.add_task("Разобрать балкон тихо", None, source="test")
    with db.session() as s:
        row = s.get(db.Task, t.id)
        row.created_at = datetime.now() - timedelta(days=8)
        s.add(row)
        s.commit()
    assert any(x["key"].startswith("stale:") for x in proactive.candidates(_day_noon()))
    assert proactive.act("mute", t.id, "stale").startswith("Понял")
    # даже состарив сильнее (новый ключ stale:<id>:<weeks>) — повод не всплывает
    with db.session() as s:
        row = s.get(db.Task, t.id)
        row.created_at = datetime.now() - timedelta(days=20)
        s.add(row)
        s.commit()
    assert all(not x["key"].startswith("stale:") for x in proactive.candidates(_day_noon()))


def test_quiet_hours_silent(fresh_db, monkeypatch):
    """Тихие часы: ночью tick молчит, днём отдаёт."""
    from core.services import proactive, tasks
    from core import config
    monkeypatch.setattr(proactive, "vibe_enabled", lambda: False)

    class N:
        quiet_from = 23
        quiet_to = 8
        proactive_enabled = True
        proactive_per_day = 5
    monkeypatch.setattr(config.cfg, "notifications", N(), raising=False)
    t = tasks.add_task("Дело для тихих часов", None, source="test")
    with db.session() as s:
        row = s.get(db.Task, t.id)
        row.created_at = datetime.now() - timedelta(days=8)
        s.add(row)
        s.commit()
    assert [x for x in proactive.candidates() if x["key"].startswith("stale:")]
    night = datetime.now().replace(hour=3, minute=0, second=0, microsecond=0)
    assert asyncio.run(proactive.tick(now=night, quiet=False)) is None
    day = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    assert asyncio.run(proactive.tick(now=day, quiet=False)) is not None


def test_memory_extract_silent_no_suggest(fresh_db, monkeypatch):
    """Память всё молча: extract пишет факт без suggest_fact/тоста (suggest выключен)."""
    from core.services import memory
    _offline_embeds_off(monkeypatch)
    assert memory.suggest_enabled() is False

    async def fake_ask(system, user):
        return {"add": [{"text": "У хозяина кот Барсик", "layer": "long", "category": "быт"}],
                "update": [], "remind": None}, "cloud"
    monkeypatch.setattr(memory, "_ask", fake_ask)
    memory.clear_suggest()
    res = asyncio.run(memory.extract("мой кот Барсик опять разбил вазу, третий раз за неделю"))
    assert len(res["added"]) == 1
    assert memory.pop_suggest() is None
    assert memory.find_fact("кот Барсик") is not None
