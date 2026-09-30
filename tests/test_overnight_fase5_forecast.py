"""ФАЗА 5 — прогноз кассы: ожидаемые оплаты заказов + регулярные платежи, реалистичный и пессимистичный сценарии.

Проверяем только расчёт `insights.cash_forecast`; существующие поля не трогаем (обратная совместимость).
"""
import os
from datetime import datetime, timedelta

import pytest

os.environ["ASSISTANT_TEST"] = "1"

from core import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlmodel import create_engine
    from sqlalchemy import event
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


def _set_recurring_next(rid: int, when: datetime) -> None:
    """Тесту нужна конкретная дата регулярного платежа — ставим её напрямую."""
    from core.db import Recurring, session
    with session() as s:
        r = s.get(Recurring, rid)
        r.next_date = when
        s.add(r)
        s.commit()


def test_scenarios_present_and_realistic_is_backwards_compatible():
    from core.services import finance, insights, orders
    finance.set_balance("Т-Банк", 10000)
    orders.add_order("монтаж", 30000, "Иванов", datetime.now() + timedelta(days=5))
    f = insights.cash_forecast(30)
    # старые поля на месте — эндпоинт/потребители не ломаются
    assert f["expected_income"] == 30000
    assert len(f["points"]) == 31 and "low" in f and "ok" in f and "per_day" in f
    sc = f["scenarios"]
    assert set(sc) == {"realistic", "pessimistic"}
    # реалистичный сценарий = верхнеуровневые поля (как считалось раньше)
    assert sc["realistic"]["points"] == f["points"]
    assert sc["realistic"]["low"] == f["low"]
    assert sc["realistic"]["ok"] == f["ok"]
    assert sc["pessimistic"]["low"] <= sc["realistic"]["low"]


def test_pessimistic_delays_expected_order_payment():
    from core.services import finance, insights, orders
    finance.set_balance("Т-Банк", 5000)
    orders.add_order("монтаж", 50000, "Иванов", datetime.now() + timedelta(days=10))
    f = insights.cash_forecast(30)
    real, pess = f["scenarios"]["realistic"], f["scenarios"]["pessimistic"]
    # реалистично: деньги пришли к дедлайну (день 10)
    assert real["points"][10]["balance"] == 55000
    # пессимистично: тот же платёж сдвинут на 14 дней и приходит на 24-й день
    assert pess["delay_days"] == 14
    assert pess["points"][10]["balance"] == 5000
    assert pess["points"][24]["balance"] == 55000
    assert pess["low"] <= real["low"]


def test_pessimistic_payment_beyond_horizon_not_counted():
    from core.services import finance, insights, orders
    finance.set_balance("Т-Банк", 1000)
    orders.add_order("лендинг", 40000, "Петров", datetime.now() + timedelta(days=20))
    f = insights.cash_forecast(30)
    real, pess = f["scenarios"]["realistic"], f["scenarios"]["pessimistic"]
    assert f["expected_income"] == 40000 and real["expected_income"] == 40000
    assert pess["expected_income"] == 0          # сдвиг попадает на 34-й день — вне горизонта
    assert pess["low"] <= real["low"]


def test_recurring_payments_counted_in_both_scenarios():
    from core.services import finance, insights
    finance.set_balance("Т-Банк", 20000)
    r = finance.add_recurring("аренда", 10000, 1, "expense")
    _set_recurring_next(r.id, datetime.now() + timedelta(days=7))
    ri = finance.add_recurring("зарплата", 15000, 1, "income")
    _set_recurring_next(ri.id, datetime.now() + timedelta(days=3))
    f = insights.cash_forecast(30)
    for name in ("realistic", "pessimistic"):
        evs = [e for p in f["scenarios"][name]["points"] for e in p["events"]]
        assert any(e["amount"] == -10000 for e in evs)      # регулярный расход
        assert any(e["amount"] == 15000 for e in evs)       # регулярный доход
    # и сами движения изменили баланс (расход увёл вниз)
    assert f["scenarios"]["realistic"]["low"] <= 20000


def test_zero_delay_makes_scenarios_equal():
    from core.services import finance, insights, orders
    finance.set_balance("Т-Банк", 5000)
    orders.add_order("монтаж", 50000, "Иванов", datetime.now() + timedelta(days=10))
    f = insights.cash_forecast(30, pessimistic_delay_days=0)
    assert f["scenarios"]["pessimistic"]["points"] == f["scenarios"]["realistic"]["points"]
    assert f["scenarios"]["pessimistic"]["low"] == f["scenarios"]["realistic"]["low"]


def test_forecast_text_shows_both_scenarios():
    from core.services import finance, insights, orders
    finance.set_balance("Т-Банк", 1000)
    finance.add_transaction(30000, "expense", "Разное", "текущие траты", "Т-Банк")
    orders.add_order("лендинг", 50000, "Петров", datetime.now() + timedelta(days=20))
    f = insights.cash_forecast(30)
    # сценарии действительно расходятся
    assert f["scenarios"]["pessimistic"]["low"] < f["scenarios"]["realistic"]["low"]
    txt = insights.cash_forecast_text()
    assert "по заказам" in txt          # ожидаемые оплаты учтены
    assert "Пессимистично" in txt        # показан второй сценарий
