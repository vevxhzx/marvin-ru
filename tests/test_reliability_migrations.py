"""Надёжность миграций: составные индексы v4, PRAGMA, идемпотентность apply(),
громкое чтение битой таблицы schema_version и флаг `migration:error` в /api/status."""
from __future__ import annotations

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import create_engine

from core import migrations


def test_fresh_db_has_v4_indexes_and_pragmas(fresh_db):
    """На свежей БД созданы составные индексы v4 и PRAGMA synchronous=NORMAL."""
    from core import db as dbm

    with dbm.engine.connect() as conn:
        names = {r[0] for r in conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
        assert "ix_transaction_account" in names       # v4: финансы по счёту
        assert "ix_task_done_due" in names             # v4: задачи «свежие + не сделаны»
        assert "ix_chatmessage_role_created_at" in names
        assert "ix_actionlog_kind" in names
        # PRAGMA synchronous = NORMAL (1) — см. db._pragmas
        assert conn.exec_driver_sql("PRAGMA synchronous").fetchone()[0] == 1


def test_apply_is_idempotent_and_covers_all_migrations(tmp_path):
    """apply() на пустой БД применяет ВСЕ миграции, повторный вызов — ничего (идемпотентно)."""
    eng = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    all_versions = [v for v, _, _ in migrations.MIGRATIONS]

    res = migrations.apply(eng, had_db=False)
    assert res["applied"] == all_versions
    assert migrations.current_version(eng) == max(all_versions)
    res2 = migrations.apply(eng, had_db=False)      # повторный запуск ничего не применяет
    assert res2["applied"] == [] and res2["from"] == res2["to"] == max(all_versions)
    assert migrations.pending(eng) == []
    assert migrations.apply(eng, had_db=True)["applied"] == []   # и с бэкапом тоже


def test_current_version_raises_on_broken_table():
    """current_version() НЕ маскирует битую таблицу schema_version под «версия 0»."""
    eng = create_engine("sqlite://")
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE schema_version (foo INTEGER, bar TEXT)")
    with pytest.raises(SQLAlchemyError):
        migrations.current_version(eng)
    # pending() тоже поднимает ошибку, а не молча отдаёт все миграции
    with pytest.raises(SQLAlchemyError):
        migrations.pending(eng)


def test_current_version_zero_when_table_absent():
    """Без таблицы schema_version — честные 0 и полный список pending (первая установка)."""
    eng = create_engine("sqlite://")
    assert migrations.current_version(eng) == 0
    assert [m[0] for m in migrations.pending(eng)] == [v for v, _, _ in migrations.MIGRATIONS]


def test_migration_error_flag_set_and_cleared(fresh_db, _client):
    """Сбой migrations.apply: флаг migration:error в settings и /api/status, старт не падает;
    следующий успешный старт флаг снимает."""
    from core import db as dbm

    orig = migrations.apply

    def boom(*a, **k):
        raise RuntimeError("симулированный сбой миграции")

    migrations.apply = boom          # init_db берёт migrations.apply с модуля в момент вызова
    try:
        dbm.init_db()                # не должно поднять исключение
    finally:
        migrations.apply = orig

    val = dbm.get_setting("migration:error")
    assert val and "симулированный" in val, "после сбоя миграции флаг должен быть записан"
    assert _client.get("/api/status").json()["migration_error"], "/api/status должен отдать migration_error"

    dbm.init_db()                    # перезапуск прошёл — флаг снят
    assert dbm.get_setting("migration:error") is None
    assert not _client.get("/api/status").json()["migration_error"]
