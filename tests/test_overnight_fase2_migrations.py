"""ФАЗА 2 overnight-crm: WAL+busy_timeout, schema_version/миграции, read-only экспорт.

Миграции проверяются на временной копии БД (временный файл), реальная data/ не трогается.
"""
import os
import sqlite3

import pytest

os.environ.setdefault("ASSISTANT_TEST", "1")

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


# ---------------------------------------------------------------- 4. WAL и busy_timeout
def test_sqlite_pragmas_wal_and_busy_timeout():
    from sqlalchemy import text
    with db.engine.connect() as conn:
        assert str(conn.execute(text("PRAGMA journal_mode")).scalar()).lower() == "wal"
        assert conn.execute(text("PRAGMA busy_timeout")).scalar() == 5000


# ---------------------------------------------------------------- 5. schema_version и миграции
def test_fresh_db_has_schema_version():
    from sqlalchemy import text
    with db.engine.connect() as conn:
        assert conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar() == 1


def test_migrations_apply_on_existing_copy_with_backup(tmp_path):
    """Существующая БД с данными: применяем миграцию на КОПИИ, данные целы, бэкап создан."""
    from sqlalchemy import create_engine, text
    from core import migrations

    db_file = tmp_path / "copy.db"
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE orders (id INTEGER PRIMARY KEY, title TEXT)")
    con.execute("INSERT INTO orders (title) VALUES ('старый заказ')")
    con.commit()
    con.close()

    eng = create_engine(f"sqlite:///{db_file}")
    result = migrations.apply(eng, had_db=True, backup_dir=tmp_path / "bk")

    assert result["applied"] == [1]
    assert migrations.current_version(eng) == 1
    assert result["backup"] and os.path.exists(result["backup"])
    with eng.connect() as conn:
        assert conn.execute(text("SELECT title FROM orders")).scalar() == "старый заказ"
    # идемпотентно: повторный запуск ничего не делает и не бэкапит
    again = migrations.apply(eng, had_db=True, backup_dir=tmp_path / "bk")
    assert again["applied"] == [] and again["backup"] is None


def test_migrations_skip_backup_on_fresh_db(tmp_path):
    from sqlalchemy import create_engine
    from core import migrations
    eng = create_engine(f"sqlite:///{tmp_path / 'new.db'}")
    result = migrations.apply(eng, had_db=False, backup_dir=tmp_path / "bk")
    assert result["applied"] == [1] and result["backup"] is None


# ---------------------------------------------------------------- 3. экспорт (только чтение)
def test_export_endpoints_read_only():
    from core.services import finance, orders
    o = orders.add_order("Ролик для Пятёрочки", 25000, status="work")
    finance.add_transaction(700, "expense", "Транспорт", "такси", source="web")
    finance.add_transaction(25000, "income", "Фриланс", "аванс по заказу", order_id=o.id, source="web")

    c = _client()
    r = c.get("/api/export/orders.csv")
    assert r.status_code == 200 and "Ролик для Пятёрочки" in r.text
    r = c.get("/api/export/transactions.csv")
    assert r.status_code == 200 and "такси" in r.text
    r = c.get("/api/export/operations.json")           # алиас операций
    assert r.status_code == 200 and "такси" in r.text
    r = c.get("/api/export/all.json")
    assert r.status_code == 200 and "orders" in r.json() and "transactions" in r.json()
