"""Бэкап и restore одной кнопкой (ROADMAP P1)."""
import os
from pathlib import Path

import pytest

os.environ.setdefault("JARVIS_TEST", "1")


@pytest.fixture()
def backup_env(tmp_path, monkeypatch):
    from core import config as cfgmod
    from core import db as dbm
    from sqlmodel import SQLModel, create_engine

    db_path = tmp_path / "jarvis.db"
    bdir = tmp_path / "backups"
    eng = create_engine(f"sqlite:///{db_path}")
    monkeypatch.setattr(dbm, "engine", eng)
    monkeypatch.setattr(cfgmod, "DB_PATH", db_path)
    # cfg.backup — Node
    monkeypatch.setattr(cfgmod.cfg.backup, "enabled", True, raising=False)
    monkeypatch.setattr(cfgmod.cfg.backup, "dir", str(bdir), raising=False)
    monkeypatch.setattr(cfgmod.cfg.backup, "keep_days", 30, raising=False)
    monkeypatch.setattr(cfgmod.cfg.backup, "extra_dir", None, raising=False)
    SQLModel.metadata.create_all(eng)
    # минимальные данные
    from core.db import session, Task
    with session() as s:
        s.add(Task(title="до бэкапа", source="test"))
        s.commit()
    yield {"db": db_path, "bdir": bdir}


def test_backup_list_and_restore(backup_env, monkeypatch):
    from core.services import scheduler
    from core import config as cfgmod
    from core.db import session, Task
    from sqlmodel import select

    monkeypatch.setattr(scheduler, "DB_PATH", backup_env["db"])
    monkeypatch.setattr(scheduler, "ROOT", backup_env["db"].parent)
    # dir absolute already
    dst = scheduler.backup_db(force=True)
    assert dst and dst.exists() and dst.name.startswith("backup-")
    names = [b["name"] for b in scheduler.list_backups()]
    assert dst.name in names

    # меняем базу после снимка
    with session() as s:
        s.add(Task(title="после бэкапа", source="test"))
        s.commit()
    with session() as s:
        titles = {t.title for t in s.exec(select(Task)).all()}
    assert "после бэкапа" in titles

    r = scheduler.restore_backup(dst.name)
    assert r["ok"] and r["needs_restart"] and r["safety"]
    assert (backup_env["bdir"] / r["safety"]).exists()

    # после replace engine может держать старый connection — новый engine
    from core import db as dbm
    from sqlmodel import create_engine, Session, select as sel
    eng = create_engine(f"sqlite:///{backup_env['db']}")
    with Session(eng) as s:
        titles = {t.title for t in s.exec(sel(Task)).all()}
    assert titles == {"до бэкапа"}


def test_restore_rejects_path_traversal(backup_env, monkeypatch):
    from core.services import scheduler
    monkeypatch.setattr(scheduler, "DB_PATH", backup_env["db"])
    with pytest.raises(ValueError):
        scheduler.restore_backup("../etc/passwd")
    with pytest.raises(ValueError):
        scheduler.restore_backup("backup-hack.db")
    with pytest.raises(LookupError):
        scheduler.restore_backup("backup-20990101-0000.db")


def test_api_backup_endpoints(backup_env, monkeypatch):
    from core.services import scheduler
    from core import db as dbm
    monkeypatch.setattr(scheduler, "DB_PATH", backup_env["db"])
    from fastapi.testclient import TestClient
    from core.api.app import app
    c = TestClient(app)
    r = c.post("/api/backup")
    assert r.status_code == 200 and r.json()["ok"] and r.json()["name"]
    lst = c.get("/api/backups").json()
    assert any(x["name"] == r.json()["name"] for x in lst)
    bad = c.post("/api/backups/restore", json={"name": "nope.db"})
    assert bad.status_code in (400, 422)
    ok = c.post("/api/backups/restore", json={"name": r.json()["name"]})
    assert ok.status_code == 200 and ok.json()["needs_restart"] is True


def test_list_backups_sees_jarvis_mask_and_retention_cleans_it(backup_env, monkeypatch):
    """Ручные снимки jarvis-*.db (docs/ROLLBACK.md) — не сироты: видны в списке,
    восстанавливаются, старые вычищаются ротацией. Файлы не переименовываем."""
    import os
    import time

    from core.services import scheduler

    monkeypatch.setattr(scheduler, "DB_PATH", backup_env["db"])
    monkeypatch.setattr(scheduler, "ROOT", backup_env["db"].parent)
    bdir = backup_env["bdir"]
    bdir.mkdir(parents=True, exist_ok=True)
    fresh = bdir / "jarvis-20260930-1414.db"
    fresh.write_bytes(b"fake-db")
    junk = bdir / "notes.txt"
    junk.write_text("not a backup")
    names = [b["name"] for b in scheduler.list_backups()]
    assert "jarvis-20260930-1414.db" in names, "jarvis-*.db должны быть видны в списке бэкапов"
    assert "notes.txt" not in names
    # restore принимает то же имя, что показывает список
    assert scheduler.resolve_backup_file("jarvis-20260930-1414.db").name == "jarvis-20260930-1414.db"
    # ротация: старый jarvis-снимок (старше keep_days) удаляется новым бэкапом, свежий — остаётся
    old = bdir / "jarvis-20200101-0000.db"
    old.write_bytes(b"fake-db-old")
    ancient = time.time() - 40 * 86400
    os.utime(old, (ancient, ancient))
    dst = scheduler.backup_db(force=True)
    assert dst and dst.exists()
    assert not old.exists(), "протухший jarvis-*.db должен вычищаться ротацией"
    assert fresh.exists(), "свежий jarvis-*.db трогать нельзя"
