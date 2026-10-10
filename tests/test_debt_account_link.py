# -*- coding: utf-8 -*-
"""Связка долг ↔ счёт-кредитка 1-к-1: трата с кредитки растит долг, перевод на неё — уменьшает, платёж обновляет оба."""
from __future__ import annotations


def _fin():
    from core.services import finance
    return finance


def test_link_sets_account_to_minus_remaining(fresh_db):
    f = _fin()
    f.set_balance(f.main_account_name(), 50_000)
    d = f.add_debt("Кубышка", 25_000)
    c = f.add_account("Кубышка карта", kind="debt_only", balance=0)
    f.link_debt_account(d.id, c.id)
    acc = next(a for a in f.list_accounts() if a.id == c.id)
    assert acc.debt_id == d.id
    assert acc.balance == -d.remaining


def test_expense_on_linked_grows_debt(fresh_db):
    f = _fin()
    f.set_balance(f.main_account_name(), 50_000)
    d = f.add_debt("Кубышка", 25_000, remaining=0)
    c = f.add_account("Кубышка карта", kind="debt_only", balance=0)
    f.link_debt_account(d.id, c.id)
    f.add_transaction(1_700, "expense", "Техника", "сертификат", account=c.name)
    d2 = f.find_debt(d.id)
    acc = next(a for a in f.list_accounts() if a.id == c.id)
    assert acc.balance == -1_700
    assert d2.remaining == 1_700
    assert d2.total >= 1_700


def test_transfer_to_linked_reduces_debt(fresh_db):
    f = _fin()
    f.set_balance(f.main_account_name(), 50_000)
    d = f.add_debt("Кубышка", 25_000, remaining=10_000)
    c = f.add_account("Кубышка карта", kind="debt_only", balance=-10_000)
    f.link_debt_account(d.id, c.id)
    main_before = next(a for a in f.list_accounts() if a.name == f.main_account_name()).balance
    f.add_transaction(2_000, "transfer", None, "погашение", account=f.main_account_name(), to_account=c.name)
    d2 = f.find_debt(d.id)
    acc = next(a for a in f.list_accounts() if a.id == c.id)
    main_after = next(a for a in f.list_accounts() if a.name == f.main_account_name()).balance
    assert d2.remaining == 8_000
    assert acc.balance == -8_000
    assert main_after == main_before - 2_000


def test_pay_debt_credits_linked_card(fresh_db):
    f = _fin()
    f.set_balance(f.main_account_name(), 50_000)
    d = f.add_debt("Кубышка", 25_000, remaining=10_000)
    c = f.add_account("Кубышка карта", kind="debt_only", balance=-10_000)
    f.link_debt_account(d.id, c.id)
    f.pay_debt(d.id, 3_000, account=f.main_account_name())
    d2 = f.find_debt(d.id)
    acc = next(a for a in f.list_accounts() if a.id == c.id)
    assert d2.remaining == 7_000
    assert acc.balance == -7_000


def test_unlink_stops_sync(fresh_db):
    f = _fin()
    f.set_balance(f.main_account_name(), 50_000)
    d = f.add_debt("Кубышка", 25_000, remaining=5_000)
    c = f.add_account("Кубышка карта", kind="debt_only", balance=-5_000)
    f.link_debt_account(d.id, c.id)
    f.unlink_debt_account(d.id)
    f.add_transaction(500, "expense", "Еда", "шоколад", account=c.name)
    d2 = f.find_debt(d.id)
    acc = next(a for a in f.list_accounts() if a.id == c.id)
    assert d2.remaining == 5_000
    assert acc.balance == -5_500
    assert acc.debt_id is None
