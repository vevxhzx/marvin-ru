# -*- coding: utf-8 -*-
"""Боевой кейс «кубышка»: долг remaining 8369 vs карта −18400. При связке побеждает долг."""
from __future__ import annotations


def _fin():
    from core.services import finance
    return finance


def test_kubyshka_link_debt_wins(fresh_db):
    f = _fin()
    f.set_balance(f.main_account_name(), 50_000)
    d = f.add_debt("Кубышка", 25_000, remaining=8_369)
    c = f.add_account("Кубышка карта", kind="debt_only", balance=-18_400)
    f.link_debt_account(d.id, c.id)
    acc = next(a for a in f.list_accounts() if a.id == c.id)
    assert acc.balance == -8_369


def test_kubyshka_flows_stay_in_sync(fresh_db):
    f = _fin()
    f.set_balance(f.main_account_name(), 50_000)
    d = f.add_debt("Кубышка", 25_000, remaining=8_369)
    c = f.add_account("Кубышка карта", kind="debt_only", balance=-18_400)
    f.link_debt_account(d.id, c.id)
    # трата с карты растит обе стороны
    f.add_transaction(500, "expense", "Еда", "шоколад", account=c.name)
    assert f.find_debt(d.id).remaining == 8_869
    assert next(a for a in f.list_accounts() if a.id == c.id).balance == -8_869
    # перевод на карту гасит обе стороны
    f.add_transaction(1_000, "transfer", None, "погашение", account=f.main_account_name(), to_account=c.name)
    assert f.find_debt(d.id).remaining == 7_869
    assert next(a for a in f.list_accounts() if a.id == c.id).balance == -7_869
    # «внести платёж» обновляет обе стороны
    f.pay_debt(d.id, 1_000, account=f.main_account_name())
    assert f.find_debt(d.id).remaining == 6_869
    assert next(a for a in f.list_accounts() if a.id == c.id).balance == -6_869
