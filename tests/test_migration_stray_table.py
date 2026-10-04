"""Миграция v10: пустая таблица-сирота `schemaversion` удаляется, непустая — сохраняется + warning.

Только tmp-БД: живая data/jarvis.db не трогается.
"""
import os

os.environ.setdefault("JARVIS_TEST", "1")


def _engine_on(path):
    from sqlmodel import create_engine
    return create_engine(f"sqlite:///{path}")


def test_v10_drops_empty_stray(tmp_path):
    import sqlite3

    from core import migrations

    path = tmp_path / "v10empty.db"
    eng = _engine_on(path)
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE schemaversion (version INTEGER PRIMARY KEY)")
    # schema_version намеренно не создаём — её ставит _ensure_table() внутри apply()
    res = migrations.apply(eng, had_db=True, backup_dir=tmp_path / "bk")
    assert 10 in res["applied"]
    with sqlite3.connect(str(path)) as con:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "schemaversion" not in tables, "пустая сирота должна быть удалена"
    assert "schema_version" in tables


def test_v10_keeps_nonempty_stray_and_warns(tmp_path, caplog):
    import logging
    import sqlite3

    from core import migrations

    path = tmp_path / "v10full.db"
    eng = _engine_on(path)
    with eng.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE schemaversion (version INTEGER PRIMARY KEY)")
        conn.exec_driver_sql("INSERT INTO schemaversion (version) VALUES (999)")
    with caplog.at_level(logging.WARNING, logger="jarvis.migrations"):
        res = migrations.apply(eng, had_db=True, backup_dir=tmp_path / "bk")
    assert 10 in res["applied"]
    with sqlite3.connect(str(path)) as con:
        n = con.execute('SELECT COUNT(*) FROM "schemaversion"').fetchone()[0]
    assert n == 1, "непустая таблица должна сохраниться"
    assert any("schemaversion" in r.message for r in caplog.records), "должен быть warning в лог"
