# -*- coding: utf-8 -*-
"""Качество: деградация на пустой базе — аналитика не падает и отдаёт структуру.

`cashflow()` / `cash_forecast()` / `cash_series()` / `summary()` на базе без единой
операции обязаны вернуться обычным словарём, а `list_recurring(active_only=...)`
— стабильно фильтровать паузы и не менять порядок между вызовами.
Временная БД — фикстура `fresh_db` из tests/conftest.py.
"""
from __future__ import annotations

from datetime import date

import pytest

pytestmark = pytest.mark.usefixtures("fresh_db")


def _fin():
    from core.services import finance
    return finance


def _ins():
    from core.services import insights
    return insights


def test_cashflow_on_empty_db_is_calm():
    cf = _fin().cashflow()
    for key in ("income", "recurring", "debt_payments", "free", "avg_variable", "left_after_all"):
        assert key in cf, f"нет поля {key}"
    assert cf["income"] == 0 and cf["recurring"] == 0 and cf["debt_payments"] == 0
    assert cf["free"] == 0


def test_cash_forecast_on_empty_db_has_full_horizon():
    fc = _ins().cash_forecast(30)
    assert len(fc["points"]) == 31
    assert fc["ok"] is True and fc["low"] >= 0
    assert fc["per_day"] == 0
    assert fc["next_income"] is None and fc["days_to_income"] is None
    assert fc["scenarios"]["realistic"]["points"]


def test_cash_series_on_empty_db_is_flat_and_tied_to_balance():
    f = _fin()
    f.set_balance(f.main_account_name(), 7_700)
    s = _ins().cash_series(30)
    assert s["today"] == date.today().isoformat()
    past = [p for p in s["points"] if p["kind"] == "past"]
    assert past[-1]["date"] == s["today"]
    assert past[-1]["balance"] == round(f.total_balance()) == 7_700
    assert all(p["delta"] == 0 for p in past)              # операций нет — ряд плоский


def test_summary_on_empty_db_keeps_contract():
    s = _fin().summary(30)
    for key in ("spent", "earned", "by_category", "total_balance", "accounts",
                "cashflow", "budgets", "safe", "recurring_monthly"):
        assert key in s, f"нет поля {key}"
    assert s["spent"] == 0 and s["earned"] == 0 and s["by_category"] == {}


def test_safe_to_spend_and_upcoming_payments_on_empty_db():
    f = _fin()
    f.set_balance(f.main_account_name(), 5_000)
    st = f.safe_to_spend()
    assert st["balance"] == 5_000 and st["reserved"] == 0
    assert st["days_left"] >= 1
    assert f.upcoming_payments(7) == []


def test_list_recurring_active_only_is_stable():
    f = _fin()
    f.set_balance(f.main_account_name(), 10_000)
    r1 = f.add_recurring("Интернет", 500, day=1, period="weekly")
    r2 = f.add_recurring("Аренда", 30_000, day=5, period="monthly")
    f.stop_recurring(r1.id)                               # ушёл на паузу

    active = f.list_recurring(active_only=True)
    all_rows = f.list_recurring(active_only=False)
    assert [r.id for r in active] == [r2.id], "active_only=True показал платёж на паузе"
    assert {r.id for r in all_rows} == {r1.id, r2.id}, "active_only=False потерял платёж"
    # порядок — по дате следующего списания, одинаковый между вызовами
    assert [r.next_date for r in all_rows] == sorted(r.next_date for r in all_rows)
    assert [r.id for r in f.list_recurring(active_only=False)] == [r.id for r in all_rows]
    # дефолт — только активные (как раньше, вызов без аргументов)
    assert [r.id for r in f.list_recurring()] == [r.id for r in active]
    # после возврата с паузы — снова активный
    f.update_recurring(r1.id, active=True)
    assert {r.id for r in f.list_recurring()} == {r1.id, r2.id}


def test_forecast_and_series_do_not_write_to_db():
    """Аналитика — read-only: вызовы не создают операций и не двигают баланс."""
    from sqlmodel import select

    from core import db
    f = _fin()
    f.set_balance(f.main_account_name(), 3_000)
    with db.session() as s:
        before = len(s.exec(select(db.Transaction)).all())
    _fin().cashflow()
    _ins().cash_forecast(30)
    _ins().cash_series(30)
    _fin().summary(30)
    with db.session() as s:
        after = len(s.exec(select(db.Transaction)).all())
    assert after == before == 0
    assert f.total_balance() == 3_000
