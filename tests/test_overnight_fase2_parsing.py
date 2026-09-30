"""ФАЗА 2 overnight-crm: регрессии парсинга (добавлены тесты, логика не менялась).

Проверяем «узкие» фразы, которые чаще всего ломаются при правках правил и парсеров:
суммы с «к»/«тыс», трата «<сумма> <категория>», дата «в среду в 15», долг с платежом.
"""
import asyncio
import os
from datetime import datetime

import pytest

os.environ.setdefault("ASSISTANT_TEST", "1")

from core import db  # noqa: E402
from core.brain.dates import parse_amount, parse_datetime  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlmodel import create_engine
    from sqlalchemy import event
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


NOW = datetime(2026, 9, 6, 14, 0)  # воскресенье


def run(text):
    from core.brain.agent import handle
    return asyncio.run(handle(text, "test"))


# ---------------------------------------------------------------- суммы
@pytest.mark.parametrize("text,amount,rest", [
    ("25к", 25000, ""),
    ("150 тыс", 150000, ""),
    ("120к", 120000, ""),
    ("8к", 8000, ""),
    ("700 такси", 700, "такси"),
    ("24 500 руб монтаж", 24500, "монтаж"),
])
def test_amount_short_forms(text, amount, rest):
    value, tail = parse_amount(text)
    assert value == amount
    assert tail == rest


# ---------------------------------------------------------------- дата и время
def test_weekday_with_explicit_time():
    dt, rest = parse_datetime("встреча в среду в 15", NOW)
    assert dt == datetime(2026, 9, 9, 15, 0)
    assert rest == "встреча"


# ---------------------------------------------------------------- правила трат/долга/встречи
def test_bare_amount_and_category_is_expense():
    from core.services import finance
    r = run("700 такси")
    assert "add_expense" in r.actions
    assert any(t.category == "Транспорт" and t.amount == 700 for t in finance.list_transactions(10, 1000))


def test_debt_with_payment_and_day():
    from core.services import finance
    run("долг банку 120к плачу 8к 25-го")
    d = finance.list_debts()[0]
    assert d.remaining == 120000 and d.payment == 8000 and d.pay_day == 25


def test_event_phrase_in_weekday():
    from core.services import calendar
    r = run("встреча в среду в 15")
    assert "add_event" in r.actions
    ev = calendar.list_events()[0]
    assert ev.start.hour == 15 and ev.start.weekday() == 2
