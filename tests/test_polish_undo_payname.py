# -*- coding: utf-8 -*-
"""Отмена — глобальная с пометкой канала; pay_ask понимает имена заказов.
TDD: сначала красные."""
import asyncio
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

from tests.test_core import fresh_db  # noqa: F401  (временная БД)


def _offline(monkeypatch):
    from core.brain import llm

    async def _no_false(*a, **k):
        return False

    async def _no_none(*a, **k):
        return None

    async def _no_empty(*a, **k):
        return ""

    monkeypatch.setattr(llm, "ollama_available", _no_false)
    monkeypatch.setattr(llm, "embed_available", _no_false)
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(llm, "ollama_chat", _no_none)
    monkeypatch.setattr(llm, "cloud_chat", _no_none)
    monkeypatch.setattr(llm, "small_chat", _no_empty)


def _h(text, ch="tg"):
    from core.brain import agent
    return asyncio.run(agent.handle(text, ch))


def test_undo_other_channel_asks_globally(monkeypatch):
    """Трата в одном канале, «отмени» в другом — спрашивает про неё, а не отфутболивает."""
    _offline(monkeypatch)
    from core.services import finance
    r1 = _h("потратил 700 на такси", "web")
    assert "add_expense" in r1.actions
    r2 = _h("отмени", "tg")
    assert "clarify" in r2.actions
    assert "700" in r2.text and "другом" in r2.text.lower()
    r3 = _h("да", "tg")
    assert "undo" in r3.actions
    assert finance.list_transactions(30, 100) == []


def test_undo_truly_nothing(monkeypatch):
    _offline(monkeypatch)
    r = _h("отмени", "tg")
    assert "нечего" in r.text


def _make_order(title="Кот прод"):
    from core.services import orders
    return orders.add_order(title, price=10_000)


def test_pay_ask_accepts_order_name(monkeypatch):
    """«это заказ кот прод» после вопроса про аванс — пишет оплату, а не теряет её."""
    _offline(monkeypatch)
    _make_order()
    r1 = _h("пришёл аванс 10000 за ролик", "tg")
    assert "clarify" in r1.actions
    r2 = _h("это заказ кот прод", "tg")
    assert "order_payment" in r2.actions
    assert "10 000" in r2.text.replace(" ", " ")


def test_pay_ask_accepts_bare_name(monkeypatch):
    _offline(monkeypatch)
    _make_order()
    _h("пришёл аванс 5000 за ролик", "tg")
    r2 = _h("кот прод", "tg")
    assert "order_payment" in r2.actions


def test_pay_ask_unknown_name_is_honest(monkeypatch):
    _offline(monkeypatch)
    _make_order()
    _h("пришёл аванс 5000 за ролик", "tg")
    r2 = _h("это заказ нечто", "tg")
    assert "не нашёл" in r2.text
    from core.services import orders
    assert orders.payments_for(1) == [] or all(p.amount != 5000 for p in orders.payments_for(1))
