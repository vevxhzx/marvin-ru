# -*- coding: utf-8 -*-
"""Траты с выбранного счёта + защита от минуса. TDD: сначала красные."""
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


def _mk(monkeypatch):
    _offline(monkeypatch)
    from core.services import finance
    finance.set_balance(finance.main_account_name(), 1_000)
    finance.add_account("ТестКуб", kind="bank", balance=5_000)
    return finance


def test_expense_from_named_account(fresh_db, monkeypatch):
    f = _mk(monkeypatch)
    r = _h("потратил 700 с тесткуба", "tg")
    assert "add_expense" in r.actions
    txs = f.list_transactions(30, 100)
    assert len(txs) == 1 and txs[0].account == "ТестКуб"
    assert next(a for a in f.list_accounts() if a.name == "ТестКуб").balance == 4_300
    assert next(a for a in f.list_accounts() if a.name == f.main_account_name()).balance == 1_000


def test_expense_unknown_account_goes_main(fresh_db, monkeypatch):
    f = _mk(monkeypatch)
    r = _h("потратил 700 с марса", "tg")
    assert "add_expense" in r.actions
    assert f.list_transactions(30, 100)[0].account == f.main_account_name()


def test_expense_category_not_eaten_as_account(fresh_db, monkeypatch):
    """«потратил 700 на такси» — «на такси» категория, а не счёт."""
    f = _mk(monkeypatch)
    r = _h("потратил 700 на такси", "tg")
    assert "add_expense" in r.actions
    tx = f.list_transactions(30, 100)[0]
    assert tx.account == f.main_account_name()
    assert tx.category == "Транспорт"


def test_overdraft_warns_but_writes(fresh_db, monkeypatch):
    f = _mk(monkeypatch)
    r = _h("потратил 6000 с тесткуба", "tg")
    assert "add_expense" in r.actions
    assert "минус" in r.text.lower() or "осторожно" in r.text.lower()
    assert next(a for a in f.list_accounts() if a.name == "ТестКуб").balance == -1_000


def test_overdraft_blocked_by_setting(fresh_db, monkeypatch):
    from core import config
    f = _mk(monkeypatch)
    monkeypatch.setattr(config.cfg, "finance", config._Node({"allow_overdraft": False, "main_account": "Основной", "currency": "RUB"}), raising=False)
    import pytest
    with pytest.raises(Exception, match="не хватает"):
        f.add_transaction(5_001, "expense", "Еда", "тест", account="ТестКуб")
    assert f.list_transactions(30, 100) == []


def test_credit_card_may_go_negative(fresh_db, monkeypatch):
    """Кредитка в минус — нормально, защита её не касается."""
    from core import config
    f = _mk(monkeypatch)
    monkeypatch.setattr(config.cfg, "finance", config._Node({"allow_overdraft": False, "main_account": "Основной", "currency": "RUB"}), raising=False)
    f.add_account("Карта", kind="debt_only", balance=0)
    t = f.add_transaction(1_000, "expense", "Еда", "тест", account="Карта")
    assert t.amount == 1_000


async def _evil_judge(text, allowed):
    """Судья «уверен» всегда и всегда врёт в трату — точные команды всё равно идут своим путём."""
    return "expense", "test"


def test_exact_templates_ignore_evil_judge(fresh_db, monkeypatch):
    """Регресс флакающего test_core::test_expense_income_balance: при запущенной Ollama
    судья крал «баланс т-банк 10000» и «долг ...» в траты."""
    from core.services import judge
    f = _mk(monkeypatch)
    monkeypatch.setattr(judge, "decide", _evil_judge)
    r = _h("баланс т-банк 10000", "tg")
    assert "set_balance" in r.actions
    r = _h("долг Сберу 120к", "tg")
    assert "add_debt" in r.actions
    r = _h("потратил 700 на такси", "tg")
    assert "add_expense" in r.actions
    assert [t.kind for t in f.list_transactions(30, 100)].count("expense") == 1
