# -*- coding: utf-8 -*-
"""Карточка долга v18: все поля, история платежей, сводка, порядок, архив, напоминания."""
from __future__ import annotations

from datetime import datetime, timedelta


def _fin():
    from core.services import finance
    return finance


def _acc(name):
    f = _fin()
    return next(a for a in f.list_accounts() if a.name == name)


def test_new_fields_are_stored_and_updated(fresh_db):
    f = _fin()
    d = f.add_debt("Сбер карта", 90_000, payment=6_000, rate=24, pay_day=12, creditor="Сбер",
                   kind="credit_card", credit_limit=150_000, color="#7cd8a0", note="до 2027",
                   remind_days=5)
    assert (d.kind, d.credit_limit, d.color, d.note, d.remind_days) == (
        "credit_card", 150_000, "#7cd8a0", "до 2027", 5)
    assert d.sort_order > 0

    d2 = f.update_debt(d.id, note="новый текст", remind_days=0, kind="installment", credit_limit=0)
    assert d2.note == "новый текст" and d2.remind_days == 0 and d2.kind == "installment"


def test_paid_and_remaining_recalculate_each_other(fresh_db):
    f = _fin()
    d = f.add_debt("Рассрочка", 40_000, payment=4_000)
    assert f.update_debt(d.id, paid=15_000).remaining == 25_000
    assert f.update_debt(d.id, remaining=10_000).total - f.find_debt(d.id).remaining == 30_000
    # форма шлёт total+paid: остаток выводится из выплаченного
    assert f.update_debt(d.id, total=50_000, paid=20_000).remaining == 30_000


def test_payment_edit_and_delete_roll_back_remaining_and_balance(fresh_db):
    f = _fin()
    f.set_balance(f.main_account_name(), 100_000)
    card = f.add_account("Зарплатная", kind="bank", balance=50_000)
    d = f.add_debt("Кредит", 30_000, payment=3_000)
    f.pay_debt(d.id, 5_000, account=card.name, note="первый")
    tx = f.debt_payments(d.id)[0]
    assert f.find_debt(d.id).remaining == 25_000
    assert _acc(card.name).balance == 45_000

    f.update_debt_payment(d.id, tx.id, amount=2_000, note="исправил", account=f.main_account_name())
    assert f.find_debt(d.id).remaining == 28_000
    assert _acc(card.name).balance == 50_000
    assert _acc(f.main_account_name()).balance == 98_000
    assert f.debt_payments(d.id)[0].note == "исправил"

    assert f.delete_debt_payment(d.id, tx.id)
    assert f.find_debt(d.id).remaining == 30_000
    assert _acc(f.main_account_name()).balance == 100_000
    assert f.debt_payments(d.id) == []


def test_summary_nearest_minimum_and_overpay(fresh_db):
    f = _fin()
    today = datetime.now()
    day = min(28, today.day)
    f.add_debt("Кредитка", 50_000, payment=5_000, rate=20, pay_day=day, kind="credit_card", credit_limit=100_000)
    f.add_debt("Личный", 10_000, payment=1_000, rate=0, pay_day=day)
    s = f.debt_summary()
    assert s["count"] == 2
    assert s["payment_total"] == 6_000
    assert s["remaining_total"] == 60_000
    assert s["nearest"] and s["nearest"]["amount"] == 5_000 and s["nearest"]["date"]
    assert s["close_date"] and s["overpay"] is not None and s["overpay"] >= 0


def test_reorder_soft_delete_and_restore(fresh_db):
    f = _fin()
    a = f.add_debt("A", 10_000, payment=1_000)
    b = f.add_debt("B", 20_000, payment=1_000)
    assert f.reorder_debts([b.id, a.id]) == 2
    assert [d.id for d in f.list_debts()] == [b.id, a.id]

    assert f.delete_debt(a.id)
    assert [d.id for d in f.list_debts()] == [b.id]
    # мягкое удаление: платежи и история остаются, «вернуть» доступно
    assert f.restore_debt(a.id).deleted_at is None
    assert {d.id for d in f.list_debts()} == {a.id, b.id}


def test_receivable_payment_is_income_not_expense(fresh_db):
    f = _fin()
    f.set_balance(f.main_account_name(), 10_000)
    d = f.add_debt("Долг Вани", 5_000, payment=0, kind="receivable")
    f.pay_debt(d.id, 2_000, account=f.main_account_name())
    tx = f.debt_payments(d.id)[0]
    assert tx.kind == "income", "возврат «мне должны» — приход, а не расход"
    assert f.find_debt(d.id).remaining == 3_000
    assert _acc(f.main_account_name()).balance == 12_000


def test_reminder_due_soon_once_per_month(fresh_db):
    f = _fin()
    day = (datetime.now() + timedelta(days=1)).day
    d = f.add_debt("Платёж", 10_000, payment=1_000, pay_day=day, remind_days=3)
    due = [(x.id, n) for x, n in f.debt_due_soon()]
    assert d.id in [x[0] for x in due]
    month = f.next_pay_date(day).strftime("%Y-%m")
    f.mark_debt_reminded(d.id, month)
    assert d.id not in [x[0] for x, _ in f.debt_due_soon()]


def test_api_roundtrip_fields_and_payments(fresh_db, _client):
    c = _client
    r = c.post("/api/finance/debts", json={
        "title": "Тест карта", "total": 100_000, "payment": 5_000, "rate": 19.9, "pay_day": 5,
        "kind": "credit_card", "credit_limit": 200_000, "color": "#ff8800", "note": "заметка",
        "remind_days": 7,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert (d["kind"], d["credit_limit"], d["color"], d["remind_days"]) == (
        "credit_card", 200_000, "#ff8800", 7)
    assert d["paid"] == 0

    r = c.put(f"/api/finance/debts/{d['id']}", json={"paid": 25_000})
    assert r.status_code == 200 and r.json()["remaining"] == 75_000

    r = c.post(f"/api/finance/debts/{d['id']}/pay", json={"amount": 5_000, "account": _fin().main_account_name(), "note": "тест"})
    assert r.status_code == 200, r.text
    pays = c.get(f"/api/finance/debts/{d['id']}/payments").json()
    assert len(pays) == 1 and pays[0]["note"] == "тест"

    r = c.put(f"/api/finance/debts/{d['id']}/payments/{pays[0]['id']}", json={"amount": 3_000})
    assert r.status_code == 200 and r.json()["amount"] == 3_000
    assert c.delete(f"/api/finance/debts/{d['id']}/payments/{pays[0]['id']}").status_code == 200

    assert c.get("/api/finance/debts/summary").status_code == 200
    assert c.get("/api/finance/debts?archived=true").status_code == 200
    assert c.post("/api/finance/debts/order", json={"ids": [d["id"]]}).status_code == 200
    assert c.delete(f"/api/finance/debts/{d['id']}").status_code == 200
    assert c.post(f"/api/finance/debts/{d['id']}/restore").status_code == 200
