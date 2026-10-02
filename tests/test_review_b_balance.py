# -*- coding: utf-8 -*-
"""Ревью B «Деньги», часть 1 — баланс счёта, типы/округление сумм, сигнатуры суммы, правки и удаления.

Проверяемые инварианты:
* баланс счёта = стартовый баланс + сумма его операций (не расходится после серии,
  возвратов и удалений);
* суммы не разъезжаются из-за float-арифметики (погрешность < 1 копейки);
* «потратил -500» / «минус 900» / «потратил 0 …» / «потратил 1000000000000000 …»
  не ломают баланс и не падают необработанным исключением;
* правка операции пересчитывает балансы (и, где надо, категорию/тип).

Все проверки — ТОЛЬКО на временной БД (tmp_path): db.engine подменяется до init_db(),
настоящий data/jarvis.db не открывается и не пишется.
"""
from __future__ import annotations

import asyncio as _asyncio
import os

import pytest

os.environ.setdefault("ASSISTANT_TEST", "1")

from sqlalchemy import event  # noqa: E402
from sqlmodel import create_engine, select  # noqa: E402

from core import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    # правила работают без LLM — судью (живая модель) выключаем, как в test_golden_quick.py
    from core.services import judge as _judge
    monkeypatch.setattr(_judge, "enabled", lambda: False)
    yield


M = "Основной"
C = "Наличные"


def _fin():
    from core.services import finance
    return finance


def _acc(name: str):
    return next((a for a in _fin().list_accounts() if a.name == name), None)


def _tx(tx_id: int):
    with db.session() as s:
        return s.get(db.Transaction, tx_id)


def _signed(name: str) -> float:
    """Сумма операций счёта со знаком (то, чему баланс обязан равняться)."""
    with db.session() as s:
        rows = s.exec(select(db.Transaction)).all()
    total = 0.0
    for t in rows:
        if t.kind == "expense" and t.account == name:
            total -= t.amount
        elif t.kind == "income" and t.account == name:
            total += t.amount
        elif t.kind == "transfer":
            if t.account == name:
                total -= t.amount
            if t.to_account == name:
                total += t.amount
    return total


def _count() -> int:
    with db.session() as s:
        return len(s.exec(select(db.Transaction)).all())


def _main() -> str:
    """Правила «потратил …» пишут на основной счёт из config (не на «Основной»)."""
    return _fin().main_account_name()


def _run(text: str):
    return _asyncio.run(_run_async(text))


async def _run_async(text: str):
    from core.brain.agent import handle
    return await handle(text, "test")


# ------------------------------------------------------------------ 1. баланс = сумма операций
def test_balance_equals_sum_of_operations_after_mixed_series():
    f = _fin()
    f.set_balance(M, 100_000)
    f.set_balance(C, 5_000)
    for a in (10.10, 33.33, 0.01, 99.99, 1234.56, 7.77):          # копейки
        f.add_transaction(a, "expense", "Еда", "обед", M)
    f.add_transaction(1500.50, "income", "Фриланс", "аванс", M)
    f.add_transaction(150.0, "expense", "Транспорт", "такси", C)
    f.add_transaction(2000.0, "transfer", None, None, M, C)

    assert _acc(M).balance == pytest.approx(100_000 + _signed(M), abs=1e-6)
    assert _acc(C).balance == pytest.approx(5_000 + _signed(C), abs=1e-6)
    # перевод между своими счетами общий баланс не двигает
    assert f.total_balance() == pytest.approx(105_000 + _signed(M) + _signed(C), abs=1e-6)
    assert f.total_balance() == pytest.approx(100_000 + 5_000 + 1500.50 - (10.10 + 33.33 + 0.01 + 99.99 + 1234.56 + 7.77) - 150.0,
                                              abs=1e-6)


def test_deleting_every_operation_restores_seed_balance():
    f = _fin()
    f.set_balance(M, 100_000)
    f.set_balance(C, 5_000)
    f.add_transaction(10.10, "expense", "Еда", "обед", M)
    f.add_transaction(33.33, "expense", "Еда", "кофе", M)
    f.add_transaction(1500.50, "income", "Фриланс", "аванс", M)
    f.add_transaction(150.0, "expense", "Транспорт", "такси", C)
    f.add_transaction(2000.0, "transfer", None, None, M, C)
    ids = [t.id for t in f.list_transactions(30, 1000)]
    assert len(ids) == 5
    for tid in reversed(ids):
        assert f.delete_transaction(tid)
    assert _count() == 0
    assert _acc(M).balance == pytest.approx(100_000, abs=1e-6)
    assert _acc(C).balance == pytest.approx(5_000, abs=1e-6)
    assert f.total_balance() == pytest.approx(105_000, abs=1e-6)


