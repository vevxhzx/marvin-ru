# -*- coding: utf-8 -*-
"""Перенос правил из agent.py в core/brain/rules/ — поведение 1:1.

Правило: сначала тесты, потом код. Только fresh_db/_client, без записи в data/jarvis.db.
"""
from __future__ import annotations

import asyncio
import os

os.environ.setdefault("ASSISTANT_TEST", "1")


def _rules(text, channel="test"):
    from core.brain import agent
    return agent.rules(text, channel)


def test_memory_remember_forget_about(fresh_db):
    from core.services import memory
    assert memory.enabled() or True
    r = _rules("запомни что у меня кот Барсик", "rx-mem")
    assert r is not None and "запомнил" in r.text.lower()
    r2 = _rules("что ты знаешь обо мне", "rx-mem")
    assert r2 is not None and "барсик" in r2.text.lower()
    r3 = _rules("забудь что у меня кот Барсик", "rx-mem")
    assert r3 is not None and "забыл" in r3.text.lower()


def test_people_add_and_card(fresh_db):
    r = _rules("человек: ТестЛюд, сестра", "rx-people")
    assert r is not None and "тестлюд" in r.text.lower()
    r2 = _rules("что по ТестЛюд", "rx-people")
    assert r2 is not None


def test_orders_summary_and_timer(fresh_db):
    r = _rules("мои заказы", "rx-ord")
    assert r is not None
    r2 = _rules("таймер", "rx-ord")
    assert r2 is not None


def test_edit_move_rename_delete(fresh_db):
    from core.services import tasks
    tasks.add_task("ПолкаТест", None, source="rx-edit")
    r = _rules("переименуй задачу ПолкаТест в ШкафТест", "rx-edit")
    assert r is not None and "шкафтест" in r.text.lower()
    r2 = _rules("удали задачу ШкафТест", "rx-edit")
    assert r2 is not None and "удалена" in r2.text.lower()


def test_fix_and_catchange_chain(fresh_db):
    # трата затем смена категории через «это ...»
    r = _rules("потратил 500 самокат", "rx-fix")
    assert r is not None
    r2 = _rules("это транспорт", "rx-fix")
    assert r2 is not None


def test_undo_asks_what(fresh_db):
    _rules("потратил 100 отмена-тест", "rx-undo")
    r = _rules("отмени", "rx-undo")
    assert r is not None and "отменить" in r.text.lower()


def test_presence_aims_and_status(fresh_db):
    from core.brain import agent
    r = asyncio.run(agent._presence_rules("цель: тест-цель-перенос", "rx-pres"))
    assert r is not None and "цель" in r.text.lower()
    r2 = asyncio.run(agent._presence_rules("что происходит", "rx-pres"))
    assert r2 is not None


def test_old_names_still_importable(fresh_db):
    from core.brain import agent
    for name in ("_memory_rules", "_people_rules", "_orders_rules", "_edit_rules",
                 "_presence_rules", "people_hint", "FIX_RX", "PERSON_Q_RX", "PERSON_ADD_RX"):
        assert hasattr(agent, name), name


def test_package_rules_parity(fresh_db):
    """Пакетные правила дают тот же результат, что agent.rules() на тех же входах."""
    from core.brain import agent
    from core.brain.rules import edit, memory, orders, people

    assert len(memory.RULES) == 1 and len(people.RULES) == 1 and len(orders.RULES) >= 1
    assert len(edit.RULES) >= 5
    # люди: пакет напрямую
    r_pkg = people.RULES[0]("человек: ПакетЛюд, друг", "человек: пакетлюд, друг", "rx-par")
    r_agent = agent.rules("человек: ПакетЛюд, друг", "rx-par2")
    assert (r_pkg is None) == (r_agent is None)
    if r_pkg and r_agent:
        assert r_pkg.actions == r_agent.actions
    # заказы: сводка через пакет и через диспетчер
    o_pkg = orders.RULES[0]("мои заказы", "мои заказы", "rx-par")
    o_agent = agent.rules("мои заказы", "rx-par2")
    assert o_pkg is not None and o_agent is not None
    assert o_pkg.text == o_agent.text and o_pkg.actions == o_agent.actions
    # память: неизвестное «забудь» — одинаковый честный ответ
    m_pkg = memory.RULES[0]("забудь про несуществующий факт хyz", "забудь про несуществующий факт хyz", "rx-par")
    m_agent = agent.rules("забудь про несуществующий факт хyz", "rx-par2")
    assert (m_pkg is None) == (m_agent is None)
    if m_pkg and m_agent:
        assert m_pkg.text == m_agent.text
