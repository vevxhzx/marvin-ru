# -*- coding: utf-8 -*-
"""Ночной разбор важности: нейронка помечает ядром устойчивое (предпочтения,
люди, здоровье) — такое не гаснет никогда. Только добавляет, чужое не трогает.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from tests.test_core import fresh_db  # noqa: E402,F401  (autouse-изоляция БД)


def _brain(monkeypatch, answer):
    from core.brain import llm
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)

    async def fake_cloud_chat(system, user, history=None, **kw):
        return answer(user) if callable(answer) else answer
    monkeypatch.setattr(llm, "cloud_chat", fake_cloud_chat)

    async def no_ollama(force=False):
        return False
    monkeypatch.setattr(llm, "ollama_available", no_ollama)


def _facts():
    from core import db
    with db.session() as s:
        from sqlmodel import select
        return {f.id: f for f in s.exec(select(db.Fact)).all()}


def test_importance_marks_stable_facts(monkeypatch):
    """«Отвечай сухо» и «мама» — в ядро; «простудился» — нет."""
    from core.services import memory

    _brain(monkeypatch, lambda u: json.dumps({"core": [
        int(l.split("]")[0][1:]) for l in u.splitlines()
        if "сухо" in l or "мама" in l.lower()]}))
    a = asyncio.run(memory.add_fact("Любит, когда отвечают сухо и коротко", layer="long"))
    b = asyncio.run(memory.add_fact("Мама живёт в Казани", layer="long"))
    c = asyncio.run(memory.add_fact("Простудился, лечится дома", layer="long"))
    assert asyncio.run(memory.review_importance()) == 2
    by = _facts()
    assert by[a.id].core and by[b.id].core and not by[c.id].core


def test_importance_respects_core_cap(monkeypatch):
    """Ядро не больше CORE_MAX: лишних не берём, старое ядро не двигаем."""
    from core import db
    from core.services import memory

    _brain(monkeypatch, lambda u: json.dumps({"core": [
        int(l.split("]")[0][1:]) for l in u.splitlines() if l.startswith("[")]}))
    ids = [asyncio.run(memory.add_fact(f"Факт {i}", layer="long")).id for i in range(10)]
    assert asyncio.run(memory.review_importance()) == memory.CORE_MAX
    by = _facts()
    assert sum(1 for f in by.values() if f.core) == memory.CORE_MAX
    # второй проход при полном ядре — ничего не делает
    assert asyncio.run(memory.review_importance()) == 0


def test_importance_ignores_junk_and_archive(monkeypatch):
    """Мусор в ответе и архивные факты — мимо."""
    from core import db
    from core.services import memory

    _brain(monkeypatch, '{"core": ["xx", 999999]}')
    a = asyncio.run(memory.add_fact("Любит чай", layer="long"))
    assert asyncio.run(memory.review_importance()) == 0
    assert not _facts()[a.id].core


def test_nightly_includes_review(monkeypatch):
    """Разбор идёт внутри nightly() — отдельную schedule-кнопку не заводим."""
    from core.services import memory

    _brain(monkeypatch, lambda u: json.dumps({"core": [
        int(l.split("]")[0][1:]) for l in u.splitlines() if "вечер" in l]}))
    a = asyncio.run(memory.add_fact("Гуляет по вечерам у дома", layer="long"))
    res = asyncio.run(memory.nightly())
    assert set(res) == {"promoted", "archived"}   # форму ответа не расширяем
    from core import db
    with db.session() as s:
        assert s.get(db.Fact, a.id).core is True