def test_refund_returns_balance_and_is_counted_once():
    f = _fin()
    f.set_balance(M, 10_000)
    f.add_transaction(1_000, "expense", "Еда", "обед", M)
    f.add_transaction(1_000, "income", "Прочий доход", "возврат от кафе", M)
    assert _acc(M).balance == pytest.approx(10_000, abs=1e-9)
    s = f.summary(30)
    assert s["spent"] == pytest.approx(1_000.0)
    assert s["earned"] == pytest.approx(1_000.0)


# ------------------------------------------------------------------ 2. округление / float
def test_kopeck_drift_stays_below_one_kopeck():
    """Баланс = float и нигде не округляется: после 300 списаний по 0.1 ₽ остаётся
    микроскопический хвост (см. review_B.md, P3). Важно, что он меньше копейки."""
    f = _fin()
    f.set_balance(M, 30.0)
    for _ in range(300):
        f.add_transaction(0.1, "expense", "Еда", "кофе", M)
    got = _acc(M).balance
    assert round(got, 2) == 0.0            # до копейки сходится
    assert abs(got) < 0.005                 # и в UI (Math.round) хвост не виден
    # точное равенства 0.0 нет — доказательство накопления ошибки float
    assert abs(got) > 0


def test_two_decimal_amounts_do_not_drift_between_accounts():
    f = _fin()
    f.set_balance(M, 10_000.0)
    f.set_balance(C, 0.0)
    for i in range(50):
        f.add_transaction(0.10 + (i % 7) * 0.11, "expense", "Еда", "кофе", M)
        f.add_transaction(0.10 + (i % 7) * 0.11, "income", "Прочий доход", "возврат", M)
    assert _acc(M).balance == pytest.approx(10_000.0, abs=1e-6)
    assert _acc(C).balance == pytest.approx(0.0, abs=1e-9)
    # сумма операций счёта и его баланс не расходятся
    assert _acc(M).balance == pytest.approx(10_000.0 + _signed(M), abs=1e-6)


# ------------------------------------------------------------------ 3. сигнатура суммы
@pytest.mark.parametrize("bad", [0, -0.0, 1e15, 1_000_000_001, float("nan"), float("inf"),
                                 "-500", "abc", None])
def test_rejected_amounts_leave_balance_and_history_intact(bad):
    f = _fin()
    f.set_balance(M, 1_000)
    with pytest.raises(finance_error()):
        f.add_transaction(bad, "expense", "Еда", "тест", M)
    assert _count() == 0
    assert _acc(M).balance == pytest.approx(1_000, abs=1e-9)


def finance_error():
    return _fin().FinanceError


def test_negative_number_is_stored_as_positive_but_string_is_rejected():
    """int/float со знаком минус приводится по модулю (как в правилах «потратил -500»),
    а та же строка "-500" отклоняется — одинаковый вход ведёт себя по-разному (P3)."""
    f = _fin()
    f.set_balance(M, 1_000)
    t = f.add_transaction(-500, "expense", "Еда", "обед", M)
    assert t.amount == 500
    assert _acc(M).balance == pytest.approx(500, abs=1e-9)
    with pytest.raises(_fin().FinanceError):
        f.add_transaction("-500", "expense", "Еда", "обед", M)
    assert _count() == 1
    assert _acc(M).balance == pytest.approx(500, abs=1e-9)


def test_amount_limit_boundary_1e9():
    f = _fin()
    f.set_balance(M, 0)
    f.add_transaction(999_999_999, "expense", "Транспорт", "граница", M)   # ровно в лимите
    assert _acc(M).balance == pytest.approx(-999_999_999, abs=1e-6)
    with pytest.raises(_fin().FinanceError):
        f.add_transaction(1_000_000_001, "expense", "Транспорт", "перебор", M)
    assert _count() == 1
    assert _acc(M).balance == pytest.approx(-999_999_999, abs=1e-6)


