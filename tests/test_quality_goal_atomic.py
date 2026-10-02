# -*- coding: utf-8 -*-
"""Качество: put_to_goal атомарен — валидация до записи (бывший xfail P2).

Любая ошибка (сумма 0 / больше лимита / неизвестный счёт / нет цели) оставляет цель
ровно такой, какой она была: saved не двигается, closed не ставится, операции нет.
Временная БД — фикстура `fresh_db` из tests/conftest.py.
"""
from __future__ import annotations

import pytest

from core import db  # noqa: E402

pytestmark = pytest.mark.usefixtures("fresh_db")


def _fin():
    from core.services import finance
    return finance


def _goals():
    from core.services import goals
    return goals


def _goal_row(gid: int):
    with db.session() as s:                     # как цель реально лежит в БД (не через view)
        return s.get(db.Goal, gid)


def _tx_count() -> int:
    from sqlmodel import select
    with db.session() as s:
        return len(s.exec(select(db.Transaction)).all())


def test_invalid_amount_leaves_goal_intact():
    f, g = _fin(), _goals()
    f.set_balance(f.main_account_name(), 10_000)
    goal = g.add_goal("Подушка", 100_000)
    with pytest.raises(f.FinanceError):
        g.put_to_goal(goal.id, 1e15)            # больше лимита суммы
    row = _goal_row(goal.id)
    assert row.saved == 0 and not row.closed
    assert _tx_count() == 0
    assert f.summary(30)["spent"] == 0


@pytest.mark.parametrize("bad", [0, -0.0, float("nan"), float("inf"), "abc", None])
def test_any_rejected_amount_keeps_goal_pristine(bad):
    f, g = _fin(), _goals()
    f.set_balance(f.main_account_name(), 10_000)
    goal = g.add_goal("Подушка", 100_000)
    with pytest.raises(f.FinanceError):
        g.put_to_goal(goal.id, bad)
    row = _goal_row(goal.id)
    assert row.saved == 0 and not row.closed
    assert _tx_count() == 0


def test_unknown_account_does_not_credit_goal():
    """Операция отказалась (нет счёта) — «отложено» не должно было вырасти раньше проверки."""
    f, g = _fin(), _goals()
    f.set_balance(f.main_account_name(), 10_000)
    goal = g.add_goal("Подушка", 100_000)
    with pytest.raises(f.FinanceError):
        g.put_to_goal(goal.id, 5_000, from_account="Несуществующий")
    row = _goal_row(goal.id)
    assert row.saved == 0 and not row.closed
    assert _tx_count() == 0


def test_missing_goal_writes_no_orphan_transaction():
    f, g = _fin(), _goals()
    f.set_balance(f.main_account_name(), 10_000)
    with pytest.raises(f.FinanceError):
        g.put_to_goal(999, 5_000)
    assert _tx_count() == 0
    assert f.summary(30)["spent"] == 0


def test_valid_amount_still_moves_money_and_credits_goal():
    f, g = _fin(), _goals()
    f.set_balance(f.main_account_name(), 10_000)
    goal = g.add_goal("Подушка", 100_000)
    r = g.put_to_goal(goal.id, 5_000)
    assert r["goal"]["saved"] == 5_000 and not r["reached"]
    row = _goal_row(goal.id)
    assert row.saved == 5_000 and not row.closed
    assert _tx_count() == 1
    assert f.summary(30)["spent"] == 5_000
    # достигнутая цель закрывается только после успешной записи
    r = g.put_to_goal(goal.id, 95_000)
    assert r["reached"] and _goal_row(goal.id).closed


def test_negative_amount_withdraws_without_touching_balance():
    f, g = _fin(), _goals()
    f.set_balance(f.main_account_name(), 10_000)
    goal = g.add_goal("Подушка", 100_000)
    g.put_to_goal(goal.id, 5_000)
    r = g.put_to_goal(goal.id, -2_000)          # забрали из конверта
    assert r["goal"]["saved"] == 3_000
    assert f.total_balance() == 7_000           # 10 000 − 5 000 + 2 000
