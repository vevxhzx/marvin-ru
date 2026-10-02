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


def _v2_crm(conn) -> None:
    """Фаза 4 (CRM): аддитивные колонки воронки/карточки + таблицы активности, комментариев,
    чек-листа и follow-up + идемпотентность платежей. Данные не теряются, только добавляются."""
    # --- заказ: стадия канбана, круги правок, причина потери, следующий шаг, контакт
    add_column(conn, "order", "stage", "VARCHAR DEFAULT ''")
    add_column(conn, "order", "revisions", "INTEGER DEFAULT 0")
    add_column(conn, "order", "lost_reason", "VARCHAR")
    add_column(conn, "order", "last_contact_at", "DATETIME")
    add_column(conn, "order", "next_step", "VARCHAR DEFAULT ''")
    add_column(conn, "order", "next_step_at", "DATETIME")
    # --- клиент: источник лида, последний контакт, следующий шаг
    add_column(conn, "client", "source", "VARCHAR DEFAULT ''")
    add_column(conn, "client", "last_contact_at", "DATETIME")
    add_column(conn, "client", "next_step", "VARCHAR DEFAULT ''")
    add_column(conn, "client", "next_step_at", "DATETIME")
    # --- платёж: ключ идемпотентности (повтор с тем же ключом не создаёт второй доход)
    add_column(conn, "transaction", "idem_key", "VARCHAR")
    create_index(conn, "ix_transaction_idem_key", "transaction", '"idem_key"')
    # --- таблицы CRM (идемпотентно; имена совпадают с SQLModel-моделями в core/db.py)
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS crmactivity ("
        "id INTEGER PRIMARY KEY, order_id INTEGER, client_id INTEGER, kind VARCHAR, "
        "text VARCHAR, author VARCHAR, channel VARCHAR, created_at DATETIME)"
    ))
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS crmcomment ("
        "id INTEGER PRIMARY KEY, order_id INTEGER, client_id INTEGER, text VARCHAR, "
        "author VARCHAR, created_at DATETIME)"
    ))
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS crmchecklist ("
        "id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL, title VARCHAR, done BOOLEAN, "
        "position INTEGER, created_at DATETIME)"
    ))
    conn.execute(text(
        "CREATE TABLE IF NOT EXISTS crmfollowup ("
        "id INTEGER PRIMARY KEY, order_id INTEGER, client_id INTEGER, kind VARCHAR, text VARCHAR, "
        "due_at DATETIME, done BOOLEAN, done_at DATETIME, created_at DATETIME)"
    ))
    for name, table, cols in (("ix_crmactivity_order_id", "crmactivity", "order_id"),
                              ("ix_crmactivity_client_id", "crmactivity", "client_id"),
                              ("ix_crmcomment_order_id", "crmcomment", "order_id"),
                              ("ix_crmcomment_client_id", "crmcomment", "client_id"),
                              ("ix_crmchecklist_order_id", "crmchecklist", "order_id"),
                              ("ix_crmfollowup_order_id", "crmfollowup", "order_id"),
                              ("ix_crmfollowup_client_id", "crmfollowup", "client_id"),
                              ("ix_crmfollowup_kind", "crmfollowup", "kind")):
        create_index(conn, name, table, cols)
    # --- бэкфилл стадии для существующих заказов (только новая колонка, без потери данных)
    if table_exists(conn, "order"):
        conn.execute(text(
            "UPDATE \"order\" SET stage = CASE status "
            "WHEN 'new' THEN 'lead' WHEN 'work' THEN 'in_work' WHEN 'review' THEN 'revisions' "
            "WHEN 'done' THEN 'delivered' WHEN 'paid' THEN 'paid' WHEN 'cancelled' THEN 'lost' "
            "ELSE 'lead' END WHERE stage IS NULL OR stage = ''"
        ))


def _v3_client_stage(conn) -> None:
    """Стадия КЛИЕНТА (вторая сущность рядом с воронкой заказа): аддитивные колонки в `client`.

    Только новые колонки со значениями по умолчанию — существующие клиенты, заказы и
    финансы не меняются. Пустая `stage` означает «стадия считается автоматически по заказам».
    """
    add_column(conn, "client", "stage", "VARCHAR DEFAULT ''")
    add_column(conn, "client", "stage_manual", "BOOLEAN DEFAULT 0")
    add_column(conn, "client", "stage_auto", "VARCHAR DEFAULT ''")
    add_column(conn, "client", "stage_updated_at", "DATETIME")
    create_index(conn, "ix_client_stage", "client", '"stage"')


