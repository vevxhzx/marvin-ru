"""Ревью E «Надёжность» — часть 1: миграции БД (аддитивность, идемпотентность, бэкап).

Правила, которых держатся тесты:

* всё работает ТОЛЬКО на временных базах в `tmp_path`;
* настоящий `data/jarvis.db` не открывается на запись — при необходимости он
  копируется в tmp через SQLite backup API с режимом `mode=ro` (источник только читается);
* каталог бэкапов подменяется на tmp, чтобы `init_db()` не писал в `data/backups`.

Проверяемые инварианты (AGENTS.md / core/migrations.py):
  1) миграции только аддитивные — ни одной конструкции DROP/RENAME;
  2) существующая непустая база получает бэкап ДО изменения схемы;
  3) повторный запуск не падает, не дублирует данные и не создаёт лишних бэкапов;
  4) данные переживают миграцию (строки и значения на месте).
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402
from sqlalchemy import create_engine, event, inspect, text  # noqa: E402

from core import db, migrations  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
REAL_DB = ROOT / "data" / "jarvis.db"

# Схема «до CRM»: только базовые колонки (те, что добавляют db._migrate и migrations v2/v3).
# Сознательно не содержит ни одной колонки, которую добавляют миграции.
LEGACY_SCHEMA = """
CREATE TABLE "order" (
  id INTEGER PRIMARY KEY, title VARCHAR NOT NULL, client_id INTEGER, price FLOAT DEFAULT 0,
  status VARCHAR NOT NULL DEFAULT 'new', deadline DATETIME, notes VARCHAR,
  estimate_h FLOAT DEFAULT 0, source VARCHAR NOT NULL DEFAULT 'web',
  created_at DATETIME, done_at DATETIME, paid_at DATETIME);
CREATE TABLE client (
  id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, contact VARCHAR, notes VARCHAR,
  kind VARCHAR DEFAULT 'client', aliases VARCHAR DEFAULT '', birthday VARCHAR,
  tags VARCHAR DEFAULT '', pay_mode VARCHAR DEFAULT 'each', pay_every INTEGER DEFAULT 14,
  pay_days VARCHAR DEFAULT '', created_at DATETIME);
CREATE TABLE "transaction" (
  id INTEGER PRIMARY KEY, amount FLOAT NOT NULL, kind VARCHAR NOT NULL, category VARCHAR,
  account VARCHAR, to_account VARCHAR, note VARCHAR, date DATETIME,
  source VARCHAR NOT NULL DEFAULT 'tg', import_hash VARCHAR);
CREATE TABLE event (
  id INTEGER PRIMARY KEY, title VARCHAR NOT NULL, start DATETIME NOT NULL, "end" DATETIME,
  location VARCHAR, notes VARCHAR, remind_minutes INTEGER DEFAULT 30,
  reminded BOOLEAN DEFAULT 0, source VARCHAR NOT NULL DEFAULT 'tg',
  google_id VARCHAR, created_at DATETIME);
CREATE TABLE task (
  id INTEGER PRIMARY KEY, title VARCHAR NOT NULL, done BOOLEAN DEFAULT 0,
  priority INTEGER DEFAULT 2, due DATETIME, project VARCHAR,
  source VARCHAR NOT NULL DEFAULT 'tg', created_at DATETIME, done_at DATETIME);
CREATE TABLE category (
  id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, kind VARCHAR NOT NULL,
  icon VARCHAR DEFAULT '•', keywords VARCHAR DEFAULT '');
CREATE TABLE account (
  id INTEGER PRIMARY KEY, name VARCHAR NOT NULL UNIQUE, kind VARCHAR DEFAULT 'bank',
  balance FLOAT DEFAULT 0, is_main BOOLEAN DEFAULT 0, currency VARCHAR DEFAULT 'RUB');
