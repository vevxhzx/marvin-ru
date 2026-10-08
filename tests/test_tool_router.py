# -*- coding: utf-8 -*-
"""Роутер инструментов: компактные схемы валидны, подбор по фразам — точный.

Ядро + 1–3 группы вместо 46 схем. Проверка по Клодам 18 фразам + моим спискам
болтовни/дел. Реальные логи не трогаю — фраз хватает из золотого набора.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from tests.test_core import fresh_db  # noqa: E402,F401  (autouse-изоляция БД)


def _router():
    from core.tools import router
    return router


def _names(tools):
    return [(t.get("function") or {}).get("name") for t in tools]


def test_compact_matches_backend():
    """Компактные схемы: те же 46 имён, те же параметры и required, что в бэкенде."""
    from core.tools import registry

    router = _router()
    assert set(router.ALL) == set(registry.TOOLS)
    for name, sch in registry.TOOLS.items():
        bp = (sch.get("function") or {}).get("parameters", {}) or {}
        cp = (router.ALL[name].get("function") or {}).get("parameters", {}) or {}
        assert set((bp.get("properties") or {})) == set((cp.get("properties") or {})), name
        assert set(bp.get("required") or []) == set(cp.get("required") or []), name


def test_update_order_status_has_new():
    """Статус new бэкенд принимает (переоткрыть) — в enum он должен быть."""
    router = _router()
    props = router.ALL["update_order"]["function"]["parameters"]["properties"]
    assert "new" in props["status"]["enum"]


# фраза -> инструменты, которые обязаны быть в подборе
CASES = {
    "потратил 450 на такси": ["add_expense"],
    "перенеси встречу с Ваней на пятницу": ["move_event"],
    "добавь задачу сделать правки": ["add_task"],
    "взял заказ ролик для Пятёрочки 25к до пятницы": ["add_order"],
    "пришёл аванс 10к за ролик": ["order_payment"],
    "кто мне должен": ["list_orders", "late_payments"],
    "сколько ушло на еду за неделю": ["spent"],
    "что по Ване": ["person_card"],
    "кинь на доску ролика: первый кадр": ["board_note"],
    "отложил 5000 в подушку": ["save_to_goal"],
    "хватит ли мне денег до зарплаты": ["cash_forecast", "finance_report"],
    "что у меня сегодня": ["agenda", "today_briefing"],
    "найди что я писал про дачу": ["search_notes"],
    "добавь кредит Сбер 300к": ["add_debt"],
    "удали подписку на нетфликс": ["stop_recurring"],
    "запомни у меня кот Барсик": ["remember_fact"],
    "покажи задачи": ["list_tasks"],
    "мои цели": ["list_aims"],
    "отмена": ["undo_last"],
}


@pytest.mark.parametrize("text, want", list(CASES.items()))
def test_router_picks_right_tools(text, want):
    router = _router()
    tools, groups = router.select_tools(text)
    names = _names(tools)
    for w in want:
        assert w in names, f"{text!r}: нет {w} (группы {groups}, всего {len(names)})"
    assert len(tools) <= 19, f"{text!r}: схем {len(tools)} — роутер не ужал"


def test_chitchat_gets_minimum():
    """Болтовня — ядро + запасной минимум, без тематических групп."""
    router = _router()
    for text in ("привет", "объясни как работает кэш", "ну ок"):
        tools, groups = router.select_tools(text)
        assert groups == [] and len(tools) == 6, (text, groups, len(tools))


def test_short_reply_inherits_prev_groups():
    """«на пятницу» после встречи — липнет к календарю прошлого хода."""
    router = _router()
    _, groups = router.select_tools("перенеси встречу на пятницу")
    assert groups == ["calendar"]
    tools, groups2 = router.select_tools("на пятницу", prev_groups=groups)
    assert "move_event" in _names(tools) and groups2 == ["calendar"]


def test_channel_memory_capped():
    """Память групп по каналам не растёт бесконечно."""
    router = _router()
    for i in range(router._LAST_MAX + 5):
        router.remember(f"ch-{i}", ["money"])
    assert len(router._LAST) <= router._LAST_MAX
    assert router.recall("ch-0") == []


def test_size_win_on_typical_phrases():
    """Выигрыш в размере: подбор заметно легче полного набора."""
    router = _router()
    full = len(json.dumps(list(router.ALL.values()), ensure_ascii=False))
    for text in ("потратил 450 на такси", "что у меня сегодня", "привет"):
        tools, _ = router.select_tools(text)
        part = len(json.dumps(tools, ensure_ascii=False))
        assert part <= full * 0.45, (text, part, full)


def test_via_ollama_uses_router_for_business(monkeypatch):
    """Сквозная: «потратил 450 на такси» — компактный подбор с add_expense, не 46 схем."""
    from core.brain import agent, llm

    async def _up(*a, **k):
        return True

    monkeypatch.setattr(llm, "local_available", _up)
    seen: list = []

    async def fake_chat(messages, tools=None, **kw):
        seen.append(tools)
        return {"content": "ок", "tool_calls": []}

    monkeypatch.setattr(agent, "_chat", fake_chat)
    monkeypatch.setattr(agent, "_history", lambda *a, **k: [])
    asyncio.run(agent.via_ollama("потратил 450 на такси", "t-router"))
    assert seen, "модель вообще не позвали"
    names = _names(seen[0] or [])
    assert "add_expense" in names and len(names) <= 19, names
