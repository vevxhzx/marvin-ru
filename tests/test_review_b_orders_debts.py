# -*- coding: utf-8 -*-
"""Ревью B «Деньги», часть 3 — заказы/оплаты (Transaction с order_id),долги, конверты.

Проверяемые инварианты:
* повторная оплата с тем же ``idem_key`` не задваивает доход (и по сервису, и по веб-роуту);
* удаление заказа не трогает деньги (операции остаются, баланс сохраняется);
* удаление оплаты возвращает деньги и открывает заказ заново;
* платёж по долгу списывается ТОЛЬКО со своего счёта;
* ошибка валидации суммы не оставляет «висячие» записи (цель saved, оплата).

Всё на временной БД (tmp_path): db.engine подменяется до init_db(), data/jarvis.db
не открывается и не пишется.
"""
from __future__ import annotations

import os

import pytest

os.environ.setdefault("ASSISTANT_TEST", "1")

from core import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlalchemy import event
    from sqlmodel import create_engine
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


C = "Наличные"


def _fin():
    from core.services import finance
    return finance


def _ord():
    from core.services import orders
    return orders


def _main() -> str:
    return _fin().main_account_name()


def _goals():
    from core.services import goals
    return goals


def _acc_balance(name: str) -> float:
    return next(a.balance for a in _fin().list_accounts() if a.name == name)


def _count_order_tx(oid: int) -> int:
    from sqlmodel import select
    with db.session() as s:
        return len(s.exec(select(db.Transaction).where(db.Transaction.order_id == oid)).all())


# ---------------------------------------------------------------- заказы и оплаты
def test_add_payment_same_idem_key_does_not_double_income():
    f, o = _fin(), _ord()
    f.set_balance(_main(), 10_000)
    order = o.add_order("Ролик", 5_000, status="done")
    t1 = o.add_payment(order.id, 2_000, idem_key="pay-42")
    t2 = o.add_payment(order.id, 2_000, idem_key="pay-42")   # повтор запроса
    assert t1.id == t2.id
    assert o.paid_for(order.id) == 2_000
    assert _count_order_tx(order.id) == 1
    assert _acc_balance(_main()) == 12_000


def test_delete_order_keeps_money_transactions():
    f, o = _fin(), _ord()
    f.set_balance(_main(), 10_000)
    order = o.add_order("Ролик", 3_000, status="done")
    o.add_payment(order.id, 3_000)
    assert _acc_balance(_main()) == 13_000
    assert o.delete_order(order.id) is True
    assert o.get_order(order.id) is None
    # деньги реально получены — операция остаётся в финансах, только без привязки
    assert _acc_balance(_main()) == 13_000
    from sqlmodel import select
    with db.session() as s:
        rows = [t for t in s.exec(select(db.Transaction)).all() if t.amount == 3_000]
    assert len(rows) == 1 and rows[0].kind == "income" and rows[0].order_id is None
    assert f.summary(30)["earned"] == pytest.approx(3_000)


def test_delete_payment_returns_money_and_reopens_order():
    f, o = _fin(), _ord()
    f.set_balance(_main(), 10_000)
    order = o.add_order("Ролик", 3_000, status="done")
    t = o.add_payment(order.id, 3_000)
    assert o.get_order(order.id).status == "paid"
    f.delete_transaction(t.id)
    got = o.get_order(order.id)
    assert got.status != "paid" and got.paid_at is None
    assert o.paid_for(order.id) == 0
    assert o.order_view(got)["left"] == 3_000
    assert _acc_balance(_main()) == 10_000


@pytest.mark.xfail(strict=True,
                   reason="P2: POST /api/orders/{id}/payments принимает PaymentIn без idem_key "
                          "(и сайт его не шлёт) — повтор одного и того же запроса "
                          "создаёт второй доход, в отличие от /api/crm/…/payments")
def test_web_payment_endpoint_honors_idem_key():
    from fastapi.testclient import TestClient
    from core.api.app import app
    f, o = _fin(), _ord()
    f.set_balance(_main(), 10_000)
    order = o.add_order("Ролик", 5_000, status="done")
    c = TestClient(app, base_url="http://localhost", client=("127.0.0.1", 5555))
    body = {"amount": 2_000, "idem_key": "web-pay-1"}
    r1 = c.post(f"/api/orders/{order.id}/payments", json=body)
    r2 = c.post(f"/api/orders/{order.id}/payments", json=body)
    assert r1.status_code < 400 and r2.status_code < 400, (r1.text, r2.text)
    assert len(o.payments_for(order.id)) == 1, "двойной клик = второй доход"
    assert o.paid_for(order.id) == 2_000


# ---------------------------------------------------------------- долги
def test_pay_debt_touches_only_its_account():
    f = _fin()
    f.set_balance(_main(), 10_000)
    f.set_balance(C, 5_000)
    d = f.add_debt("Рассрочка", 3_000, payment=0)
    f.pay_debt(d.id, 1_000, account=C)
    assert _acc_balance(C) == 4_000                 # списалось со счёта платежа
    assert _acc_balance(_main()) == 10_000          # основной счёт не тронут
    assert f.find_debt(d.id).remaining == 2_000
    txs = f.debt_payments(d.id)
    assert len(txs) == 1 and txs[0].account == C and txs[0].category == "Долги"


def test_pay_debt_overpay_rejected_and_balance_intact():
    f = _fin()
    f.set_balance(_main(), 10_000)
    f.set_balance(C, 5_000)
    d = f.add_debt("Рассрочка", 3_000, payment=0)
    with pytest.raises(f.FinanceError):
        f.pay_debt(d.id, 5_000, account=C)          # больше остатка
    assert f.find_debt(d.id).remaining == 3_000
    assert _acc_balance(C) == 5_000 and _acc_balance(_main()) == 10_000
    assert f.debt_payments(d.id) == []


def test_delete_debt_payment_restores_remaining_and_balance():
    f = _fin()
    f.set_balance(_main(), 10_000)
    f.set_balance(C, 5_000)
    d = f.add_debt("Рассрочка", 3_000, payment=0)
    f.pay_debt(d.id, 1_000, account=C)
    tx = f.debt_payments(d.id)[0]
    f.delete_transaction(tx.id)
    assert f.find_debt(d.id).remaining == 3_000
    assert _acc_balance(C) == 5_000 and _acc_balance(_main()) == 10_000
    assert f.debt_payments(d.id) == []


# ---------------------------------------------------------------- конверты (цели)
@pytest.mark.xfail(strict=True,
                   reason="P2: goals.put_to_goal фиксирует g.saved (commit) ДО того, как "
                          "add_transaction проверит сумму — FinanceError на сумме 1e15 "
                          "оставляет цель с saved=1e15 и closed=True, а операции нет")
def test_put_to_goal_invalid_amount_leaves_goal_intact():
    f, g = _fin(), _goals()
    f.set_balance(_main(), 10_000)
    goal = g.add_goal("Подушка", 100_000)
    with pytest.raises(f.FinanceError):
        g.put_to_goal(goal.id, 1e15)                # сумма больше лимита операции
    with db.session() as s:                          # цель — как она реально лежит в БД
        stored = s.get(db.Goal, goal.id)
    assert stored.saved == 0, "ошибка валидации не должна увеличивать «отложено»"
    assert not stored.closed
    assert f.summary(30)["spent"] == 0