"""

LEGACY_ROWS = [
    ('INSERT INTO "order" (id, title, client_id, price, status, notes, source, created_at) '
     "VALUES (1, 'Монтаж ролика', 1, 50000.0, 'work', 'ТЗ от клиента', 'web', '2026-08-01 12:00:00')"),
    ("INSERT INTO client (id, name, kind, notes, created_at) "
     "VALUES (1, 'Иван Петров', 'client', 'пришёл по рекомендации', '2026-08-01 12:00:00')"),
    ('INSERT INTO "transaction" (id, amount, kind, category, account, note, date, source) '
     "VALUES (1, 700.0, 'expense', 'Транспорт', 'Наличные', 'такси', '2026-08-02 09:00:00', 'tg')"),
    ("INSERT INTO event (id, title, start, notes, source, created_at) "
     "VALUES (1, 'Встреча', '2026-09-01 10:00:00', 'кофе', 'tg', '2026-08-01 12:00:00')"),
    ("INSERT INTO task (id, title, priority, source, created_at) "
     "VALUES (1, 'Купить молоко', 2, 'tg', '2026-08-01 12:00:00')"),
    ("INSERT INTO category (id, name, kind, icon, keywords) VALUES (1, 'Еда', 'expense', '🍔', 'еда')"),
    ("INSERT INTO account (id, name, kind, is_main) VALUES (1, 'Наличные', 'cash', 1)"),
]

# Колонки, которые обязаны появиться после полного цикла миграций.
MUST_APPEAR = {
    "order": ["stage", "revisions", "lost_reason", "last_contact_at", "next_step", "next_step_at"],
    "client": ["source", "last_contact_at", "next_step", "next_step_at",
               "stage", "stage_manual", "stage_auto", "stage_updated_at"],
    "transaction": ["debt_id", "order_id", "goal_id", "idem_key"],
    "event": ["repeat", "repeat_days", "done", "task_id", "order_id"],
    "task": ["remind_stage", "aim_id", "milestone_id", "blocked_by"],
    "category": ["budget", "custom", "bucket"],
}


def _connect(path: Path) -> sqlite3.Connection:
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    return con


def _columns_sqlite(path: Path, table: str) -> set[str]:
    con = _connect(path)
    try:
        return {r["name"] for r in con.execute(f'PRAGMA table_info("{table}")')}
    finally:
        con.close()


def _count(path: Path, table: str) -> int:
    con = _connect(path)
    try:
        return int(con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
    finally:
        con.close()


def _make_legacy_db(path: Path) -> None:
    con = _connect(path)
    try:
        con.executescript(LEGACY_SCHEMA)
        for sql in LEGACY_ROWS:
            con.execute(sql)
        con.commit()
    finally:
        con.close()


def _engine_on(path: Path):
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    return eng


@pytest.fixture()
def legacy_db(tmp_path, monkeypatch):
    """Непустая «старая» база (схема до CRM) + подменённый engine и каталог бэкапов."""
    path = tmp_path / "legacy.db"
    _make_legacy_db(path)
    monkeypatch.setattr(db, "engine", _engine_on(path))
    monkeypatch.setattr(migrations, "_backup_dir", lambda: tmp_path / "backups")
    return path


def _backups(tmp_path: Path) -> list[Path]:
    bdir = tmp_path / "backups"
    return sorted(bdir.glob("*.db")) if bdir.exists() else []


# ---------------------------------------------------------------- 1. аддитивность + бэкап
def test_legacy_db_migrates_additively_and_creates_backup(legacy_db, tmp_path):
    before_cols = {t: _columns_sqlite(legacy_db, t) for t in MUST_APPEAR}

    db.init_db()

    # бэкап сделан ДО изменения схемы
    backups = _backups(tmp_path)
    assert backups, "для существующей непустой базы должен быть бэкап в backups/"
    with sqlite3.connect(str(backups[0])) as con:
        con.row_factory = sqlite3.Row
        b_cols = {r["name"] for r in con.execute('PRAGMA table_info("order")')}
        assert "stage" not in b_cols, "бэкап должен хранить схему ДО миграции"
        row = con.execute('SELECT title FROM "order" WHERE id=1').fetchone()
        assert row["title"] == "Монтаж ролика"

    # после миграции: новые колонки есть, старые не тронуты
    for table, cols in MUST_APPEAR.items():
        after = _columns_sqlite(legacy_db, table)
        assert before_cols[table] <= after, f"{table}: старые колонки пропали"
        missing = [c for c in cols if c not in after]
        assert not missing, f"{table}: миграция не добавила колонки {missing}"

    # новые таблицы CRM созданы
    with sqlite3.connect(str(legacy_db)) as con:
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"crmactivity", "crmcomment", "crmchecklist", "crmfollowup"} <= names

    # данные на месте, значения не переписаны
    with sqlite3.connect(str(legacy_db)) as con:
        assert con.execute('SELECT title FROM "order" WHERE id=1').fetchone()[0] == "Монтаж ролика"
        assert con.execute('SELECT price FROM "order" WHERE id=1').fetchone()[0] == 50000.0
        assert con.execute("SELECT stage FROM \"order\" WHERE id=1").fetchone()[0] == "in_work"  # бэкфилл из status
        assert con.execute("SELECT name FROM client WHERE id=1").fetchone()[0] == "Иван Петров"
        assert con.execute('SELECT amount FROM "transaction" WHERE id=1').fetchone()[0] == 700.0
        assert con.execute("SELECT title FROM event WHERE id=1").fetchone()[0] == "Встреча"
        assert con.execute("SELECT title FROM task WHERE id=1").fetchone()[0] == "Купить молоко"

    with db.engine.connect() as conn:
        assert conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar() == max(
            v for v, _, _ in migrations.MIGRATIONS)


# ---------------------------------------------------------------- 2. идемпотентность
def test_init_db_twice_is_idempotent(legacy_db, tmp_path):
    db.init_db()
    counts_1 = {t: _count(legacy_db, t) for t in ("order", "client", "transaction", "event", "task", "category", "account")}
    with db.engine.connect() as conn:
        v1 = conn.execute(text("SELECT COUNT(*) FROM schema_version")).scalar()

    db.init_db()  # повторный запуск (второй старт приложения)

    counts_2 = {t: _count(legacy_db, t) for t in counts_1}
    assert counts_1 == counts_2, "повторный init_db продублировал данные"
    with db.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM schema_version")).scalar() == v1
        assert conn.execute(text("SELECT MAX(version) FROM schema_version")).scalar() == max(
            v for v, _, _ in migrations.MIGRATIONS)
    # второй бэкап не нужен: миграций больше нет
    assert len(_backups(tmp_path)) == 1, "повторный запуск не должен плодить бэкапы"
    # дефолтные категории/счета не задублированы
    assert _count(legacy_db, "category") <= 14
    assert _count(legacy_db, "account") <= 3


def test_migrations_apply_twice_on_same_engine(tmp_path, monkeypatch):
    """migrations.apply() вызывается повторно (реставрация бэкапа, ручной запуск) — не падает."""
    path = tmp_path / "m.db"
    _make_legacy_db(path)
    eng = _engine_on(path)
    first = migrations.apply(eng, had_db=True, backup_dir=tmp_path / "bk")
    second = migrations.apply(eng, had_db=True, backup_dir=tmp_path / "bk")
    assert first["applied"] == [v for v, _, _ in migrations.MIGRATIONS]
    assert second["applied"] == [] and second["backup"] is None
    assert len(list((tmp_path / "bk").glob("*.db"))) == 1


# ---------------------------------------------------------------- 3. только аддитивный SQL
def test_migration_sources_have_no_destructive_sql():
    """Ни одна миграция не удаляет колонки/таблицы/индексы и не переименовывает их.
    Единственное исключение — v10: DROP пустой таблицы-сироты `schemaversion`
    (только IF EXISTS после проверки COUNT(*)=0 в коде миграции; см. SECURITY.md §2)."""
    for fname in (ROOT / "core" / "migrations.py", ROOT / "core" / "db.py"):
        src = fname.read_text(encoding="utf-8")
        # выкидываем строки-комментарии, чтобы не ругаться на слово DROP в докстрингах
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        # v10-исключение: удаление только пустой сироты (guard COUNT(*)=0 — в коде миграции выше)
        code = re.sub(r"DROP\s+TABLE\s+IF\s+EXISTS\s+schemaversion\b", "", code, flags=re.I)
        assert not re.search(r"DROP\s+(TABLE|COLUMN|INDEX)\b", code, re.I), f"{fname.name}: есть DROP"
        assert not re.search(r"ALTER\s+TABLE\s+\S+\s+(DROP|RENAME|REPLACE)\b", code, re.I), f"{fname.name}: есть деструктивный ALTER"
        assert not re.search(r"DELETE\s+FROM\s+(?!schema_version)", code, re.I), f"{fname.name}: есть DELETE FROM"
        for m in re.finditer(r"ALTER\s+TABLE[^\n]*", code, re.I):
            assert "ADD COLUMN" in m.group(0).upper(), f"{fname.name}: ALTER не ADD COLUMN → {m.group(0)!r}"


# ---------------------------------------------------------------- 4. бэкап не плодится на пустой базе
def test_fresh_db_gets_no_backup(tmp_path, monkeypatch):
    path = tmp_path / "fresh.db"
    monkeypatch.setattr(db, "engine", _engine_on(path))
    monkeypatch.setattr(migrations, "_backup_dir", lambda: tmp_path / "backups")
    db.init_db()
    assert _backups(tmp_path) == []
    assert path.exists() and path.stat().st_size > 0


# ---------------------------------------------------------------- 5. настоящая data/jarvis.db (только чтение)
def _copy_real_db_to(dst: Path) -> None:
    """Копия реальной базы в tmp. Источник открывается ТОЛЬКО на чтение (mode=ro)."""
    assert REAL_DB.exists(), "data/jarvis.db не найдена"
    uri = "file:" + REAL_DB.resolve().as_posix() + "?mode=ro"
    src = sqlite3.connect(uri, uri=True)
    out = sqlite3.connect(str(dst))
    try:
        with out:
            src.backup(out)
    finally:
        out.close()
        src.close()


def test_real_db_copy_survives_migration(tmp_path, monkeypatch):
    if not REAL_DB.exists():
        # CI и чистый клон: рабочей базы нет (data/ не в git) — здесь нечего проверять.
        # В рабочей копии файла тест идёт как обычно, источник открывается только на чтение.
        pytest.skip("data/jarvis.db нет (CI/чистый клон) — тест проверяет именно рабочую базу")
    stat_before = (REAL_DB.stat().st_size, REAL_DB.stat().st_mtime)

    copy = tmp_path / "jarvis_copy.db"
    _copy_real_db_to(copy)

    # считаем данные ДО
    before_tables = set()
    before_counts: dict[str, int] = {}
    with sqlite3.connect(str(copy)) as con:
        before_tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                         if not r[0].startswith("sqlite_") and r[0] not in ("schema_version", "schemaversion")}
        # schemaversion исключена намеренно: это пустая таблица-сирота (двойник SchemaVersion),
        # которую v10 удаляет — её исчезновение и есть ожидаемый эффект миграции
        for t in sorted(before_tables):
            before_counts[t] = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        before_cols = {t: {r[1] for r in con.execute(f'PRAGMA table_info("{t}")')} for t in sorted(before_tables)}
        con.execute("DELETE FROM schema_version")  # имитация базы, к которой миграции ещё не применялись
        con.commit()

    eng = _engine_on(copy)
    monkeypatch.setattr(migrations, "_backup_dir", lambda: tmp_path / "backups")
    res = migrations.apply(eng, had_db=True, backup_dir=tmp_path / "backups")
    res2 = migrations.apply(eng, had_db=True, backup_dir=tmp_path / "backups")

    assert res["applied"] == [v for v, _, _ in migrations.MIGRATIONS] and res["backup"], "миграции не применились или бэкапа нет"
    assert res2["applied"] == []
    assert len(_backups(tmp_path)) == 1

    with sqlite3.connect(str(copy)) as con:
        assert con.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        after_tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
                        if not r[0].startswith("sqlite_")}
        assert before_tables <= after_tables, "миграция удалила таблицы"
        for t, cols in before_cols.items():
            now = {r[1] for r in con.execute(f'PRAGMA table_info("{t}")')}
            lost = cols - now
            assert not lost, f"{t}: после миграции потеряны колонки {lost}"
        for t in sorted(before_tables):
            n = con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            assert n == before_counts[t], f"{t}: {before_counts[t]} → {n} строк после миграции"
        # бэкап — это снимок ДО миграции (версия 0, данные уже на месте)
        with sqlite3.connect(str(_backups(tmp_path)[0])) as b:
            assert b.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version").fetchone()[0] == 0
            if "order" in before_counts:
                assert b.execute('SELECT COUNT(*) FROM "order"').fetchone()[0] == before_counts["order"]

    # источник не изменён
    stat_after = (REAL_DB.stat().st_size, REAL_DB.stat().st_mtime)
    assert stat_before == stat_after, "тест открыл настоящую БД на запись"
