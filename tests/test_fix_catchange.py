# -*- coding: utf-8 -*-
"""«это еда а не транспорт» — правка категории последней операции без LLM.

Живой баг: фраза уходила в облако, модель отвечала «Поправил: [сумма] · Еда»
(сырые плейсхолдеры анонимайзера), а категория в базе оставалась старой.
Теперь: правило меняет категорию офлайн с настоящими цифрами, а _mark
вычищает скобки-плейсхолдеры из любого ответа как последний рубеж.
"""
import asyncio
import os

os.environ.setdefault("ASSISTANT_TEST", "1")


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


def test_catchange_with_old_category(fresh_db, monkeypatch):
    _offline(monkeypatch)
    from core.services import finance
    r1 = _h("потратил 767 на самокат", "tg")
    assert "add_expense" in r1.actions
    r = _h("это доставка еды а не транспорт", "tg")
    assert "[" not in r.text and "]" not in r.text, r.text
    assert "767" in r.text and "Еда" in r.text, r.text
    tx = finance.last_transaction()
    assert tx.category == "Еда"


def test_catchange_bare_category(fresh_db, monkeypatch):
    _offline(monkeypatch)
    from core.services import finance
    _h("потратил 700 на такси", "tg")
    r = _h("это еда", "tg")
    assert "[" not in r.text and "]" not in r.text, r.text
    assert finance.last_transaction().category == "Еда"


def test_catchange_unknown_category_is_honest(fresh_db, monkeypatch):
    _offline(monkeypatch)
    from core.services import finance
    _h("потратил 700 на такси", "tg")
    r = _h("это фигня какая-то", "tg")
    assert "[" not in r.text and "]" not in r.text, r.text
    assert "фигня" in r.text.lower() or "категор" in r.text.lower(), r.text
    assert finance.last_transaction().category == "Транспорт"


def test_mark_scrubs_anon_placeholders(fresh_db):
    from core.brain.agent import Reply, _mark
    r = _mark(Reply("Поправил: [сумма] · Еда. Остаток -[сумма].", ["update_transaction"], "gemini"))
    for ph in ("[сумма]", "[имя]", "[телефон]", "[email]", "[карта]", "[ключ]", "[скрыто]"):
        assert ph not in r.text, r.text
