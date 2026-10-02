# -*- coding: utf-8 -*-
"""Замеры тяжёлых мест БД/аналитики на КОПИИ настоящей базы (data/jarvis.db只 читается).

Зачем: цифры «было/стало» для отчёта, а не догадки. Скрипт ничего не меняет в проекте:
настоящая база открывается строго на чтение (`file:…?mode=ro`), работа идёт с её копией в temp.

    .venv\\Scripts\\python.exe tools/perf_probe.py            # сводка по всем замерам
    .venv\\Scripts\\python.exe tools/perf_probe.py --queries  # + EXPLAIN QUERY PLAN тяжёлых запросов
    .venv\\Scripts\\python.exe tools/perf_probe.py --sql "SELECT …"   # план произвольного запроса

Что меряем: сколько SQL-запросов уходит из функции (счётчик на event-listener) и сколько
это миллисекунд. Счётчик — тот же приём, что в tests/test_perf_queries.py.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ASSISTANT_TEST", "1")

import asyncio  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402

from core import db  # noqa: E402

QUERIES: list[str] = []
_counter = {"n": 0}


def _on_cursor_execute(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
    _counter["n"] += 1
    QUERIES.append(" ".join(str(statement).split()))


def install_counter(eng) -> None:  # noqa: ANN001
    event.listen(eng, "before_cursor_execute", _on_cursor_execute)


def copy_real_db(dst: Path) -> Path:
    """Копия настоящей БД. Источник — ТОЛЬКО на чтение (mode=ro), как в тестах миграций."""
    src_path = ROOT / "data" / "jarvis.db"
    if not src_path.exists():
        raise SystemExit("data/jarvis.db не найдена — замеры невозможны")
    uri = "file:" + src_path.resolve().as_posix() + "?mode=ro"
    src = sqlite3.connect(uri, uri=True)
    out = sqlite3.connect(str(dst))
    try:
        with out:
            src.backup(out)
    finally:
        out.close()
        src.close()
    return dst


def _prep(dst: Path, migrate: bool = True):
    eng = create_engine(f"sqlite:///{dst}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    install_counter(eng)
    db.engine = eng
    if migrate:
        # копию приводим к последней версии схемы, иначе меряем на устаревших индексах
        from core import migrations
        migrations.apply(eng, had_db=False)
    return eng


def dump(name: str, fn) -> None:  # noqa: ANN001
    """Печатает список SQL, который уходит из функции (поиск дублей и N+1)."""
    _counter["n"] = 0
    QUERIES.clear()
    fn()
    print(f"\n=== {name}: {_counter['n']} запросов")
    for i, q in enumerate(QUERIES, 1):
        print(f"{i:3d}. {q[:170]}")


# ------------------------------------------------------------------ что меряем
def cases() -> list[tuple[str, object]]:
    from core.services import finance, insights, orders, scheduler, tasks
    from core.services import health
    return [
        ("finance.summary(30)", lambda: finance.summary(30)),
        ("finance.cashflow()", lambda: finance.cashflow()),
        ("finance.budgets()", lambda: finance.budgets()),
        ("finance.safe_to_spend()", lambda: finance.safe_to_spend()),
        ("finance.daily_series(30)", lambda: finance.daily_series(30)),
        ("insights.cash_forecast(30)", lambda: insights.cash_forecast(30)),
        ("insights.cash_forecast_text()", lambda: insights.cash_forecast_text()),
        ("insights.cash_series(30)", lambda: insights.cash_series(30)),
        ("insights.streak()", lambda: insights.streak()),
        ("insights.activity_heatmap(26)", lambda: insights.activity_heatmap(26)),
        ("insights.detect_subscriptions()", lambda: insights.detect_subscriptions()),
        ("orders.list_orders()", lambda: orders.list_orders()),
        ("orders.expected_income(30)", lambda: orders.expected_income(30)),
        ("orders.unpaid_total()", lambda: orders.unpaid_total()),
        ("tasks.list_tasks()", lambda: tasks.list_tasks()),
        ("tasks.due_task_reminders()", lambda: tasks.due_task_reminders()),
        ("scheduler.morning_facts()", lambda: scheduler.morning_facts()),
        ("scheduler.morning_digest_text(card=False)", lambda: scheduler.morning_digest_text(card=False)),
        ("health.diagnose()", lambda: asyncio.run(health.diagnose())),
    ]


def run_all(repeat: int = 3) -> None:
    rows = []
    for name, fn in cases():
        try:
            fn()          # прогрев: импорт, ленивые кэши, первый разбор моделей
        except Exception as e:  # noqa: BLE001
            rows.append((name, -1.0, -1, 0, f"ОШИБКА {type(e).__name__}: {e}"))
            continue
        # холодный замер: кэши сброшены, считаем настоящую цену функции
        cold_ms, cold_q = 1e9, 0
        for _ in range(repeat):
            db.clear_caches()
            _counter["n"] = 0
            t0 = time.perf_counter()
            fn()
            cold_ms = min(cold_ms, (time.perf_counter() - t0) * 1000)
            cold_q = _counter["n"]
        # тёплый замер: те же данные, кэш живой (как второй запрос с сайта)
        warm_ms, warm_q = 1e9, 0
        for _ in range(repeat):
            _counter["n"] = 0
            t0 = time.perf_counter()
            fn()
            warm_ms = min(warm_ms, (time.perf_counter() - t0) * 1000)
            warm_q = _counter["n"]
        rows.append((name, cold_ms, cold_q, warm_q, ""))
    width = max(len(r[0]) for r in rows)
    print(f"{'что'.ljust(width)}  холод мс  SQL   тёпл мс  SQL")
    print("-" * (width + 32))
    for name, cold, cq, wq, err in rows:
        print(f"{name.ljust(width)} {cold:8.1f} {cq:5d}  {wq:7.1f} {abs(wq):4d}  {err}")


HEAVY_QUERIES: list[tuple[str, str, tuple]] = [
    ("transactions 90 дней (cashflow/summary)",
     'SELECT * FROM "transaction" WHERE date >= ? ORDER BY date DESC LIMIT 100000', ("2026-01-01",)),
    ("transactions месяц по категории (budgets)",
     'SELECT * FROM "transaction" WHERE kind = ? AND date >= ?', ("expense", "2026-09-01")),
    ("transactions: траты без авто и долгов (cash_forecast)",
     'SELECT "date", amount FROM "transaction" WHERE date >= ? AND kind = ? '
     'AND (category IS NULL OR category != ?) AND (note IS NULL OR note NOT LIKE ?)',
     ("2026-09-01", "expense", "Долги", "%(авто)%")),
    ("transactions: по счёту и дате (отчёт по счёту)",
     'SELECT * FROM "transaction" WHERE "account" = ? AND date >= ? ORDER BY date DESC', ("Наличные", "2026-09-01")),
    ("tasks: открытые по сроку", "SELECT * FROM task WHERE done = 0 AND due IS NOT NULL", ()),
    ("tasks: список как на сайте",
     "SELECT * FROM task WHERE done = 0 ORDER BY done, priority, due, created_at LIMIT 50", ()),
    ("tasks: вечерний обзор (просрочено)",
     "SELECT * FROM task WHERE done = 0 AND due IS NOT NULL AND due <= ? ORDER BY priority, due", ("2026-10-02 23:59:59",)),
    ("memory: стрик (400 дней)",
     'SELECT created_at FROM memory WHERE created_at >= ? AND channel != ?', ("2025-01-01", "system")),
    ("events: напоминания", "SELECT * FROM event WHERE start >= ? ORDER BY start", ("2026-10-01",)),
    ("orders: незакрытые",
     'SELECT * FROM "order" WHERE status IN (\'new\',\'work\',\'review\',\'done\') ORDER BY created_at DESC LIMIT 300', ()),
    ("orders: все по клиенту (список)", 'SELECT * FROM "order" ORDER BY created_at DESC', ()),
    ("оплаты по заказу", 'SELECT * FROM "transaction" WHERE order_id = ? AND kind = \'income\'', (1,)),
    ("сессии по заказу", "SELECT * FROM worksession WHERE order_id = ? AND kind = 'focus'", (1,)),
    ("ходы агента за сутки", "SELECT ok FROM run WHERE created_at >= ?", ("2026-10-01",)),
    ("facts: слой+дата", "SELECT * FROM fact WHERE layer = ? AND created_at >= ?", ("short", "2026-09-01")),
    ("boards: доска заказа (кэш)", "SELECT * FROM board WHERE order_id IS NOT NULL AND archived = 0", ()),
    ("screenslot: сутки", "SELECT * FROM screenslot WHERE start >= ? ORDER BY start", ("2026-10-01",)),
    ("actionlog: по записи (undo)", "SELECT * FROM actionlog WHERE ref_table = ? AND ref_id = ?", ("task", 1)),
    ("chatmessage: последние", "SELECT * FROM chatmessage WHERE role = ? ORDER BY created_at LIMIT 20", ("user",)),
    ("run: неудачные за сутки", "SELECT COUNT(*) FROM run WHERE ok = 0 AND created_at >= ?", ("2026-10-01",)),
    ("worksession: фокус за сутки", "SELECT * FROM worksession WHERE kind = ? AND started_at >= ?", ("focus", "2026-10-01")),
    ("worksession: открытый таймер", "SELECT * FROM worksession WHERE ended_at IS NULL ORDER BY id DESC", ()),
    ("task: по цели", "SELECT * FROM task WHERE aim_id = ?", (1,)),
    ("milestone: по цели и статусу", "SELECT * FROM milestone WHERE aim_id = ? AND status = ?", (1, "open")),
    ("order: канбан по стадии", "SELECT * FROM \"order\" WHERE stage IN ('lead','spec') ORDER BY deadline", ()),
    ("client: по стадии", "SELECT * FROM client WHERE stage = ?", ("client",)),
    ("event: непрочитанные напоминания",
     "SELECT * FROM event WHERE start <= ? AND reminded = 0 ORDER BY start", ("2026-10-02 12:00:00",)),
    ("actionlog: последние действия", "SELECT * FROM actionlog ORDER BY id DESC LIMIT 10", ()),
    ("relation: связи заметки", "SELECT * FROM relation WHERE a = ? OR b = ?", ("note:1", "note:1")),
    ("embedding: по записи", "SELECT * FROM embedding WHERE ref_table = ? AND ref_id = ?", ("note", 1)),
    ("transaction: платежи по долгу", "SELECT * FROM \"transaction\" WHERE debt_id = ? ORDER BY date DESC", (1,)),
    ("transaction: конверт накопления", "SELECT * FROM \"transaction\" WHERE goal_id = ?", (1,)),
]


def explain(eng, title: str, sql: str, params: tuple = ()) -> None:  # noqa: ANN001
    """EXPLAIN QUERY PLAN. Параметры подставляем текстом — план строим на копии базы, риска нет."""
    from sqlalchemy import text
    full = sql
    if params:
        vals = [("'" + str(p).replace("'", "''") + "'") if isinstance(p, str) else str(p) for p in params]
        parts = sql.split("?")
        full = parts[0] + "".join(v + p for v, p in zip(vals, parts[1:]))
    with eng.connect() as conn:
        rows = conn.execute(text("EXPLAIN QUERY PLAN " + full)).fetchall()
    print(f"\n### {title}\n{full}")
    for r in rows:
        print("   ", r[-1])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", action="store_true", help="EXPLAIN QUERY PLAN тяжёлых запросов")
    ap.add_argument("--sql", default="", help="план произвольного запроса")
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--dump", default="", help="показать все SQL конкретной функции из cases()")
    ap.add_argument("--no-migrate", action="store_true", help="не применять миграции к копии")
    args = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="jarvis-perf-"))
    dst = copy_real_db(tmp / "copy.db")
    eng = _prep(dst, migrate=not args.no_migrate)
    try:
        if args.dump:
            fn = dict(cases())[args.dump]
            dump(args.dump, fn)
            return 0
        if args.sql:
            explain(eng, "произвольный запрос", args.sql)
            return 0
        if args.queries:
            for title, sql, params in HEAVY_QUERIES:
                explain(eng, title, sql, params)
            return 0
        run_all(args.repeat)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())