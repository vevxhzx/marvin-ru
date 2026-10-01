"""ФАЗА 4 overnight-crm: воронка стадий, карточки, платежи (частичные/идемпотентные),
миграция существующих данных на КОПИИ БД, аналитика и API.

Реальная data/ не трогается: свежая временная БД + отдельная копия для миграции.
"""
import os
import sqlite3
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


def _client():
    from fastapi.testclient import TestClient
    from core.api.app import app
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 5555))


def _j(r):
    assert r.status_code < 400, (r.status_code, r.text)
    return r.json()


# ---------------------------------------------------------------- A. воронка
def test_stage_transitions_sync_status_and_revisions():
    from core.crm import service, stages
    from core.services import orders
    o = orders.add_order("Ролик", 25000, "Пятёрочка", status="work")
    assert orders.get_order(o.id).stage == "in_work"

    service.set_stage(o.id, "negotiation")
    assert (orders.get_order(o.id).stage, orders.get_order(o.id).status) == ("negotiation", "new")

    service.set_stage(o.id, "revisions")
    service.set_stage(o.id, "revisions")           # повторный вход в правки не должен крутить счётчик дальше
    assert orders.get_order(o.id).revisions == 1

    service.set_stage(o.id, "lost", lost_reason="ушёл к другим")
    got = orders.get_order(o.id)
    assert got.status == "cancelled" and got.lost_reason == "ушёл к другим"

    service.set_stage(o.id, "paid")
    got = orders.get_order(o.id)
    assert got.status == "paid" and got.paid_at is not None and got.lost_reason is None

    with pytest.raises(orders.OrderError):
        service.set_stage(o.id, "не-стадия")
    assert stages.label("awaiting_payment") == "ждёт оплаты"


def test_existing_status_maps_to_stage_without_loss():
    from core.services import orders
    pairs = {"new": "lead", "work": "in_work", "review": "revisions", "done": "delivered", "paid": "paid", "cancelled": "lost"}
    for status, stage in pairs.items():
        o = orders.add_order(f"Заказ {status}", 1000, status=status)
        assert orders.get_order(o.id).stage == stage
        assert orders.order_view(o)["status"] == status      # старый статус не потерян


# ---------------------------------------------------------------- F. деньги
def test_partial_and_idempotent_payments():
    from core.crm import service
    from core.services import orders
    o = orders.add_order("Монтаж", 25000, "Иванов", status="delivered")

    r1 = service.payment(o.id, 10000, idem_key="pay-1")
    assert r1["duplicate"] is False and r1["order"]["left"] == 15000
    r2 = service.payment(o.id, 10000, idem_key="pay-1")      # повтор того же запроса
    assert r2["duplicate"] is True
    assert r2["order"]["paid"] == 10000
    assert len(orders.payments_for(o.id)) == 1               # второго дохода нет

    r3 = service.payment(o.id, 15000)                        # полная оплата закрывает заказ
    assert r3["order"]["left"] == 0 and orders.get_order(o.id).status == "paid"
    assert len(orders.payments_for(o.id)) == 2

    # доход реально в финансах и один раз
    from core.db import Transaction, session
    from sqlmodel import select
    with session() as s:
        txs = s.exec(select(Transaction).where(Transaction.order_id == o.id, Transaction.kind == "income")).all()
    assert sum(t.amount for t in txs) == 25000


# ---------------------------------------------------------------- H. миграция на копии
def test_migration_existing_db_copy(tmp_path):
    from sqlalchemy import create_engine, text
    from core import migrations

    db_file = tmp_path / "old.db"
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE \"order\" (id INTEGER PRIMARY KEY, title TEXT, price FLOAT, status TEXT)")
    con.execute("INSERT INTO \"order\" (title, price, status) VALUES ('Старый ролик', 15000, 'done')")
    con.execute("INSERT INTO \"order\" (title, price, status) VALUES ('Текущий', 5000, 'work')")
    con.commit(); con.close()

    eng = create_engine(f"sqlite:///{db_file}")
    res = migrations.apply(eng, had_db=True, backup_dir=tmp_path / "bk")
    assert res["applied"] == [1, 2, 3] and res["backup"] and os.path.exists(res["backup"])

    with eng.connect() as conn:
        cols = {r[1] for r in conn.execute(text('PRAGMA table_info("order")')).all()}
        assert {"stage", "revisions", "lost_reason", "next_step"}.issubset(cols)
        rows = {r[0]: r[1] for r in conn.execute(text('SELECT title, stage FROM "order"')).all()}
        assert rows["Старый ролик"] == "delivered" and rows["Текущий"] == "in_work"
        assert conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar() == 3

    again = migrations.apply(eng, had_db=True, backup_dir=tmp_path / "bk")
    assert again["applied"] == [] and again["backup"] is None


