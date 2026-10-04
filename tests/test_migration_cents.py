# -*- coding: utf-8 -*-
"""F1: миграция денег в целые копейки (v8, `<col>_cents INTEGER` + бэкфилл из float).

Проверяется ТОЛЬКО на scratch-БД в tmp_path — data/jarvis.db не трогается.

Правило округления бэкфилла (зафиксировано здесь, см. _v8_money_cents):
SQLite ROUND = half away from zero, применённый к произведению в бинарном double.
Отсюда неочевидные, но детерминированные значения (проверены прямым прогоном в sqlite3):
- 2.675 -> 268, т.к. 2.675*100 в double ровно 267.5, а .5 уводит от нуля;
- 1.005 -> 100, т.к. 1.005*100 в double = 100.49999999999999 (до половины не дотягивает);
- 0.5   -> 50 (точное значение, без сюрпризов).
Это НЕ Python round() (там banker's rounding) и НЕ Decimal(str(x)) с ROUND_HALF_UP
из finance.money() (там 1.005 -> 101): на непредставимых в double значениях вида x.xx5
витрина и бэкфилл могут разойтись на 1 копейку — приемлемо для бэкфилла истории.

Перевод кода на ЧТЕНИЕ _cents — OUT OF SCOPE (отдельный таск): здесь проверяем только
схему, бэкфилл, сохранность float-колонок и идемпотентность.
"""
from __future__ import annotations

import os

os.environ.setdefault("ASSISTANT_TEST", "1")

from datetime import datetime  # noqa: E402

from sqlalchemy import text  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from core import migrations  # noqa: E402
from core.db import Account, Category, Debt, Goal, Order, Recurring, Transaction  # noqa: E402


def _build_legacy_db(path):
    """Старая схема: все таблицы по моделям (float-колонки денег, _cents ещё нет)."""
    eng = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        s.add(Transaction(amount=2.675, kind="expense", category="Еда",
                          account="Наличные", date=datetime(2026, 9, 1, 12, 0)))
        s.add(Transaction(amount=10.0, kind="income", category="Фриланс",
                          account="Т-Банк", date=datetime(2026, 9, 2, 12, 0)))
        s.add(Debt(title="Сбер кредит", total=1.005, remaining=0.5, payment=1999.99))
        s.add(Goal(title="Подушка", target=300000.0, saved=1234.56))
        s.add(Account(name="Наличные", kind="cash", balance=10.0))
        s.add(Category(name="Еда", kind="expense", budget=50000.0))
        s.add(Recurring(title="Аренда", amount=999.99, account="Т-Банк",
                        next_date=datetime(2026, 10, 1)))
        s.add(Order(title="Ролик", price=25000.50, status="work"))
        s.commit()
    return eng


def _cents(eng, table, col="amount"):
    with eng.connect() as conn:
        return conn.execute(text(f'SELECT "{col}_cents" FROM "{table}" ORDER BY id')).scalars().all()


def test_v8_money_cents_backfill_and_floats_intact(tmp_path):
    db_file = tmp_path / "legacy.db"
    eng = _build_legacy_db(db_file)

    res = migrations.apply(eng, had_db=True, backup_dir=tmp_path / "bk")

    assert 8 in res["applied"], "v8 должна примениться на старой БД"
    assert migrations.current_version(eng) == max(v for v, _, _ in migrations.MIGRATIONS)
    # пре-миграционный бэкап штатным хелпером (как у всех предыдущих версий)
    assert res["backup"] and os.path.exists(res["backup"])

    # бэкфилл: см. правило округления в шапке файла
    assert _cents(eng, "transaction") == [268, 1000]          # 2.675 -> 268; 10.0 -> 1000
    assert _cents(eng, "debt", "total") == [100]              # 1.005 -> 100 (double 100.4999…)
    assert _cents(eng, "debt", "remaining") == [50]           # 0.5 -> 50
    assert _cents(eng, "debt", "payment") == [199999]
    assert _cents(eng, "goal", "target") == [30000000]
    assert _cents(eng, "goal", "saved") == [123456]
    assert _cents(eng, "account", "balance") == [1000]
    assert _cents(eng, "category", "budget") == [5000000]
    assert _cents(eng, "recurring") == [99999]
    assert _cents(eng, "order", "price") == [2500050]

    # старые float-колонки на месте, значения не тронуты (rollback safety)
    with eng.connect() as conn:
        assert conn.execute(text('SELECT amount FROM "transaction" ORDER BY id')
                            ).scalars().all() == [2.675, 10.0]
        assert conn.execute(text('SELECT total, remaining, payment FROM debt')).all() == [
            (1.005, 0.5, 1999.99)]
        assert conn.execute(text('SELECT target, saved FROM goal')).all() == [
            (300000.0, 1234.56)]
        assert conn.execute(text('SELECT balance FROM account')).scalar() == 10.0
        assert conn.execute(text('SELECT budget FROM category')).scalar() == 50000.0
        assert conn.execute(text('SELECT amount FROM recurring')).scalar() == 999.99
        assert conn.execute(text('SELECT price FROM "order"')).scalar() == 25000.50
        # NULL денег остаётся NULL центов, а не 0 (проверка семантики выражения бэкфилла)
        assert conn.execute(
            text("SELECT CAST(ROUND(CAST(NULL AS FLOAT) * 100) AS INTEGER)")).scalar() is None

    # идемпотентность: повторный прогон — no-op (ничего не применено, бэкапа нет,
    # значения центов те же — UPDATE ... WHERE _cents IS NULL никого не задел)
    again = migrations.apply(eng, had_db=True, backup_dir=tmp_path / "bk")
    assert again["applied"] == [] and again["backup"] is None
    assert _cents(eng, "transaction") == [268, 1000]
    assert _cents(eng, "goal", "saved") == [123456]


def test_v8_fn_rerun_fills_late_null_rows(tmp_path):
    """Строка, вставленная с NULL _cents уже после v8 (код пока пишет только float),
    добивается повторным вызовом самой функции миграции — бэкфилл по IS NULL
    (apply() повторно версии не гоняет: `applied == []`, это проверено выше)."""
    eng = _build_legacy_db(tmp_path / "late.db")
    migrations.apply(eng, had_db=True, backup_dir=tmp_path / "bk")
    v8 = next(fn for v, _, fn in migrations.MIGRATIONS if v == 8)
    with eng.begin() as conn:
        conn.execute(text(
            'INSERT INTO "transaction" (amount, kind, source, date) VALUES (0.07, \'expense\', \'test\', \'2026-09-03 12:00:00\')'))
    with eng.connect() as conn:
        assert conn.execute(
            text("SELECT amount_cents FROM \"transaction\" WHERE amount_cents IS NULL")
        ).first() is not None
    with eng.begin() as conn:
        v8(conn)  # прямой повтор v8: ADD — no-op, UPDATE добивает только NULL-строки
    assert _cents(eng, "transaction") == [268, 1000, 7]
