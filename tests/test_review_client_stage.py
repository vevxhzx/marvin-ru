"""Стадия КЛИЕНТА (CRM): авто-переходы по заказам, приоритет ручного значения,
снятие ручного режима, идемпотентность миграции v3 на ВРЕМЕННОЙ копии БД,
обратная совместимость старых записей (stage пуст) и API.

Реальная `data/*.db` не открывается: все проверки — на временных БД в tmp_path.
"""
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

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


def _backdate(order_id: int, days: int) -> None:
    from core.db import Order, session
    with session() as s:
        o = s.get(Order, order_id)
        o.created_at = datetime.now() - timedelta(days=days)
        o.last_contact_at = o.created_at
        s.add(o); s.commit()


def _backdate_client(client_id: int, days: int) -> None:
    from core.db import Client, session
    with session() as s:
        c = s.get(Client, client_id)
        c.created_at = datetime.now() - timedelta(days=days)
        c.last_contact_at = None
        s.add(c); s.commit()


# ---------------------------------------------------------------- 1. чистые правила
def test_auto_stage_is_a_pure_function():
    from core.crm import client_stages as cs
    ref = datetime(2026, 10, 1)
    assert cs.auto_stage(paid_orders=0, last_activity=ref - timedelta(days=10), now_dt=ref) is None
    assert cs.auto_stage(paid_orders=0, last_activity=None, now_dt=ref) is None
    assert cs.auto_stage(paid_orders=1, last_activity=ref, now_dt=ref) == "client"
    assert cs.auto_stage(paid_orders=2, last_activity=ref, now_dt=ref) == "permanent"
    assert cs.auto_stage(paid_orders=7, last_activity=ref, now_dt=ref) == "permanent"
    # нет заказов 90 дней → «спит/ушёл» (граница: ровно 90 дней — уже спит)
    assert cs.auto_stage(paid_orders=0, last_activity=ref - timedelta(days=89), now_dt=ref) is None
    assert cs.auto_stage(paid_orders=0, last_activity=ref - timedelta(days=90), now_dt=ref) == "asleep"
    assert cs.auto_stage(paid_orders=0, last_activity=ref - timedelta(days=200), now_dt=ref) == "asleep"
    # оплата важнее «спит» (приоритет постоянный → клиент → спит)
    assert cs.auto_stage(paid_orders=3, last_activity=ref - timedelta(days=400), now_dt=ref) == "permanent"
    # справочник: 5 стадий клиента
    assert [k for k, _ in cs.CLIENT_STAGES] == ["lead", "negotiation", "client", "permanent", "asleep"]
    assert cs.label("asleep") == "спит/ушёл"
    assert cs.is_client_stage("client") and not cs.is_client_stage("в работе")


def test_resolve_keeps_legacy_records_on_auto():
    from core.crm import client_stages as cs
    assert cs.resolve("", False, "client") == "client"          # старая запись без стадии
    assert cs.resolve(None, False, None) == "lead"              # вообще ничего → «лид»
    assert cs.resolve("negotiation", True, "client") == "negotiation"   # ручная приоритетнее
    assert cs.resolve("negotiation", False, "client") == "negotiation"  # сохранённое не перетираем


# ---------------------------------------------------------------- 2. авто-переходы от заказов
def test_paid_order_moves_client_to_client_stage():
    from core.crm import client_stages as cs
    from core.services import orders
    o = orders.add_order("Ролик", 25000, "Пятёрочка", status="work")
    assert cs.get(o.client_id)["stage"] == "lead"            # оплаты нет — «лид»

    from core.crm import service
    service.payment(o.id, 25000)                              # авто-пересчёт после оплаты
    got = cs.get(o.client_id)
    assert got["stage"] == "client" and got["label"] == "клиент"
    assert got["manual"] is False and got["paid_orders"] == 1
    assert cs.recalc(o.client_id)["stage"] == "client"       # повторный пересчёт — то же самое


def test_two_paid_orders_move_client_to_permanent():
    from core.crm import client_stages as cs
    from core.crm import service
    from core.services import orders
    o1 = orders.add_order("Первый", 10000, "Ромашка", status="delivered")
    service.payment(o1.id, 10000)
    o2 = orders.add_order("Второй", 12000, "Ромашка", status="delivered")
    service.payment(o2.id, 12000)
    got = cs.get(o1.client_id)
    assert got["stage"] == "permanent" and got["label"] == "постоянный"
    assert got["paid_orders"] == 2 and got["orders_count"] == 2 and got["paid_total"] == 22000


def test_no_orders_90_days_moves_client_to_asleep():
    from core.crm import client_stages as cs
    from core.services import orders
    o = orders.add_order("Давний", 5000, "Тихий", status="work")
    cid = o.client_id
    _backdate(o.id, 120)
    _backdate_client(cid, 200)
    got = cs.recalc(cid)
    assert got["stage"] == "asleep" and got["label"] == "спит/ушёл"
    assert got["days_since"] >= 90 and got["auto"] == "asleep"

    # свежий заказ без оплаты — авто-сигнала нет, значение не перетирается
    o2 = orders.add_order("Свежий", 5000, "Свежий", status="work")
    assert cs.recalc(o2.client_id)["note"].startswith("авто-сигнала нет")
    assert cs.recalc(o2.client_id)["stage"] == "lead"