@pytest.mark.parametrize("text", ["потратил 0 на обед",
                                  "потратил 1000000000000000 на еду",
                                  "получил 0 зарплату"])
def test_rules_bad_amount_is_answered_not_raised(text):
    """Соседи известных «потратил 0 …» / «потратил 1e15 …»: FinanceError должен
    превратиться в ответ, без записи в БД и без падения."""
    f = _fin()
    acc = _main()
    f.set_balance(acc, 10_000)
    r = _run(text)
    assert r.text and not r.actions, f"ожидался ответ без действий, получено: {r.actions} / {r.text[:120]}"
    assert _count() == 0
    assert _acc(acc).balance == pytest.approx(10_000, abs=1e-9)


def test_rules_signed_amounts_land_as_positive_expenses():
    f = _fin()
    acc = _main()
    f.set_balance(acc, 10_000)
    r1 = _run("потратил -500 на обед")
    assert "add_expense" in r1.actions
    assert f.summary(1)["spent"] == pytest.approx(500)
    assert _acc(acc).balance == pytest.approx(9_500, abs=1e-9)
    r2 = _run("минус 900 на обед")
    assert "add_expense" in r2.actions
    assert _acc(acc).balance == pytest.approx(8_600, abs=1e-9)
    assert _count() == 2


def test_rules_zero_amount_does_not_change_anything():
    f = _fin()
    acc = _main()
    f.set_balance(acc, 10_000)
    r = _run("потратил 0 на обед")
    assert not r.actions
    assert _count() == 0
    assert _acc(acc).balance == pytest.approx(10_000, abs=1e-9)


# ------------------------------------------------------------------ 6. удаление / редактирование
def test_edit_amount_recalculates_balance():
    f = _fin()
    f.set_balance(M, 10_000)
    t = f.add_transaction(500, "expense", "Еда", "обед", M)
    assert _acc(M).balance == pytest.approx(9_500, abs=1e-9)
    f.update_transaction(t.id, amount=300)
    assert _tx(t.id).amount == pytest.approx(300)
    assert _acc(M).balance == pytest.approx(9_700, abs=1e-9)


def test_edit_kind_recalculates_balance():
    f = _fin()
    f.set_balance(M, 10_000)
    t = f.add_transaction(500, "expense", "Еда", "обед", M)
    f.update_transaction(t.id, kind="income")
    assert _tx(t.id).kind == "income"
    # 10 000 (старт) + 500 дохода — расход полностью превратился в доход
    assert _acc(M).balance == pytest.approx(10_500, abs=1e-9)


def test_edit_account_moves_money_between_accounts():
    f = _fin()
    f.set_balance(M, 10_000)
    f.set_balance(C, 1_000)
    t = f.add_transaction(500, "expense", "Еда", "обед", M)
    f.update_transaction(t.id, account=C)
    assert _acc(M).balance == pytest.approx(10_000, abs=1e-9)
    assert _acc(C).balance == pytest.approx(500, abs=1e-9)


def test_edit_to_unknown_account_rolls_back():
    f = _fin()
    f.set_balance(M, 10_000)
    t = f.add_transaction(500, "expense", "Еда", "обед", M)
    with pytest.raises(_fin().FinanceError):
        f.update_transaction(t.id, account="Несуществующий")
    assert _tx(t.id).account == M
    assert _acc(M).balance == pytest.approx(9_500, abs=1e-9)


def test_delete_after_edit_returns_seed():
    f = _fin()
    f.set_balance(M, 10_000)
    t = f.add_transaction(500, "expense", "Еда", "обед", M)
    f.update_transaction(t.id, amount=800)
    assert _acc(M).balance == pytest.approx(9_200, abs=1e-9)
    f.delete_transaction(t.id)
    assert _acc(M).balance == pytest.approx(10_000, abs=1e-9)
    assert _count() == 0


# P2 закрыт: update_transaction(kind=...) при смене типа пересчитывает конфликтующую категорию
# (доход уходит из «Еды» в подходящую ему). Был xfail(strict) в core/services/finance.py.
def test_edit_kind_rerecalculates_category():
    f = _fin()
    f.set_balance(M, 10_000)
    t = f.add_transaction(500, "expense", "Еда", "обед", M)
    f.update_transaction(t.id, kind="income")
    assert _tx(t.id).category == "Прочий доход"
