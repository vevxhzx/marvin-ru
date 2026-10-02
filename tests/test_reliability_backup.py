"""Надёжность бэкапов (агент B): порядок «бэкап → первое изменение схемы», integrity-check
после снимка, копии конфигов, ретеншн `pre-migration-*.db`, скачивание через API.

Всё ТОЛЬКО на временной БД: `fresh_db` из tests/conftest подменяет db.engine до init_db(),
каталог бэкапов и пути указываются в tmp_path. Настоящие data/jarvis.db и config.yaml
не открываются на запись (копии конфигов читаются и только перекладываются в tmp).
"""
from __future__ import annotations

import os
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def backup_env(fresh_db, monkeypatch, tmp_path):
    """Временная БД + каталог бэкапов в tmp: backup_db() ходит только туда."""
    from core import config as cfgmod
    from core import db as dbm
    from core.services import scheduler

    bdir = tmp_path / "backups"
    db_path = Path(str(dbm.engine.url.database))
    monkeypatch.setattr(scheduler, "DB_PATH", db_path)
    monkeypatch.setattr(cfgmod.cfg.backup, "enabled", True, raising=False)
    monkeypatch.setattr(cfgmod.cfg.backup, "dir", str(bdir), raising=False)
    monkeypatch.setattr(cfgmod.cfg.backup, "keep_days", 30, raising=False)
    monkeypatch.setattr(cfgmod.cfg.backup, "extra_dir", None, raising=False)
    return {"db": db_path, "bdir": bdir}


def _legacy_db(path: Path) -> None:
    """Старая база (схема до CRM): в ней ещё нет ни stage, ни schema_version."""
    con = sqlite3.connect(str(path))
    try:
        con.execute('CREATE TABLE "order" (id INTEGER PRIMARY KEY, title VARCHAR NOT NULL, '
                    "status VARCHAR DEFAULT 'new', price FLOAT, source VARCHAR DEFAULT 'web', "
                    "client_id INTEGER, deadline DATETIME, notes VARCHAR, estimate_h FLOAT, "
                    "created_at DATETIME, done_at DATETIME, paid_at DATETIME)")
        con.execute("CREATE TABLE task (id INTEGER PRIMARY KEY, title VARCHAR NOT NULL, "
                    "done BOOLEAN DEFAULT 0, priority INTEGER DEFAULT 2, due DATETIME, created_at DATETIME)")
        con.execute("INSERT INTO \"order\" (title, status, price) VALUES ('Старый ролик', 'work', 15000.0)")
        con.commit()
    finally:
        con.close()


# ---------------------------------------------------------------- 1. бэкап ДО изменения схемы
def test_backup_taken_before_first_schema_change(tmp_path, monkeypatch):
    """init_db() снимает копию ДО create_all/_migrate/migrations.apply: в бэкапе ни одной новой
    колонки и даже ещё нет schema_version. Повторный старт нового бэкапа не плодит."""
    from sqlalchemy import event, text
    from sqlmodel import create_engine

    from core import db as dbm, migrations

    db_file = tmp_path / "legacy.db"
    _legacy_db(db_file)
    eng = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", dbm._pragmas)
    monkeypatch.setattr(dbm, "engine", eng)
    monkeypatch.setattr(migrations, "_backup_dir", lambda: tmp_path / "backups")

    dbm.init_db()

    backups = sorted((tmp_path / "backups").glob("pre-migration-*.db"))
    assert len(backups) == 1, f"ожидался один снимок до миграции, найдено: {backups}"
    con = sqlite3.connect(str(backups[0]))
    try:
        cols = {r[1] for r in con.execute('PRAGMA table_info("order")')}
        assert "stage" not in cols, "в бэкапе не должно быть колонок из миграций"
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "schema_version" not in tables, "бэкап снят раньше ЛЮБОГО изменения схемы"
        assert con.execute('SELECT title FROM "order"').fetchone()[0] == "Старый ролик"
    finally:
        con.close()

    # после старта схема доехала и данные целы
    with eng.connect() as conn:
        assert "stage" in {r[1] for r in conn.exec_driver_sql('PRAGMA table_info("order")').fetchall()}
        ver = conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar()
        assert conn.execute(text('SELECT title FROM "order"')).scalar() == "Старый ролик"
    assert ver == max(v for v, _, _ in migrations.MIGRATIONS)

    # второй старт: изменений нет → второй бэкап не нужен
    dbm.init_db()
    assert len(list((tmp_path / "backups").glob("pre-migration-*.db"))) == 1


