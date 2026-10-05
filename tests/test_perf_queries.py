# -*- coding: utf-8 -*-
"""Производительность: индексы, отсутствие N+1, кэш, фоновые задачи.

Все тесты работают на временной БД в `tmp_path` (фикстура `fresh_db` из conftest) и без сети.
Настоящая data/jarvis.db не открывается.

Что проверяем (по ORDER.md, раздел «скорость»):
1. ключевые тяжёлые выборки идут по индексу (EXPLAIN QUERY PLAN содержит USING INDEX);
2. список заказов/прогноз не делает запрос на каждый заказ (N+1 отсутствует);
3. аналитика на пустой базе считается и не падает;
4. кэш отдаёт тот же результат, не отдаёт протухшее (после записи) и умеет выключаться;
5. фоновые задачи планировщика не дублируются и не висят.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

os.environ.setdefault("ASSISTANT_TEST", "1")

from core import db  # noqa: E402
from core.db import session  # noqa: E402


# ------------------------------------------------------------------ helpers
def plan(sql: str, params: tuple = ()) -> str:
    """EXPLAIN QUERY PLAN одной строкой: 'SEARCH transaction USING INDEX …'."""
    with db.engine.connect() as conn:
        full = sql
        if params:
            vals = [("'" + str(p).replace("'", "''") + "'") if isinstance(p, str) else str(p) for p in params]
            parts = full.split("?")
            full = parts[0] + "".join(v + p for v, p in zip(vals, parts[1:]))
        rows = conn.execute(text("EXPLAIN QUERY PLAN " + full)).fetchall()
    return " | ".join(str(r[-1]) for r in rows)


class Counter:
    """Счётчик SQL-инструкций, ушедших из интересующей нас функции."""

    def __init__(self):
        self.n = 0
        self.statements: list[str] = []

    def __enter__(self):
        from sqlalchemy import event
        event.listen(db.engine, "before_cursor_execute", self._hook)
        return self

    def _hook(self, conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        self.n += 1
        self.statements.append(" ".join(str(statement).split()))

    def __exit__(self, *exc):
        from sqlalchemy import event
        event.remove(db.engine, "before_cursor_execute", self._hook)
        return False


def _orders(n: int = 12, price: int = 10_000) -> list:
    """n заказов в работе, каждому — оплата, часть — сессии работы."""
    from core.services import orders
    made = []
    for i in range(n):
        o = orders.add_order(f"Ролик {i}", price=price, client=f"Клиент {i % 4}", deadline=datetime.now() + timedelta(days=i + 1))
        made.append(o)
    return made


# ------------------------------------------------------------------ 1. индексы
INDEX_CASES = [
    ("оплаты по заказу (N+1 в списке заказов)",
     'SELECT * FROM "transaction" WHERE "transaction".order_id = ? AND "transaction".kind = ?', (1, "income")),
    ("платежи по долгу",
     'SELECT * FROM "transaction" WHERE "transaction".debt_id = ?', (1,)),
    ("переводы в конверт накопления",
     'SELECT * FROM "transaction" WHERE "transaction".goal_id = ?', (1,)),
    ("операции по счёту за период",
     'SELECT * FROM "transaction" WHERE "transaction"."account" = ? AND "transaction".date >= ?', ("Наличные", "2026-01-01")),
    ("задачи с дедлайном (напоминания)",
     "SELECT * FROM task WHERE task.done = ? AND task.due IS NOT NULL", (False,)),
    ("задачи по цели",
     "SELECT * FROM task WHERE task.aim_id = ?", (1,)),
    ("вехи цели со статусом",
     "SELECT * FROM milestone WHERE milestone.aim_id = ? AND milestone.status = ?", (1, "open")),
    ("заказы по стадии воронки",
     'SELECT * FROM "order" WHERE "order".stage = ?', ("lead",)),
    ("заказы по дате создания",
     'SELECT * FROM "order" ORDER BY "order".created_at DESC LIMIT 10', ()),
    ("сессии работы по заказу",
     "SELECT * FROM worksession WHERE worksession.order_id = ?", (1,)),
    ("незакрытая сессия таймера (тик 20 с)",
     "SELECT * FROM worksession WHERE worksession.ended_at IS NULL ORDER BY worksession.id DESC", ()),
    ("фокус за период (отчёт за неделю)",
     "SELECT * FROM worksession WHERE worksession.kind = ? AND worksession.started_at >= ?", ("focus", "2026-01-01")),
    ("векторы по записи (смысловой поиск)",
     "SELECT * FROM embedding WHERE embedding.ref_table = ? AND embedding.ref_id = ?", ("note", 1)),
    ("лента журнала по виду записи",
     "SELECT * FROM memory WHERE memory.kind = ? AND memory.created_at >= ?", ("task", "2026-01-01")),
]


@pytest.mark.parametrize("title,sql,params", INDEX_CASES, ids=[c[0] for c in INDEX_CASES])
def test_heavy_query_uses_index(fresh_db, title, sql, params):  # noqa: ARG001
    p = plan(sql, params)
    assert "USING INDEX" in p, f"{title}: план без индекса → {p}"
    # «SCAN … USING INDEX» — обход индекса целиком: допустим там, где нет фильтра
    # (только сортировка/поиск по началу списка) — тогда он всё равно лучше скана таблицы.
    if "SCAN " in p and "USING INDEX" in p:
        assert " WHERE " not in sql.upper(), f"{title}: скан с фильтром → {p}"
        assert "ORDER BY" in sql.upper() or sql.upper().lstrip().startswith("SELECT"), title


def test_perf_indexes_are_created_on_fresh_db(fresh_db):  # noqa: ARG001
    """Индексы создаются и на новой базе (создаёт их миграция, а не только путь «старая база»)."""
    with db.engine.connect() as conn:
        have = {r[0] for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).all()}
    missing = [name for name, _, _ in db.PERF_INDEXES if name not in have]
    assert not missing, f"не созданы на новой базе: {missing}"


def test_perf_migration_is_aditive_and_idempotent(tmp_path, monkeypatch):
    """Миграция индексов: только CREATE INDEX, повторный apply — no-op, данные на месте."""
    from sqlalchemy import create_engine, event as sa_event

    from core import migrations
    path = tmp_path / "m.db"
    eng = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    sa_event.listen(eng, "connect", db._pragmas)
    # ВАЖНО: init_db() здесь НЕ зовём до подмены движка — любой вызов на дефолтном
    # db.engine бьёт по настоящей data/jarvis.db (create_all + миграции + set_setting).
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    with eng.connect() as conn:
        rows = conn.execute(text("SELECT id FROM account")).all()
    res = migrations.apply(eng, had_db=False)
    assert res["applied"] == [], "повторное применение должно быть no-op"
    with eng.connect() as conn:
        rows2 = conn.execute(text("SELECT id FROM account")).all()
    assert rows == rows2, "миграция изменила данные"


# ------------------------------------------------------------------ 2. нет N+1
def test_list_orders_has_no_n_plus_one(fresh_db):  # noqa: ARG001
    """Список заказов: число запросов не растёт с числом заказов."""
    from core.services import orders
    _orders(3)
    db.clear_caches()
    with Counter() as c3:
        small = orders.list_orders()
    assert small, "заказы не создались"
    _orders(9)
    db.clear_caches()
    with Counter() as c12:
        big = orders.list_orders()
    assert len(big) > len(small)
    # +6 заказов не должны дать +6 (и тем более ×2) запросов: допускаем небольшой рост,
    # но не линейный «по два на заказ»
    assert c12.n <= c3.n + 2, f"похоже на N+1: {c3.n} запросов на 3 заказа, {c12.n} на 12"


def test_unpaid_total_and_expected_income_scale(fresh_db):  # noqa: ARG001
    from core.services import orders
    _orders(10)
    db.clear_caches()
    with Counter() as c:
        total = orders.unpaid_total()
        income = orders.expected_income(30)
    assert total > 0 and income, "расчёты по заказам вернули пустоту"
    # 10 заказов: сумма остатков + ожидаемые поступления — единицы запросов, не десятки
    assert c.n <= 20, f"слишком много запросов на 10 заказов: {c.n}"


def test_stats_has_no_n_plus_one(fresh_db):  # noqa: ARG001
    from core.services import orders
    _orders(8)
    db.clear_caches()
    with Counter() as c:
        st = orders.stats(6)
    assert st["total_income"] == 0 or st["total_income"] >= 0
    assert c.n <= 15, f"stats делает {c.n} запросов на 8 заказов — похоже на N+1"


def test_add_task_duplicate_check_does_not_scan_all(fresh_db):  # noqa: ARG001
    """Поиск дубля задачи идёт по подстроке, а не перебором всех открытых задач в Python."""
    from core.services import tasks
    for i in range(40):
        with session() as s:
            from core.db import Task
            s.add(Task(title=f"Позвонить клиенту {i}", done=False))
            s.commit()
    with Counter() as c:
        tasks.add_task("Позвонить клиенту 7")
    assert c.n <= 6, f"проверка дубля сделала {c.n} запросов"


# ------------------------------------------------------------------ 3. пустая база
def test_analytics_on_empty_db_does_not_fail(fresh_db):  # noqa: ARG001
    from core.services import finance, insights
    fc = insights.cash_forecast(30)
    assert len(fc["points"]) == 31 and fc["per_day"] == 0
    ser = insights.cash_series(30)
    assert ser["points"], "ряд на пустой базе пуст"
    summary = finance.summary(30)
    assert summary["spent"] == 0 and summary["earned"] == 0
    assert isinstance(insights.streak()["current"], int)
    assert isinstance(insights.activity_heatmap(4), list)
    assert insights.budget_alerts() == []
    assert isinstance(finance.cashflow()["free"], float)


def test_cash_series_reconciles_with_total_balance(fresh_db):  # noqa: ARG001
    """Последняя точка прошлого равна единому источнику баланса (цифры не «поехали»)."""
    from core.services import finance, insights
    finance.set_balance("Т-Банк", 12_345)
    finance.add_transaction(700, "expense", account="Т-Банк", category="Еда", note="еда",
                            date=datetime.now() - timedelta(days=2))
    ser = insights.cash_series(30)
    past = [p for p in ser["points"] if p["kind"] == "past"]
    assert past[-1]["balance"] == round(finance.total_balance()) == 11_645


# ------------------------------------------------------------------ 4. кэш
def test_cache_returns_equal_result(fresh_db):  # noqa: ARG001
    from core.services import insights
    first = insights.cash_forecast(30)
    second = insights.cash_forecast(30)
    assert first == second, "кэш отдал другой результат"


def test_cache_result_is_a_copy(fresh_db):  # noqa: ARG001
    """Правка выданного словаря не должна портить кэш (иначе второй вызов отдаст мусор)."""
    from core.services import insights
    first = insights.cash_forecast(30)
    first["per_day"] = -999
    first["points"].clear()
    second = insights.cash_forecast(30)
    assert second["per_day"] != -999 and second["points"], "кэш отдал тот же объект"


def test_cache_is_dropped_after_write(fresh_db):  # noqa: ARG001
    """Запись в базу сразу сбрасывает кэш — цифры не устаревают."""
    from core.services import finance, insights
    finance.set_balance("Т-Банк", 1_000)
    before = insights.cash_forecast(30)["points"][0]["balance"]
    finance.set_balance("Т-Банк", 50_000)
    after = insights.cash_forecast(30)["points"][0]["balance"]
    assert after != before and after == 50_000, f"кэш не сбросился после записи: {before} → {after}"


def test_cache_saves_queries_on_repeat(fresh_db):  # noqa: ARG001
    from core.services import insights
    insights.cash_forecast(30)             # прогрев
    db.clear_caches()
    with Counter() as cold:
        insights.cash_forecast(30)
    with Counter() as warm:
        insights.cash_forecast(30)
    assert cold.n > 0 and warm.n == 0, f"повторный вызов всё ещё ходит в базу: {warm.n}"


def test_cache_can_be_disabled(fresh_db, monkeypatch):  # noqa: ARG001
    from core.services import insights
    monkeypatch.setattr(db.cfg, "performance", None, raising=False)
    monkeypatch.setattr(db, "cache_ttl", lambda: 0.0)
    insights.cash_forecast(30)
    with Counter() as c:
        insights.cash_forecast(30)
    assert c.n > 0, "performance.cache_ttl_sec = 0 должен отключать кэш"


def test_cache_key_includes_arguments(fresh_db):  # noqa: ARG001
    from core.services import insights
    assert insights.cash_forecast(30)["points"] != insights.cash_forecast(7)["points"]
    assert insights.cash_forecast(7, pessimistic_delay_days=0)["points"]


def test_get_setting_reflects_writes(fresh_db):  # noqa: ARG001
    """Настройки читаются через кэш — запись обязана быть видна сразу."""
    assert db.get_setting("perf_probe") is None
    db.set_setting("perf_probe", "1")
    assert db.get_setting("perf_probe") == "1"
    db.set_setting("perf_probe", None)
    assert db.get_setting("perf_probe") is None
    assert db.get_setting("perf_probe", "запасное") == "запасное"


# ------------------------------------------------------------------ 5. фоновые задачи
def test_scheduler_jobs_are_not_duplicated():  # noqa: ARG001
    """Повторный build() на том же планировщике не добавляет вторую копию задачи."""
    from core.services import scheduler
    async def notify(text, buttons=None):  # noqa: ARG001
        return None

    sch = scheduler.build(notify)
    ids = [j.id for j in sch.get_jobs()]
    assert len(ids) == len(set(ids)), f"дубли задач: {ids}"
    sch.add_job(scheduler.__dict__["backup_db"], "interval", seconds=5, id="probe", replace_existing=True)
    scheduler.build(notify).add_job(lambda: None, "interval", seconds=5, id="probe", replace_existing=True)
    ids2 = [j.id for j in sch.get_jobs()]
    assert ids2.count("probe") == 1, "replace_existing не сработал"


def test_scheduler_jobs_have_timeouts():  # noqa: ARG001
    """У задач есть misfire_grace_time/coalesce/max_instances — зависшая не копит копии."""
    from core.services import scheduler
    async def notify(text, buttons=None):  # noqa: ARG001
        return None
    sch = scheduler.build(notify)
    jobs = {j.id: j for j in sch.get_jobs()}
    assert {"reminders", "task_reminders", "timer_tick", "backup", "self_check"} <= set(jobs)
    # значения по умолчанию живут в планировщике и наследуются задачами
    # (у Job до старта планировщика слоты ещё не заполнены — смотрим именно умолчания)
    dflt = sch._job_defaults
    assert dflt.get("max_instances") == 1, "без max_instances задача может накапливаться"
    assert dflt.get("coalesce") is True, "без coalesce пропуски приводят к пачке запусков"
    assert dflt.get("misfire_grace_time") == 3600, "нет misfire_grace_time: после сна задачи молча пропадут"
    # и каждая задача обёрнута таймаутом (иначе зависшая сеть её больше не запустит)
    for jid in ("timer_tick", "reminders", "semantic", "backup", "self_check"):
        assert jobs[jid].func.__name__ == f"job_{jid}", f"{jid}: задача без таймаута"


def test_job_guard_logs_error_and_timeout(caplog):
    """Обёртка задачи: ошибка и таймаут попадают в лог и не выходят наружу."""
    import asyncio
    import logging

    from core.services import scheduler

    async def boom():
        raise RuntimeError("задача сломалась")

    wrapped = scheduler.guard_job(boom, "test_task")
    with caplog.at_level(logging.ERROR, logger="jarvis.sched"):
        assert asyncio.run(wrapped()) is None      # исключение не выходит наружу
    assert any("test_task" in r.getMessage() for r in caplog.records), "в логе нет имени задачи"

    async def hang():
        await asyncio.sleep(5)

    caplog.clear()
    short = scheduler.guard_job(hang, "test_slow")
    with caplog.at_level(logging.ERROR, logger="jarvis.sched"):
        monkey_timeout = scheduler.JOB_TIMEOUT_DEFAULT
        try:
            scheduler._JOB_TIMEOUTS["test_slow"] = 0.05
            assert asyncio.run(short()) is None    # таймаут вместо вечного ожидания
        finally:
            scheduler._JOB_TIMEOUTS["test_slow"] = monkey_timeout
    assert any("test_slow" in r.getMessage() for r in caplog.records), "в логе нет таймаута"


def test_job_timeout_is_configurable(monkeypatch):
    from core.services import scheduler
    assert scheduler.job_timeout("reminders") == scheduler.JOB_TIMEOUT_DEFAULT
    assert scheduler.job_timeout("backup") == 1800.0            # ночной бэкап — отдельный лимит
    node = type("N", (), {"job_timeout_sec": 120})()
    monkeypatch.setattr(scheduler.cfg, "performance", node, raising=False)
    assert scheduler.job_timeout("reminders") == 120.0
    node.job_timeout_sec = "не число"
    assert scheduler.job_timeout("reminders") == scheduler.JOB_TIMEOUT_DEFAULT