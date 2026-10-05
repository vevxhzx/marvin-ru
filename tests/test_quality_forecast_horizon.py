# -*- coding: utf-8 -*-
"""Качество: cash_forecast не режет регулярные платежи по константе 6 (бывший xfail P2).

Количество повторов считается от горизонта и периода; поля ответа и поведение для
месячных/годовых платежей не изменились (обратная совместимость).
Временная БД — фикстура `fresh_db` из tests/conftest.py.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("fresh_db")


def _fin():
    from core.services import finance
    return finance


def _ins():
    from core.services import insights
    return insights


def _events(fc: dict, title: str) -> int:
    """Сколько точек прогноза содержат событие с таким названием."""
    return sum(1 for p in fc["points"]
               if any(e.get("title") == title for e in (p.get("events") or [])))


def test_weekly_payment_not_capped_at_six():
    f = _fin()
    f.set_balance(f.main_account_name(), 100_000)
    f.add_recurring("Интернет", 500, day=1, period="weekly")
    fc = _ins().cash_forecast(90)
    n = _events(fc, "Интернет")
    assert n >= 12, f"недельный платёж за 90 дней должен встретиться ~13 раз, встретился {n}"
    # и не больше, чем реальных недель в горизонте (+1 на пограничный день)
    assert n <= 14, f"лишние события вне горизонта: {n}"


def test_weekly_payment_matches_short_horizon():
    """Короткий горизонт не задумывается: неделя вперёд — ровно одно списание."""
    f = _fin()
    f.set_balance(f.main_account_name(), 100_000)
    f.add_recurring("Интернет", 500, day=1, period="weekly")
    assert _events(_ins().cash_forecast(7), "Интернет") <= 2


def test_monthly_payment_still_occurs_once_a_month():
    f = _fin()
    f.set_balance(f.main_account_name(), 100_000)
    f.add_recurring("Аренда", 30_000, day=5, period="monthly")
    # Горизонт берём 100 дней, а не 90: 90 дней от любого числа после 5-го — это только
    # два наступления 5-го числа (следующее уже за окном), и тест падал 25 дней из 30.
    # Смысл не меняется: платёж идёт раз в месяц и не режется по константе 6.
    n = _events(_ins().cash_forecast(100), "Аренда")
    assert 3 <= n <= 5, f"месячный платёж за 100 дней: ожидалось 3–4, получено {n}"
    # за 30 дней — как и раньше, не больше двух
    assert _events(_ins().cash_forecast(30), "Аренда") <= 2


def test_yearly_payment_occurs_within_a_year():
    f = _fin()
    f.set_balance(f.main_account_name(), 100_000)
    f.add_recurring("ОСАГО", 8_000, day=1, period="yearly")
    n = _events(_ins().cash_forecast(400), "ОСАГО")
    assert 1 <= n <= 2, f"годовой платёж за 400 дней: ожидалось 1–2, получено {n}"
    assert _events(_ins().cash_forecast(30), "ОСАГО") <= 1


def test_forecast_response_shape_is_backward_compatible():
    """Верхнеуровневые поля (points/low/ok/…) и сценарии на месте — фронт не заметит правки."""
    f = _fin()
    f.set_balance(f.main_account_name(), 50_000)
    fc = _ins().cash_forecast(30)
    for key in ("points", "per_day", "low", "low_date", "next_income", "days_to_income",
                "safe_per_day", "expected_income", "expected_tax", "ok", "scenarios"):
        assert key in fc, f"нет поля {key}"
    assert len(fc["points"]) == 31                      # сегодня + 30 дней
    assert fc["scenarios"]["realistic"]["delay_days"] == 0
    assert fc["scenarios"]["pessimistic"]["delay_days"] >= 0
    # точки идут подряд, без дат вне горизонта
    from datetime import date
    ds = [p["date"] for p in fc["points"]]
    assert len(ds) == len(set(ds))
    assert all(date.fromisoformat(b) > date.fromisoformat(a) for a, b in zip(ds, ds[1:]))


def test_recurring_on_pause_is_not_forecast():
    f = _fin()
    f.set_balance(f.main_account_name(), 100_000)
    r = f.add_recurring("Интернет", 500, day=1, period="weekly")
    f.stop_recurring(r.id)                              # на паузе — из расписания уходит
    assert _events(_ins().cash_forecast(90), "Интернет") == 0