# ---------------------------------------------------------------- 2. integrity-check после снимка
def test_backup_integrity_check_is_recorded(backup_env):
    from core.services import scheduler

    dst = scheduler.backup_db(force=True)
    assert dst and dst.exists()
    chk = scheduler.last_backup().get("check")
    assert isinstance(chk, dict) and chk["ok"] is True
    assert chk["file"] == dst.name and chk["result"] == "ok"
    assert chk["size"] == dst.stat().st_size and chk["at"]


def test_integrity_failure_keeps_old_backups_and_alerts(backup_env, monkeypatch):
    """Провал проверки: log.error + событие health_bad, СТАРЫЕ бэкапы не удаляются,
    результат уходит в settings (его же отдаёт /api/status)."""
    from core import config as cfgmod
    from core.services import events, scheduler

    good = scheduler.backup_db(force=True)
    assert good and good.exists()
    old = backup_env["bdir"] / "backup-20200101-0000.db"
    old.write_bytes(b"old verified snapshot")
    t_old = time.time() - 40 * 86400
    os.utime(old, (t_old, t_old))

    orig_verify = scheduler._verify_backup
    monkeypatch.setattr(cfgmod.cfg.backup, "keep_days", 0, raising=False)  # ретеншн съел бы всё старое
    monkeypatch.setattr(scheduler, "_verify_backup", lambda p: (False, "симулированный разрыв файла"))
    bad = scheduler.backup_db(force=True)
    assert bad
    assert old.exists(), "при провале integrity-check старые бэкапы удалять нельзя"
    chk = scheduler.last_backup()["check"]
    assert chk["ok"] is False and "симулированный" in chk["result"]
    assert any(e.kind == "health_bad" and e.key == "backup_integrity"
               for e in events.recent(50)), "нет события health_bad о битом бэкапе"

    # проверка снова прошла — ретеншн возвращается
    monkeypatch.setattr(scheduler, "_verify_backup", orig_verify)
    scheduler.backup_db(force=True)
    assert not old.exists(), "после успешной проверки ретеншн keep_days снова работает"


def test_status_shows_last_backup_check(backup_env, _client):
    from core.services import scheduler

    scheduler.backup_db(force=True)
    data = _client.get("/api/status").json()
    assert data["backup"]["check"]["ok"] is True
    assert "migration_error" in data
    r = _client.post("/api/backup")
    assert r.status_code == 200 and r.json()["check"]["ok"] is True


# ---------------------------------------------------------------- 3. копии конфигов + скачивание
def test_config_backups_listed_and_downloadable(backup_env, _client, tmp_path, monkeypatch):
    from core import config as cfgmod
    from core.services import scheduler

    # свои источники в tmp: тест не зависит от наличия настоящих config.yaml / data/api_token
    root = tmp_path / "root"
    dat = tmp_path / "data"
    root.mkdir(exist_ok=True)
    dat.mkdir(exist_ok=True)
    (root / "config.yaml").write_text("brain:\n  mode: local\n", encoding="utf-8")
    (dat / "api_token").write_bytes(b"sekret-token")
    (dat / "session_secret").write_bytes(b"sekret-sign")
    monkeypatch.setattr(cfgmod, "ROOT", root)
    monkeypatch.setattr(cfgmod, "DATA_DIR", dat)

    dst = scheduler.backup_db(force=True)
    assert dst
    cfg_dirs = list(backup_env["bdir"].glob("config-*"))
    assert cfg_dirs, "копии конфигов не созданы"
    files = {p.name for p in cfg_dirs[0].iterdir() if p.is_file()}
    assert {"config.yaml", "api_token", "session_secret"} <= files

    items = scheduler.list_config_backups()
    assert {i["name"].rsplit("/", 1)[-1] for i in items} >= {"config.yaml", "api_token", "session_secret"}
    assert all(i["kind"] == "config" for i in items)

    # /api/backups: и снимки базы, и копии конфигов — одним списком
    names = [i["name"] for i in _client.get("/api/backups").json()]
    assert dst.name in names
    assert any(n.startswith("config-") for n in names)

    # скачивание файла
    target = next(i["name"] for i in items if i["name"].endswith("/config.yaml"))
    r = _client.get(f"/api/backups/{target}/download")
    assert r.status_code == 200, r.text
    assert r.content == (root / "config.yaml").read_bytes()
    # тот же файл отдаёт и resolve_backup_file
    assert scheduler.resolve_backup_file(target).read_bytes() == r.content

    # path traversal — как в restore_backup
    for bad in ("../config.yaml", f"{target.rsplit('/', 1)[0]}/../../config.yaml",
                "nope.db", "..\\config.yaml"):
        with pytest.raises((ValueError, LookupError)):
            scheduler.resolve_backup_file(bad)
    assert _client.get("/api/backups/..%2F..%2Fconfig.yaml/download").status_code in (400, 404)
    assert _client.get("/api/backups/nope.db/download").status_code in (400, 404)