def _v4_indexes(conn) -> None:
    """Составные индексы под частые запросы (фаза «надёжность»): финансы по счёту/дате, задачи по срокам,
    журналы по ссылке, история чата и факты по слою. Только CREATE INDEX IF NOT EXISTS — никаких изменений
    данных; на старых базах колонки/таблицы проверяются, отсутствующее пропускается с предупреждением."""
    for name, table, cols in (
        ("ix_transaction_account", "transaction", '"account"'),
        ("ix_transaction_kind_date", "transaction", '"kind", "date"'),
        ("ix_task_due", "task", '"due"'),
        ("ix_task_done_due", "task", '"done", "due"'),
        ("ix_recurring_active_next_date", "recurring", '"active", "next_date"'),
        ("ix_memory_ref_table_ref_id", "memory", '"ref_table", "ref_id"'),
        ("ix_actionlog_ref_table_ref_id", "actionlog", '"ref_table", "ref_id"'),
        ("ix_actionlog_kind", "actionlog", '"kind"'),
        ("ix_embedding_model_ref_table_ref_id", "embedding", '"model", "ref_table", "ref_id"'),
        ("ix_chatmessage_role_created_at", "chatmessage", '"role", "created_at"'),
        ("ix_fact_layer_created_at", "fact", '"layer", "created_at"'),
    ):
        create_index(conn, name, table, cols)


def _v5_fact_decay(conn) -> None:
    """Память: колонки затухания фактов. Только ADD COLUMN, значения NULL = «ещё не было».

    fact.last_seen_at — когда факт последний раз встречался в реплике хозяина (не в промпте!);
    fact.confirmed_at — когда хозяин подтвердил предложение («да» в тосте) — такой факт не гаснет;
    fact.archived_at  — когда ушёл в архив (случай «затухло» отличается от ручного «забудь»)."""
    add_column(conn, "fact", "last_seen_at", "DATETIME")
    add_column(conn, "fact", "confirmed_at", "DATETIME")
    add_column(conn, "fact", "archived_at", "DATETIME")
    create_index(conn, "ix_fact_confirmed_at", "fact", '"confirmed_at"')


def _v6_lesson_applied(conn) -> None:
    """Уроки: когда урок реально подмешивался в промпт чата — чтобы выбирать свежие/уже применявшиеся
    и не показывать один и тот же урок подряд."""
    add_column(conn, "lesson", "applied", "BOOLEAN DEFAULT 0")
    add_column(conn, "lesson", "last_applied_at", "DATETIME")


# Порядковый номер — это версия схемы. Никогда не переиспользуем и не меняем задним числом.
MIGRATIONS: list[Migration] = [
    (1, "baseline: schema_version", _noop),
    (2, "crm: order.stage/revisions/next_step, client.source, transaction.idem_key, crm-таблицы", _v2_crm),
    (3, "crm: client.stage/stage_manual/stage_auto/stage_updated_at", _v3_client_stage),
    (4, "индексы: transaction/task/recurring/memory/action_log/embedding/chat_message/fact", _v4_indexes),
    (5, "память: fact.last_seen_at/confirmed_at/archived_at", _v5_fact_decay),
    (6, "уроки: lesson.applied/last_applied_at", _v6_lesson_applied),
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
    """Идемпотентно создать индекс (аддитивно, без удаления). Пропускает таблицу без нужных колонок:
    на старой базе колонка могла не появиться — индекс создавать не на чем, лучше предупредить, чем упасть."""
    if not table_exists(conn, table):
        return
    have = column_names(conn, table)
    wanted = {c.strip().strip('"`[]') for c in columns.split(",")}
    if not wanted <= have:
        log.warning("индекс %s пропущен: в таблице %s нет колонок %s", name, table, sorted(wanted - have))
        return
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
    """Максимальная применённая версия; 0 — таблицы `schema_version` ещё нет (миграции не применялись).

    Ошибка чтения (битая база, чужая схема) НЕ маскируется под «0»: раньше `except: return 0`
    превращал сбой в «миграций нет» и apply() молча повторно лез в схему. Теперь поднимаем
    исключение — init_db его залогирует (log.error), выставит флаг `migration:error` в settings
    и отдаст его в /api/status."""
    with engine.connect() as conn:
        exists = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )).first()
        if not exists:
            return 0   # таблицы нет — честно «ничего не применялось», это не ошибка
        try:
            row = conn.execute(text("SELECT MAX(version) FROM schema_version")).first()
        except Exception as e:
            log.error("не удалось прочитать версию схемы: %s", e)
            raise
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


def apply(engine: Engine, had_db: bool = True, backup_dir: str | Path | None = None,
          backup_taken: bool = False) -> dict:
    """Применить недостающие миграции по порядку.

    `had_db=False` — база только что создана с нуля (бэкапить нечего).
    `backup_taken=True` — копия уже снята ДО первых изменений схемы (init_db берёт её заранее,
    чтобы ни один ALTER не ушёл в файл раньше бэкапа) — второй раз не копируем.
    Возвращает {"from", "to", "applied": [версии], "backup": путь|None}.
    """
    _ensure_table(engine)
    cur = current_version(engine)
    todo = [m for m in MIGRATIONS if m[0] > cur]
    if not todo:
        return {"from": cur, "to": cur, "applied": [], "backup": None}
    backup = None if backup_taken else (backup_before_migration(engine, backup_dir) if had_db else None)
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