# ---------------------------------------------------------------- 3. ручное значение приоритетнее
def test_manual_stage_wins_and_can_be_cleared():
    from core.crm import client_stages as cs
    from core.crm import service
    from core.services import orders
    o = orders.add_order("Договор", 30000, "Сложный", status="delivered")
    service.payment(o.id, 30000)                              # авто = «клиент»
    assert cs.get(o.client_id)["stage"] == "client"

    manual = cs.set_stage(o.client_id, "negotiation")         # выставили руками
    assert manual["stage"] == "negotiation" and manual["manual"] is True

    # авто-пересчёт НЕ перетирает ручное значение, но обновляет stage_auto
    again = cs.recalc(o.client_id)
    assert again["stage"] == "negotiation" and again["manual"] is True
    assert again["auto"] == "client" and again["note"].startswith("ручная")
    assert cs.get(o.client_id)["stored"] == "negotiation"

    # «вернуть авто»: ручной режим снят, значение пересчитано по заказам
    back = cs.clear_manual(o.client_id)
    assert back["was_manual"] is True and back["manual"] is False
    assert back["stage"] == "client" and back["auto"] == "client"

    with pytest.raises(cs.ClientStageError):
        cs.set_stage(o.client_id, "оплачен")


def test_no_auto_signal_keeps_value_after_undoing_manual():
    from core.crm import client_stages as cs
    from core.services import orders
    o = orders.add_order("Обсуждаем", 8000, "Лид номер один", status="work")
    cs.set_stage(o.client_id, "negotiation")
    back = cs.clear_manual(o.client_id)                       # авто-сигнала нет → не перетираем
    assert back["stage"] == "negotiation" and back["manual"] is False
    assert back["auto"] == "" and back["changed"] is False
    assert back["note"].startswith("авто-сигнала нет")


# ---------------------------------------------------------------- 4. обратная совместимость
def test_legacy_client_without_stage_uses_auto_logic():
    from core.crm import client_stages as cs
    from core.crm import service
    from core.services import orders
    o = orders.add_order("Старый заказ", 5000, "Давний клиент", status="paid")

    # эмулируем запись до миграции: стадии в БД нет, колонка пустая
    from core.db import Client, session
    with session() as s:
        c = s.get(Client, o.client_id)
        c.stage, c.stage_manual, c.stage_auto = "", False, ""
        s.add(c); s.commit()

    # чтение ничего не меняет, но показывает авто-стадию
    got = cs.get(o.client_id)
    assert got["stage"] == "client" and got["stored"] == "" and got["changed"] is True
    with session() as s:
        assert (s.get(Client, o.client_id).stage or "") == ""

    # пересчёт дописывает авто-стадию, данные клиента не теряются
    r = cs.recalc(o.client_id)
    assert r["stage"] == "client" and r["changed"] is True
    with session() as s:
        c = s.get(Client, o.client_id)
        assert c.stage == "client" and c.stage_manual is False and c.name == "Давний клиент"
    # карточка клиента отдаёт стадию (аддитивное поле)
    card = service.customer_card(o.client_id)
    assert card["stage"]["stage"] == "client" and card["client"]["name"] == "Давний клиент"


# ---------------------------------------------------------------- 5. миграция v3 (аддитивная/идемпотентная)
def _old_db(path: Path) -> None:
    """Старая БД (до миграции v3): таблица client без новых колонок + данные."""
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE client (id INTEGER PRIMARY KEY, name TEXT, contact TEXT, kind TEXT,"
                " tags TEXT, created_at DATETIME)")
    con.execute("INSERT INTO client (name, contact, kind, created_at)"
                " VALUES ('Иван', '@ivan', 'client', '2025-01-01 10:00:00')")
    con.execute("CREATE TABLE \"order\" (id INTEGER PRIMARY KEY, title TEXT, client_id INTEGER, price FLOAT, status TEXT)")
    con.execute("INSERT INTO \"order\" (title, client_id, price, status) VALUES ('Старый ролик', 1, 15000, 'paid')")
    con.commit(); con.close()


