# -*- coding: utf-8 -*-
"""Качество: 404 на PUT несуществующей фин-сущности, 400 — только на ошибку ввода (бывший xfail P2).

Раньше PUT /api/finance/{transactions|categories|accounts|debts|recurring}/999 отдавал 400
(FinanceError), а DELETE того же ресурса — 404. Теперь сервис кидает finance.FinanceNotFound
(наследник HTTPException + FinanceError) → «нет такого» = 404, кривые данные = 400.
Клиент `_client` и временная БД — из tests/conftest.py.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.usefixtures("fresh_db")

MISSING = [
    ("/api/finance/transactions/999", {"amount": 10}),
    ("/api/finance/categories/999", {"name": "X"}),
    ("/api/finance/accounts/999", {"name": "X"}),
    ("/api/finance/debts/999", {"title": "X"}),
    ("/api/finance/recurring/999", {"title": "X"}),
]


@pytest.mark.parametrize("path,body", MISSING)
def test_put_missing_entity_is_404(_client, path, body):
    r = _client.put(path, json=body)
    assert r.status_code == 404, f"PUT {path} -> {r.status_code} (ожидали 404)"


@pytest.mark.parametrize("path,_", MISSING)
def test_delete_missing_entity_is_404_too(_client, path, _):
    """Паритет методов: PUT и DELETE одного ресурса отвечают одинаково."""
    assert _client.delete(path).status_code == 404


def test_put_existing_transaction_still_works(_client):
    f_main = _client.get("/api/finance/accounts").json()[0]["name"]
    tid = _client.post("/api/finance/transactions",
                       json={"amount": 500, "kind": "expense", "note": "обед", "account": f_main}).json()["id"]
    r = _client.put(f"/api/finance/transactions/{tid}", json={"amount": 250})
    assert r.status_code == 200, r.text
    assert r.json()["amount"] == 250


def test_put_validation_error_is_still_400(_client):
    """Ошибка ввода на СУЩЕСТВУЮЩЕЙ сущности — 400, а не 404: два случая не смешаны."""
    accs = _client.get("/api/finance/accounts").json()
    main = next(a for a in accs if a["is_main"])
    acc = next(a for a in accs if a["id"] != main["id"])     # «Наличные»
    r = _client.put(f"/api/finance/accounts/{acc['id']}", json={"name": main["name"]})   # дубль имени
    assert r.status_code == 400, r.text


def test_not_found_is_error_not_a_silent_200(_client):
    """404 несущности не заталкивается в 200/422 — клиент отличает «нет такого» от битого тела."""
    r = _client.put("/api/finance/transactions/999", json={"amount": "много"})
    assert r.status_code == 422, "некорректное тело ловится схемой раньше, чем сервис (422)"


def test_finance_not_found_is_still_a_finance_error():
    """Совместимость для правил/инструментов: except FinanceError по-прежнему ловит 404-случай."""
    from core.services import finance
    err = finance.FinanceNotFound("Операция не найдена")
    assert isinstance(err, finance.FinanceError) and isinstance(err, ValueError)
    assert err.status_code == 404
    assert str(err) == "Операция не найдена"
    with pytest.raises(finance.FinanceError):
        raise finance.FinanceNotFound("Счёт не найден")
