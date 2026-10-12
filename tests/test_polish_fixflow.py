# -*- coding: utf-8 -*-
"""Починка догадки голым словом + «самокат» это транспорт. TDD: сначала красные."""
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


async def _evil_order_judge(text, allowed):
    return "order", "test"


def test_amount_first_known_category_ignores_judge(fresh_db, monkeypatch):
    """«767 самокат» — самокат теперь транспорт: судья вообще не зовётся, сразу трата."""
    from core.services import finance, judge
    _offline(monkeypatch)
    monkeypatch.setattr(judge, "decide", _evil_order_judge)
    r = _h("767 самокат", "tg")
    assert "add_expense" in r.actions
    assert "judge" not in r.actions
    txs = finance.list_transactions(30, 100)
    assert len(txs) == 1 and txs[0].amount == 767 and txs[0].category == "Транспорт"


def test_bare_kind_fixes_guess(fresh_db, monkeypatch):
    """Догадка «заказ» + голое «трата» → переложил в трату, заказ откачен, урок записан."""
    from core.services import finance, judge, orders
    _offline(monkeypatch)
    monkeypatch.setattr(judge, "decide", _evil_order_judge)
    r1 = _h("логотип для Кати 8к", "tg")
    assert "add_order" in r1.actions
    assert "если не то" in r1.text
    r2 = _h("трата", "tg")
    assert "add_expense" in r2.actions and "fix" in r2.actions
    assert "Переложил" in r2.text
    assert orders.list_orders(include_closed=True) == []
    txs = finance.list_transactions(30, 100)
    assert len(txs) == 1 and txs[0].amount == 8000


def test_bare_kind_without_guess_is_harmless(fresh_db, monkeypatch):
    """Голое «трата» без свежей догадки — ничего не пишет и не падает."""
    from core.services import finance
    _offline(monkeypatch)
    r = _h("трата", "tg")
    assert "add_expense" not in r.actions
    assert finance.list_transactions(30, 100) == []


def test_explicit_fix_still_works(fresh_db, monkeypatch):
    """«это трата» как раньше чинит."""
    from core.services import finance, judge, orders
    _offline(monkeypatch)
    monkeypatch.setattr(judge, "decide", _evil_order_judge)
    _h("логотип для Кати 8к", "tg")
    r2 = _h("это трата", "tg")
    assert "add_expense" in r2.actions
    assert orders.list_orders(include_closed=True) == []
    assert finance.list_transactions(30, 100)


def test_default_keywords_merge_into_old_db(fresh_db):
    """Старая база без «самокат» в транспорте — merge доклеивает один раз, своё не трогает."""
    from core import db
    from core.services import finance
    with db.session() as s:
        c = s.exec(db.select(db.Category).where(db.Category.name == "Транспорт")).first()
        assert c is not None
        c.keywords = ",".join(k for k in (c.keywords or "").split(",") if k.strip() != "самокат")
        s.add(c)
        s.commit()
        # флаг merge сносим, будто база со старой версии
        old = s.exec(db.select(db.Setting).where(db.Setting.key == "migr.kwmerge1")).first()
        if old:
            s.delete(old)
            s.commit()
    db.init_db()
    assert finance.guess_category("самокат", "expense") == "Транспорт"
    with db.session() as s:
        c = s.exec(db.select(db.Category).where(db.Category.name == "Транспорт")).first()
        n = len([k for k in (c.keywords or "").split(",") if k.strip()])
    db.init_db()
    with db.session() as s:
        c2 = s.exec(db.select(db.Category).where(db.Category.name == "Транспорт")).first()
        assert len([k for k in (c2.keywords or "").split(",") if k.strip()]) == n
