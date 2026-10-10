# -*- coding: utf-8 -*-
"""Батч 4: люди и память-silent (TDD).

Люди:
- упоминание только ищет (mentions/people_in_text), карточка заводится сама
  лишь по явному «человек:/клиент: …» (или другому явному факту);
- при 2+ похожих людях — вопрос «какой Дима: X или Y?» (clarify),
  молча никого не выбираем и не склеиваем.

Память:
- всё молча, без тостов: suggest_fact-тост выключен по умолчанию
  (suggest_enabled() == False из коробки);
- отклонённые фразы (dismissed-список) по-прежнему не сохраняем.
"""
import asyncio
import json
import os

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


def _offline(monkeypatch):
    from core.brain import llm
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)

    async def no_ollama(force=False):
        return False
    monkeypatch.setattr(llm, "ollama_available", no_ollama)

    async def emb_avail():
        return False
    monkeypatch.setattr(llm, "embed_available", emb_avail)


def _two_dimas():
    from core.services import people
    a = people.add_person("Дима Иванов", kind="friend")
    b = people.add_person("Дима Петров", kind="client")
    return a, b


# ---------------------------------------------------------------- люди
def test_find_candidates_returns_both_namesakes():
    from core.services import people
    a, b = _two_dimas()
    cands = people.find_candidates("Дима")
    assert {c.id for c in cands} == {a.id, b.id}


def test_namesakes_ask_which_not_silent_merge():
    from core.brain.agent import _people_rules
    from core.services import people
    a, b = _two_dimas()
    # упоминание ищет обоих
    found = people.people_in_text("позвони Диме")
    assert {c.id for c in found} == {a.id, b.id}
    # а карточка по короткому имени — вопрос, а не молчаливый выбор первого
    r = _people_rules("кто такой Дима", "web")
    assert r is not None, "ожидался clarify, а не None"
    assert "clarify" in r.actions, (r.actions, r.text)
    assert "person_card" not in r.actions
    assert "какой" in r.text.lower(), r.text
    assert "Дима Иванов" in r.text and "Дима Петров" in r.text, r.text


def test_explicit_client_prefix_creates_card():
    from core.brain.agent import _people_rules
    from core.services import people
    r = _people_rules("клиент: Петя Тестов, магазин", "web")
    assert r is not None and "add_person" in r.actions, (r.actions if r else None, r.text if r else None)
    c = people.find_person("Петя Тестов")
    assert c is not None and c.kind == "client"
    # упоминание находит, дубль не заводится
    found = people.people_in_text("написать Пете Тестову про счёт")
    assert [x.id for x in found] == [c.id]


def test_single_person_card_still_works():
    from core.brain.agent import _people_rules
    from core.services import people
    people.add_person("Лена Соколова", kind="friend")
    r = _people_rules("кто такая Лена", "web")
    assert r is not None and "person_card" in r.actions, (r.actions if r else None, r.text if r else None)
    assert "Лена" in r.text


# ---------------------------------------------------------------- память-silent
def test_suggest_off_by_default():
    from core.services import memory
    assert memory.suggest_enabled() is False


def test_memory_after_reply_silent_no_toast(fresh_db, monkeypatch):
    """Сайту больше не ждём тост: suggest_fact пуст, слот пуст, extract уходит в фон."""
    from core.brain import agent
    from core.services import memory
    _offline(monkeypatch)
    f = memory.add_fact_sync("пельмени люблю с мясом", category="предпочтение")
    assert f is not None

    async def fake_extract(text, msg_id=None):
        return {"added": [f], "updated": [], "remind": None, "via": "cloud"}
    monkeypatch.setattr(memory, "extract", fake_extract)
    calls = []
    monkeypatch.setattr(agent, "_extract_memory_bg", lambda *a, **k: calls.append(a))
    memory.clear_suggest()

    r = agent.Reply("ok")
    asyncio.run(agent._memory_after_reply("а пельмени я люблю с мясом очень", r, "web"))
    assert r.suggest_fact is None
    assert len(calls) == 1
    assert memory.pop_suggest() is None


def test_extract_saves_silently_and_dismissed_kept(fresh_db, monkeypatch):
    """extract пишет факт молча (без pop_suggest), а отклонённую фразу не сохраняет."""
    from core.services import memory
    _offline(monkeypatch)

    async def fake_ask(system, user):
        return {"add": [{"text": "У хозяина кот Барсик", "layer": "long", "category": "быт"}],
                "update": []}, "cloud"
    monkeypatch.setattr(memory, "_ask", fake_ask)
    memory.clear_suggest()
    res = asyncio.run(memory.extract("мой кот Барсик опять разбил вазу, третий раз за неделю"))
    assert len(res["added"]) == 1
    assert memory.pop_suggest() is None  # тоста нет — факт уже молча записан
    assert memory.find_fact("кот Барсик") is not None

    # dismissed-список жив: «нет» — и фраза больше не сохраняется
    assert memory.dismiss(None, "У хозяина кот Барсик") is True
    res2 = asyncio.run(memory.extract("мой кот Барсик опять разбил вазу, третий раз за неделю"))
    assert res2["added"] == []


def test_injector_silent_when_suggest_off(monkeypatch):
    """SuggestInjector при выключенных предложениях ничего не вшивает."""
    from core.api.routers import chat as chat_router
    from core.services import memory
    monkeypatch.setattr(memory, "suggest_enabled", lambda: False)
    memory.clear_suggest()
    memory.set_suggest({"text": "пельмени люблю"}, "web")
    msgs = [
        {"type": "http.response.start", "status": 200,
         "headers": [(b"content-type", b"application/json")]},
        {"type": "http.response.body", "body": b'{"text": "ok"}'},
    ]
    out = chat_router._patch_json(msgs)
    body = b"".join(m["body"] for m in out if m["type"] == "http.response.body")
    assert "suggest_fact" not in json.loads(body)
    memory.clear_suggest()
