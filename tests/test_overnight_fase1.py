"""ФАЗА 1 overnight-crm: баги (единый баланс, склонения, просрочка, «ждут оплаты»).

Только регрессии на то, что поправили: один источник баланса, русские формы числа,
флаг просрочки и честный «остаток ждёт оплаты» (paid_at = деньги получены).
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


def _client():
    from fastapi.testclient import TestClient
    from core.api.app import app
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 5555))


def _j(r):
    assert r.status_code < 400, (r.status_code, r.text)
    return r.json()


# ---------------------------------------------------------------- 1. баланс
def test_balance_has_one_source():
    """Главная (/api/dashboard) и финансы (/api/finance/summary) обязаны совпадать
    и совпадать с finance.total_balance(); долговой счёт в баланс не входит."""
    from core.services import finance
    finance.set_balance("Т-Банк", 377)           # главный счёт уже заведён init_db
    finance.add_account("отложенные", "bank", 6)
    finance.add_account("Долг", "debt_only", 999)   # не должен попасть в баланс

    assert finance.total_balance() == 383
    s = finance.summary()
    assert s["total_balance"] == 383 and s["balance"] == 383

    c = _client()
    assert _j(c.get("/api/finance/summary"))["total_balance"] == 383
    assert _j(c.get("/api/dashboard"))["finance"]["balance"] == 383


# ---------------------------------------------------------------- 2. склонения
def test_russian_plurals():
    from core.services import plural
    assert (plural.days(1), plural.days(2), plural.days(5), plural.days(11), plural.days(21)) == ("день", "дня", "дней", "дней", "день")
    assert (plural.hours(1), plural.hours(3), plural.hours(5)) == ("час", "часа", "часов")
    assert plural.tasks_word(2) == "задачи" and plural.tasks_word(5) == "задач"
    assert plural.events_word(1) == "событие" and plural.events_word(3) == "события"
    assert plural.orders_word(1) == "заказ" and plural.orders_word(7) == "заказов"


# ---------------------------------------------------------------- 4. просрочка и оплата
def test_overdue_order_flag():
    from core.services import orders
    past = datetime.now() - timedelta(days=2)
    o = orders.add_order("Старый ролик", 1500, status="work", deadline=past)
    v = orders.order_view(orders.get_order(o.id))
    assert v["overdue"] is True
    orders.update_order(o.id, status="done")
    v = orders.order_view(orders.get_order(o.id))
    assert v["overdue"] is False        # сдан — не просрочка


def test_unpaid_total_ignores_paid_at():
    """«Ждут оплаты» — остаток по незакрытым; заказ с отметкой paid_at (деньги получены)
    больше не висит в этой сумме, даже если статус вернули в работу."""
    from core.services import orders
    a = orders.add_order("Первый", 1500, status="work")
    b = orders.add_order("Второй", 1500, status="work")
    assert orders.unpaid_total() == 3000

    orders.update_order(b.id, status="paid")     # ставит paid_at
    orders.update_order(b.id, status="work")     # статус вернули, деньги уже получены
    v = orders.order_view(orders.get_order(b.id))
    assert v["left"] == 0 and v["paid_at"]
    assert orders.unpaid_total() == 1500