def test_migration_v3_additive_and_idempotent_on_copy(tmp_path):
    from sqlalchemy import create_engine, text
    from core import migrations

    real = Path(__file__).resolve().parents[1] / "data" / "jarvis.db"
    before = real.stat().st_mtime if real.exists() else None

    db_file = tmp_path / "copy.db"
    _old_db(db_file)
    eng = create_engine(f"sqlite:///{db_file}")

    res = migrations.apply(eng, had_db=True, backup_dir=tmp_path / "bk")
    all_versions = [v for v, _, _ in migrations.MIGRATIONS]
    assert res["applied"] == all_versions and res["backup"] and os.path.exists(res["backup"])
    assert str(tmp_path) in res["backup"]                      # бэкап только во временную папку

    with eng.connect() as conn:
        cols = {r[1] for r in conn.execute(text('PRAGMA table_info("client")')).all()}
        assert {"stage", "stage_manual", "stage_auto", "stage_updated_at"}.issubset(cols)
        # старые данные целы, новые колонки — с дефолтами
        row = conn.execute(text("SELECT name, contact, kind, stage, stage_manual, stage_auto FROM client")).all()
        assert row[0][0] == "Иван" and row[0][1] == "@ivan" and row[0][2] == "client"
        assert (row[0][3] or "") == "" and not row[0][4] and (row[0][5] or "") == ""
        assert conn.execute(text('SELECT title FROM "order" WHERE status=\'paid\'')).scalar() == "Старый ролик"
        assert conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar() == max(
            v for v, _, _ in migrations.MIGRATIONS)

    # идемпотентно: повторный запуск — no-op, без бэкапа
    again = migrations.apply(eng, had_db=True, backup_dir=tmp_path / "bk")
    assert again["applied"] == [] and again["backup"] is None
    assert migrations.current_version(eng) == all_versions[-1]

    # реальная БД не открывалась
    if before is not None:
        assert real.stat().st_mtime == before


def test_migration_v3_noop_without_client_table(tmp_path):
    """Нет таблицы client — миграция не падает (минимальная старая БД)."""
    from sqlalchemy import create_engine, text
    from core import migrations
    db_file = tmp_path / "min.db"
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE \"order\" (id INTEGER PRIMARY KEY, title TEXT, status TEXT)")
    con.commit(); con.close()
    eng = create_engine(f"sqlite:///{db_file}")
    assert migrations.apply(eng, had_db=True, backup_dir=tmp_path / "bk")["applied"] == [
        v for v, _, _ in migrations.MIGRATIONS]
    with eng.connect() as conn:
        assert {r[1] for r in conn.execute(text('PRAGMA table_info("order")')).all()} >= {"stage"}


# ---------------------------------------------------------------- 6. API
def test_client_stage_api():
    c = _client()
    ref = _j(c.get("/api/crm/client-stages"))
    assert [s["stage"] for s in ref["stages"]] == ["lead", "negotiation", "client", "permanent", "asleep"]
    assert ref["sleeper_days"] == 90 and ref["permanent_paid_orders"] == 2

    o = _j(c.post("/api/orders", json={"title": "Монтаж", "price": 40000, "client": "Пятёрочка", "status": "delivered"}))
    cid = _j(c.get(f"/api/crm/orders/{o['id']}/card"))["client_id"]

    # прочитать стадию
    got = _j(c.get(f"/api/crm/clients/{cid}/stage"))
    assert got["stage"] == "lead" and got["manual"] is False and got["paid_orders"] == 0

    # поставить вручную + приоритет ручного
    man = _j(c.put(f"/api/crm/clients/{cid}/stage", json={"stage": "negotiation"}))
    assert man["stage"] == "negotiation" and man["manual"] is True
    assert _j(c.post(f"/api/crm/clients/{cid}/stage/recalc"))["stage"] == "negotiation"
    assert _j(c.get(f"/api/crm/clients/{cid}/stage"))["auto"] == ""   # авто-сигнала нет (нет оплат)

    # снять ручной режим: авто-сигнала нет (оплат не было) → значение сохраняется
    back = _j(c.delete(f"/api/crm/clients/{cid}/stage/manual"))
    assert back["was_manual"] is True and back["manual"] is False
    assert back["stage"] == "negotiation" and back["auto"] == ""
    assert back["note"].startswith("авто-сигнала нет")

    # неизвестная стадия → 400, неизвестный клиент → 404
    assert c.put(f"/api/crm/clients/{cid}/stage", json={"stage": "оплачен"}).status_code == 400
    assert c.get("/api/crm/clients/999999/stage").status_code == 404

    # карточка клиента отдаёт стадию (аддитивное поле)
    card_stage = _j(c.get(f"/api/crm/clients/{cid}/card"))["stage"]
    assert card_stage["stage"] == "negotiation" and card_stage["manual"] is False

    # массовый пересчёт
    allr = _j(c.post("/api/crm/client-stages/recalc"))
    assert allr["total"] >= 1 and "updated" in allr and "manual_skipped" in allr


def test_api_recalc_after_payment_and_404s():
    c = _client()
    o = _j(c.post("/api/orders", json={"title": "Сайт", "price": 50000, "client": "Гараж", "status": "delivered"}))
    cid = _j(c.get(f"/api/crm/orders/{o['id']}/card"))["client_id"]
    _j(c.post(f"/api/crm/orders/{o['id']}/payments", json={"amount": 50000, "idem_key": "stg-1"}))
    assert _j(c.get(f"/api/crm/clients/{cid}/stage"))["stage"] == "client"
    assert c.post("/api/crm/clients/999999/stage/recalc").status_code == 404
    assert c.delete("/api/crm/clients/999999/stage/manual").status_code == 404
    # старые эндпоинты клиентов/заказов на месте и не переименованы
    assert c.get("/api/crm/stages").status_code == 200 and len(_j(c.get("/api/crm/stages"))["stages"]) == 9
    assert c.get("/api/orders").status_code == 200
