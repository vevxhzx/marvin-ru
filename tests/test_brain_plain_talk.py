# -*- coding: utf-8 -*-
"""Гейт болтовни (_plain_talk): обычной болтовне инструменты не нужны.

Обычный запрос тащит ~19 схем (~2.5k токенов, на 6 ГБ это ~35 с одного чтения).
Болтовне («привет», «что такое инфляция») хватает ask_cloud — остальное срезаем.
Гейт консервативный: любое сомнение — полные инструменты, как раньше.
Ретраи при нужде поднимают полный набор (см. full_now в via_ollama).
"""
from __future__ import annotations

import asyncio

import pytest

from tests.test_core import fresh_db  # noqa: E402,F401  (autouse-изоляция БД)

PLAIN = [
    "привет",
    "ну привет",
    "здравствуйте",
    "добрый вечер",
    "спасибо",
    "спасибо большое",
    "как дела",
    "доброе утро",
    "добрый вечер",
    "как ты",
    "что такое инфляция",
    "расскажи анекдот",
    "кто ты",
    "что ты умеешь",
    "пока",
]

NEEDS_TOOLS = [
    "отмена",
    "удали встречу",
    "покажи задачи",
    "что по задачам на сегодня",
    "потратил 700 на такси",
    "напомни через 20 минут достать стирку",
    "запомни: у меня кот Барсик",
    "открой ютуб",
    "сколько денег осталось",
    "мои цели",
    "что на доске",
    "запиши встречу завтра в 15",
    "привет, мама",
    "распредели это на задачи",
    "хватит ли до зарплаты",
    "мой баланс",
    "идея для ролика про монтаж",
    "мысль: позвонить в банк",
    "что с делами",
    "сколько я потратил за неделю",
    "задача",
    "ну привет, а что у меня завтра",
]


@pytest.mark.parametrize("text", PLAIN)
def test_plain_talk_detected(text):
    from core.brain import agent

    assert agent._plain_talk(text) is True, f"болтовня не распознана: {text!r}"


@pytest.mark.parametrize("text", NEEDS_TOOLS)
def test_tools_kept_where_needed(text):
    from core.brain import agent

    assert agent._plain_talk(text) is False, f"инструменты срезаны зря: {text!r}"


def test_via_ollama_cuts_tools_for_chitchat(monkeypatch):
    """Сквозная: «привет» уходит модели почти без схем (ask_cloud — если облако есть)."""
    from core.brain import agent

    seen: list = []

    async def fake_chat(messages, tools=None, **kw):
        seen.append(tools)
        return {"content": "Привет!", "tool_calls": []}

    monkeypatch.setattr(agent, "_chat", fake_chat)
    monkeypatch.setattr(agent, "_history", lambda *a, **k: [])
    asyncio.run(agent.via_ollama("привет", "t-plain"))
    assert seen, "модель вообще не позвали"
    names = [(t.get("function") or {}).get("name") for t in (seen[0] or [])]
    assert "add_task" not in names and "agenda" not in names and len(names) <= 1, names


def test_via_ollama_keeps_tools_for_business(monkeypatch):
    """Сквозная: «покажи задачи» — полный набор, list_tasks на месте."""
    from core.brain import agent

    seen: list = []

    async def fake_chat(messages, tools=None, **kw):
        seen.append(tools)
        return {"content": "ок", "tool_calls": []}

    monkeypatch.setattr(agent, "_chat", fake_chat)
    monkeypatch.setattr(agent, "_history", lambda *a, **k: [])
    asyncio.run(agent.via_ollama("покажи задачи", "t-biz"))
    assert seen, "модель вообще не позвали"
    names = [(t.get("function") or {}).get("name") for t in (seen[0] or [])]
    assert "list_tasks" in names and len(names) > 10, names