# ---------------------------------------------------------------- 4. ретеншн pre-migration-*.db
def test_pre_migration_backups_listed_and_trimmed(backup_env, monkeypatch):
    from core import config as cfgmod
    from core.services import scheduler

    bdir = backup_env["bdir"]
    bdir.mkdir(parents=True, exist_ok=True)
    old = bdir / "pre-migration-20200101-010101.db"
    fresh = bdir / f"pre-migration-{datetime.now():%Y%m%d-%H%M%S}.db"
    for f in (old, fresh):
        f.write_bytes(b"x" * 16)
    t_old = time.time() - 40 * 86400
    os.utime(old, (t_old, t_old))

    listed = {b["name"]: b for b in scheduler.list_backups()}
    assert old.name in listed and fresh.name in listed
    assert listed[old.name]["pre_migration"] is True and listed[old.name]["kind"] == "db"

    # keep_days=1: сорокадневная копия уходит, свежая — остаётся
    monkeypatch.setattr(cfgmod.cfg.backup, "keep_days", 1, raising=False)
    scheduler.backup_db(force=True)
    assert not old.exists(), "pre-migration-*.db должен попадать под backup.keep_days"
    assert fresh.exists(), "свежая копия не должна удаляться"

    # restore по-прежнему принимает только backup-*.db — поведение не менялось
    with pytest.raises(ValueError):
        scheduler.restore_backup(old.name)


def test_pre_migration_backup_never_leaves_an_empty_file(tmp_path):
    """Страховка перед миграцией: снимок проверяется до того, как попадёт в backups/.

    Пустой или битый снимок опаснее отсутствия снимка — его принимают за рабочую копию.
    """
    import sqlmodel

    from core import migrations

    db_file = tmp_path / "src.db"
    con = sqlite3.connect(db_file)
    con.execute("CREATE TABLE t (x INT)")
    con.execute("INSERT INTO t VALUES (42)")
    con.commit()
    con.close()
    engine = sqlmodel.create_engine(f"sqlite:///{db_file}")

    out = migrations.backup_before_migration(engine, backup_dir=tmp_path / "backups")
    assert out and Path(out).stat().st_size > 0, "бэкап должен быть непустым"
    chk = sqlite3.connect(out)
    try:
        assert chk.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert chk.execute("SELECT x FROM t").fetchone()[0] == 42
    finally:
        chk.close()

    # небоевая база (тест/tmp) не должна писать бэкапы в боевой каталог из config.yaml
    real_dir = migrations._backup_dir()
    before = set(real_dir.glob("pre-migration-*.db")) if real_dir.exists() else set()
    migrations.backup_before_migration(engine)
    after = set(real_dir.glob("pre-migration-*.db")) if real_dir.exists() else set()
    assert after == before, "тестовая БД не должна оставлять файлы в боевом каталоге бэкапов"

    # битый источник - не оставляем ни файла, ни «полу-бэкапа»
    broken = tmp_path / "broken.db"
    broken.write_bytes(b"not a database at all")
    eng2 = sqlmodel.create_engine(f"sqlite:///{broken}")
    assert migrations.backup_before_migration(eng2, backup_dir=tmp_path / "backups2") is None
    left = list((tmp_path / "backups2").glob("*")) if (tmp_path / "backups2").exists() else []
    assert not [p for p in left if p.stat().st_size == 0], "пустых файлов быть не должно"