# ---------------------------------------------------------------- D/C. карточки
def test_order_and_customer_cards():
    from core.crm import service
    from core.services import orders
    o = orders.add_order("Логотип", 30000, "Ромашка", status="delivered")
    service.payment(o.id, 15000)
    service.add_check(o.id, "Согласовать ТЗ")
    service.toggle_check(service.checklist(o.id)[0]["id"])
    service.add_comment(o.id, "первый вариант готов")

    card = service.order_card(o.id)
    assert card["prepaid"] == 15000 and card["remaining"] == 15000
    assert len(card["payments"]) == 1 and card["checklist"][0]["done"] is True
    assert card["comments"][0]["text"] == "первый вариант готов"
    assert any(a["kind"] == "payment" for a in card["activity"])

    cc = service.customer_card(o.client_id)
    assert cc["ltv"] == 15000 and cc["debt"] == 15000 and cc["orders_count"] == 1
    assert cc["avg_check"] == 30000
    service.update_client_fields(o.client_id, source="рекомендация", next_step="позвонить")
    cc = service.customer_card(o.client_id)
    assert cc["source"] == "рекомендация" and cc["next_step"] == "позвонить"


# ---------------------------------------------------------------- E. follow-up
def test_followup_scan_and_templates():
    from core.crm import service
    from core.services import orders
    o = orders.add_order("Просроченный", 5000, "Клиент", deadline=datetime.now() - timedelta(days=2), status="work")
    created = service.scan()
    assert any(f["kind"] == "overdue" and f["order_id"] == o.id for f in created)
    # повторный скан не плодит дубли
    assert service.scan() == []
    f = service.followups()[0]
    service.complete_followup(f["id"])
    assert all(x["done"] for x in service.followups(only_open=False) if x["id"] == f["id"])
    tpl = service.templates(o.id)
    assert "Просроченный" in tpl["payment"] and "payment" in tpl and "silent" in tpl


# ---------------------------------------------------------------- G. аналитика (read-only)
def test_analytics_read_only():
    from core.crm import service
    from core.services import orders
    o = orders.add_order("Сдан", 20000, "А", status="delivered")
    service.payment(o.id, 20000)
    orders.add_order("Потерян", 3000, "Б", status="cancelled")
    a = service.analytics()
    assert a["counts"]["paid"] == 1 and a["counts"]["lost"] == 1
    assert a["avg_check"] == 20000
    assert len(a["funnel"]) == 9 and a["top"][0]["revenue"] == 20000


# ---------------------------------------------------------------- API
def test_crm_api_endpoints():
    c = _client()
    o = _j(c.post("/api/orders", json={"title": "Ролик", "price": 25000, "client": "Пятёрочка", "status": "work"}))
    oid = o["id"]

    board = _j(c.get("/api/crm/board"))
    assert any(col["stage"] == "in_work" and col["orders"] for col in board["columns"])
    assert len(_j(c.get("/api/crm/stages"))["stages"]) == 9

    _j(c.put(f"/api/crm/orders/{oid}/stage", json={"stage": "delivered"}))
    assert _j(c.get(f"/api/crm/orders/{oid}/card"))["status"] == "done"

    pay = _j(c.post(f"/api/crm/orders/{oid}/payments", json={"amount": 5000, "idem_key": "api-1"}))
    assert pay["duplicate"] is False and pay["order"]["left"] == 20000
    pay2 = _j(c.post(f"/api/crm/orders/{oid}/payments", json={"amount": 5000, "idem_key": "api-1"}))
    assert pay2["duplicate"] is True and pay2["order"]["paid"] == 5000

    _j(c.post(f"/api/crm/orders/{oid}/comments", json={"text": "ок"}))
    _j(c.post(f"/api/crm/orders/{oid}/checklist", json={"title": "этап"}))
    card = _j(c.get(f"/api/crm/orders/{oid}/card"))
    assert card["comments"][0]["text"] == "ок" and len(card["checklist"]) == 1

    cid = o["client_id"]
    assert cid
    cc = _j(c.get(f"/api/crm/clients/{cid}/card"))
    assert cc["ltv"] == 5000
    _j(c.put(f"/api/crm/clients/{cid}", json={"source": "сарафан", "next_step": "напомнить"}))

    _j(c.post("/api/crm/followups", json={"text": "позвонить", "order_id": oid}))
    assert len(_j(c.get("/api/crm/followups"))) == 1
    assert "payment" in _j(c.get("/api/crm/templates"))
    assert "funnel" in _j(c.get("/api/crm/analytics"))
