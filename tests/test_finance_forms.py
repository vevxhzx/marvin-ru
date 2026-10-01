"""Формы финансов: алиас `name` → `title` и регулярные доходы в прогнозе.

Фон: веб-формы «новый долг» и «+ платёж» шли с полем `name`, а API ждёт `title` —
пользователь получал 4 тоста «Field required» (422) и не мог ни добавить долг, ни
завести регулярный доход. Здесь фиксируем:

1. старый алиас `name` принимается (обратная совместимость со старым бандлом),
   но «без названия» по-прежнему 422 — контракт не размыт;
2. регулярный доход создаётся (`kind=income`), виден через `?all=true` вместе с паузами
   и НЕ виден в обычном списке, когда стоит на паузе (как раньше);
3. активный доход реально учитывается в `cashflow()` и `insights.cash_forecast()`.

Фикстура `fresh_db` (tests/test_core) — временная БД в tmp_path, `data/jarvis.db`
не открывается.
"""
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402
from tests.test_core import fresh_db  # noqa: E401,F401  (autouse: временная БД)


def _client():
    from fastapi.testclient import TestClient
    from core.api.app import app
    return TestClient(app, client=("127.0.0.1", 5555), base_url="http://testserver")


# ------------------------- 1. алиас name → title -------------------------
def test_debt_accepts_legacy_name_field():
    r = _client().post("/api/finance/debts", json={"name": "Тест кредитка", "total": 10000})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Тест кредитка"


def test_debt_without_title_still_422():
    r = _client().post("/api/finance/debts", json={"total": 10000})
    assert r.status_code == 422


def test_recurring_accepts_legacy_name_field():
    r = _client().post("/api/finance/recurring", json={"name": "Тест подписка", "amount": 100})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Тест подписка"


def test_recurring_without_title_still_422():
    assert _client().post("/api/finance/recurring", json={"amount": 100}).status_code == 422


def test_title_wins_over_legacy_name():
    r = _client().post("/api/finance/debts", json={"title": "Правильный", "name": "Левый", "total": 1})
    assert r.status_code == 200 and r.json()["title"] == "Правильный"


# ------------------------- 2. регулярный доход и ?all=true -------------------------
def _add_income(title="Зарплата", amount=100000, day=5):
    r = _client().post("/api/finance/recurring",
                       json={"title": title, "amount": amount, "day": day, "kind": "income"})
    assert r.status_code == 200, r.text
    return r.json()


def test_recurring_income_created_as_income():
    row = _add_income()
    assert row["kind"] == "income" and row["active"] is not False


def test_all_param_shows_paused_rows():
    row = _add_income()
    assert row["id"] in [x["id"] for x in _client().get("/api/finance/recurring").json()]
    # поставили на паузу — обычный список её больше не отдаёт (как раньше)
    assert _client().put(f"/api/finance/recurring/{row['id']}", json={"active": False}).status_code == 200
    base = [x["id"] for x in _client().get("/api/finance/recurring").json()]
    assert row["id"] not in base
    # ?all=true — видна, иначе UI не сможет вернуть её в расчёт
    assert row["id"] in [x["id"] for x in _client().get("/api/finance/recurring?all=true").json()]


def test_income_recurrence_moves_cashflow_and_forecast():
    from core.services import finance, insights
    finance.set_balance("Т-Банк", 10000)
    cf_before = finance.cashflow()
    _add_income(amount=145000)
    cf = finance.cashflow()
    # регулярный доход входит в месячный поток и снимает пометку «доход — оценка»
    assert cf["income"] >= cf_before["income"] + 145000
    assert cf["income_is_estimate"] is False
    f = insights.cash_forecast(30)
    assert f["next_income"] is not None, "прогноз должен знать дату ближайшего дохода"
    assert f["days_to_income"] is not None and f["safe_per_day"] is not None


def test_paused_income_leaves_forecast():
    from core.services import finance, insights
    finance.set_balance("Т-Банк", 10000)
    row = _add_income(amount=145000)
    assert insights.cash_forecast(30)["next_income"] is not None
    _client().put(f"/api/finance/recurring/{row['id']}", json={"active": False})
    assert insights.cash_forecast(30)["next_income"] is None
    assert finance.cashflow()["income_is_estimate"] is True
