"""Связка долг <-> кредитка через API (полигон polish-20261010).

POST /api/finance/accounts/{id}/link-debt связывает,
GET /api/finance/debts отдаёт linked_account,
DELETE /api/finance/accounts/{id}/link-debt отвязывает.
"""
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402

from core import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlmodel import create_engine
    from sqlalchemy import event

    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


def test_link_debt_api():
    from fastapi.testclient import TestClient

    from core.api.app import app

    c = TestClient(app)

    # долг + кредитка
    r = c.post("/api/finance/debts", json={"title": "Сбер кредит", "total": 100000, "payment": 8000})
    assert r.status_code == 200, r.text
    debt = r.json()
    debt_id = debt["id"]

    r = c.post("/api/finance/accounts", json={"name": "Кредитка Сбера", "kind": "debt_only", "balance": 0})
    assert r.status_code == 200, r.text
    acc = r.json()
    acc_id = acc["id"]

    # связка
    r = c.post(f"/api/finance/accounts/{acc_id}/link-debt", json={"debt_id": debt_id})
    assert r.status_code == 200, r.text
    linked = r.json()
    assert linked["debt_id"] == debt_id

    # GET /debts содержит linked_account
    r = c.get("/api/finance/debts")
    assert r.status_code == 200, r.text
    row = next(d for d in r.json() if d["id"] == debt_id)
    assert row["linked_account"] is not None, row
    assert row["linked_account"]["id"] == acc_id

    # счёт тоже хранит debt_id
    r = c.get("/api/finance/accounts")
    assert r.status_code == 200, r.text
    acc_row = next(a for a in r.json() if a["id"] == acc_id)
    assert acc_row["debt_id"] == debt_id

    # отвязка
    r = c.delete(f"/api/finance/accounts/{acc_id}/link-debt")
    assert r.status_code == 200, r.text

    r = c.get("/api/finance/debts")
    assert r.status_code == 200, r.text
    row = next(d for d in r.json() if d["id"] == debt_id)
    assert row["linked_account"] is None, row
