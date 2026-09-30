"""Простые аддитивные миграции схемы БД с версионированием.

Правила (см. OVERNIGHT.md, «жёсткие правила безопасности»):

- Миграции только **аддитивные**: `CREATE TABLE` / `ALTER TABLE … ADD COLUMN` со значением
  по умолчанию. Никаких `DROP`, переименований колонок/таблиц и удаления данных.
- Каждая миграция **идемпотентна**: повторный запуск ничего не ломает.
- Перед первым применением к существующей непустой БД автоматически делается бэкап
  файла БД (SQLite backup API) в `backups/pre-migration-<дата>.db`.
- Применяются строго по возрастанию версии. Текущая версия — `MAX(version)` в
  таблице `schema_version` (модель `db.SchemaVersion`).

Новая миграция = функция `_vN(conn)` + строка `(N, "описание", _vN)` в конце `MIGRATIONS`.
Пример (для фазы 4):

    def _v2_add_order_stage(conn):
        _add_column(conn, "order", "stage", "VARCHAR DEFAULT 'lead'")

    MIGRATIONS.append((2, "crm: order.stage", _v2_add_order_stage))
"""
from __future__ import annotations

import logging
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger("jarvis.migrations")

MigrationFn = Callable[[object], None]
Migration = tuple[int, str, MigrationFn]


def _noop(_conn) -> None:
    """Базовая версия: сама таблица `schema_version` уже создана до применения."""


# Порядковый номер — это версия схемы. Никогда не переиспользуем и не меняем задним числом.
MIGRATIONS: list[Migration] = [
    (1, "baseline: schema_version", _noop),
]


# ------------------------------------------------------------------ утилиты для будущих миграций
def table_exists(conn, table: str) -> bool:
    row = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table' AND name=:n"), {"n": table}).first()
    return bool(row)


def column_names(conn, table: str) -> set[str]:
    try:
        return {r[1] for r in conn.execute(text(f'PRAGMA table_info("{table}")')).all()}
    except Exception:
        return set()


def add_column(conn, table: str, column: str, ddl: str) -> bool:
    """Идемпотентно добавить колонку (`ddl` — тип + DEFAULT). Возвращает True, если добавили."""
    if not table_exists(conn, table) or column in column_names(conn, table):
        return False
    conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN "{column}" {ddl}'))
    return True


def create_index(conn, name: str, table: str, columns: str) -> None:
    """Идемпотентно создать индекс (аддитивно, без удаления)."""
    conn.execute(text(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{table}" ({columns})'))


# ------------------------------------------------------------------ версия и применение
def _ensure_table(engine: Engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE IF NOT EXISTS schema_version ("
            "version INTEGER PRIMARY KEY, "
            "name VARCHAR DEFAULT '', "
            "applied_at DATETIME)"
        ))


def current_version(engine: Engine) -> int:
    """Максимальная применённая версия; 0 — ещё ничего не применялось."""
    with engine.connect() as conn:
        try:
            row = conn.execute(text("SELECT MAX(version) FROM schema_version")).first()
        except Exception:
            return 0
    return int(row[0]) if row and row[0] is not None else 0


def pending(engine: Engine) -> list[Migration]:
    cur = current_version(engine)
    return [m for m in MIGRATIONS if m[0] > cur]


def _db_file(engine: Engine) -> str | None:
    return getattr(engine.url, "database", None)


def _backup_dir() -> Path:
    try:
        from .config import ROOT, cfg
        raw = (getattr(getattr(cfg, "backup", None), "dir", "") or "backups")
        p = Path(raw)
        return p if p.is_absolute() else (ROOT / p).resolve()
    except Exception:  # pragma: no cover
        from .config import ROOT
        return ROOT / "backups"


def backup_before_migration(engine: Engine, backup_dir: str | Path | None = None) -> str | None:
    """Копия файла БД через SQLite backup API. Возвращает путь к бэкапу или None."""
    db = _db_file(engine)
    if not db or not os.path.exists(db):
        return None
    bdir = Path(backup_dir) if backup_dir else _backup_dir()
    bdir.mkdir(parents=True, exist_ok=True)
    dst = bdir / f"pre-migration-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(db)
    out = sqlite3.connect(str(dst))
    try:
        with out:
            src.backup(out)
    finally:
        out.close()
        src.close()
    log.info("миграция: бэкап БД → %s", dst)
    return str(dst)


def apply(engine: Engine, had_db: bool = True, backup_dir: str | Path | None = None) -> dict:
    """Применить недостающие миграции по порядку.

    `had_db=False` — база только что создана с нуля (бэкапить нечего).
    Возвращает {"from", "to", "applied": [версии], "backup": путь|None}.
    """
    _ensure_table(engine)
    cur = current_version(engine)
    todo = [m for m in MIGRATIONS if m[0] > cur]
    if not todo:
        return {"from": cur, "to": cur, "applied": [], "backup": None}
    backup = backup_before_migration(engine, backup_dir) if had_db else None
    applied: list[int] = []
    for version, name, fn in todo:
        with engine.begin() as conn:
            fn(conn)
            # applied_at — строкой, чтобы не задействовать устаревший адаптер datetime в sqlite3
            conn.execute(
                text("INSERT OR REPLACE INTO schema_version (version, name, applied_at) VALUES (:v, :n, :t)"),
                {"v": version, "n": name, "t": datetime.now().strftime("%Y-%m-%d %H:%M:%S")},
            )
        applied.append(version)
        log.info("миграция %s применена: %s", version, name)
    return {"from": cur, "to": applied[-1] if applied else cur, "applied": applied, "backup": backup}
