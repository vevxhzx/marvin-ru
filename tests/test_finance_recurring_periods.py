# -*- coding: utf-8 -*-
"""Регулярные платежи: период «год» с месяцем, «неделя» с днём недели и пауза.

Пауза — это `active=False`, а не удаление: платёж остаётся в базе и в списке
`list_recurring(active_only=False)`, чтобы интерфейс мог показать его выключенным.
Временная БД — фикстура `fresh_db` из tests/conftest.py.
"""
from __future__ import annotations

from datetime import datetime

import pytest

pytestmark = pytest.mark.usefixtures("fresh_db")


def _fin():
    from core.services import finance
    return finance


def test_yearly_payment_keeps_month():
    """«каждый год 23 августа»: месяц должен сохраниться, а не подставиться текущий."""
    f = _fin()
    r = f.add_recurring("Сертификат на айфон", 1700, day=23, period="yearly", month=8)
    assert r.period == "yearly" and r.day == 23
    assert r.next_date.month == 8 and r.next_date.day == 23
    assert r.next_date > datetime.now(), "ближайшая дата должна быть в будущем"


def test_yearly_update_keeps_month_without_explicit_month():
    """Правка числа не должна сбрасывать месяц годового платежа на текущий."""
    f = _fin()
    r = f.add_recurring("ОСАГО", 8000, day=23, period="yearly", month=8)
    f.update_recurring(r.id, day=25)
    got = f.find_recurring(r.id)
    assert got.next_date.month == 8 and got.next_date.day == 25


def test_weekly_payment_day_is_weekday():
    """«каждую неделю»: день 0..6 (0 = понедельник), а не число месяца."""
    f = _fin()
    r = f.add_recurring("Интернет", 500, day=0, period="weekly")
    assert r.day == 0
    assert r.next_date.weekday() == 0
    with pytest.raises(f.FinanceError):
        f.add_recurring("Кривой", 100, day=9, period="weekly")


def test_pause_keeps_payment_visible():
    """Тумблер паузы выключает платёж, но не убирает его из базы и из «с паузами»."""
    f = _fin()
    r = f.add_recurring("Яндекс Плюс", 399, day=11, period="monthly")
    f.update_recurring(r.id, active=False)
    assert f.list_recurring(active_only=True) == []
    all_rec = f.list_recurring(active_only=False)
    assert [x.id for x in all_rec] == [r.id]
    assert all_rec[0].active is False
    # включаем обратно — снова активен
    f.update_recurring(r.id, active=True)
    assert [x.id for x in f.list_recurring(active_only=True)] == [r.id]


def test_credit_card_account_is_not_in_balance():
    """Счёт-кредитка (debt_only): трата растит долг, но не трогает баланс на руках."""
    f = _fin()
    f.set_balance(f.main_account_name(), 50_000)
    card = f.add_account("Альфа кредитка", kind="debt_only", balance=0)
    f.add_transaction(1700, "expense", "Техника", "сертификат", account=card.name)
    acc = next(a for a in f.list_accounts() if a.name == card.name)
    assert acc.balance == -1700, "долг по кредитке должен вырасти"
    assert f.total_balance() == 50_000, "кредитка не входит в баланс на руках"
