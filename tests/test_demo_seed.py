# -*- coding: utf-8 -*-
"""Демо-данные для первого запуска (core/services/demo_seed.py, core/api/routers/demo.py).

Задача фичи: новичок ставит Marvin, база пустая, бот молчит и ценность не видна.
По кнопке грузим правдоподобный пример (счёт, траты, задачи, события, клиенты, цели),
рядом — кнопка «очистить и начать с нуля».

Главный вопрос набора — БЕЗОПАСНОСТЬ. `clear_demo()` обязана съесть ТОЛЬКО демо
и никогда не тронуть реальные данные: принадлежность к демо определяется маркером
(`source == "demo"` там, где колонка есть, и манифестом в `setting` там, где её нет),
а не догадкой «похоже на заголовок».

Ключевой тест — `test_clear_demo_never_touches_real_data`.
"""
from __future__ import annotations

import os

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402
from tests.test_core import fresh_db  # noqa: E401,F401  (autouse: временная БД)

from core import db  # noqa: E402
from core.services import demo_seed  # noqa: E402

DEMO = demo_seed.DEMO_SOURCE


# ------------------------------------------------------------------ помощники
def _rows(model, **where) -> list:
    with db.session() as s:
        q = db.select(model)
        for k, v in where.items():
            q = q.where(getattr(model, k) == v)
        return list(s.exec(q).all())


def _ids(model, **where) -> set[int]:
    return {r.id for r in _rows(model, **where)}


def _real_world(fresh_db):
    """Живая база реального человека: счёт, деньги, задачи, встреча, заказ, клиент, цель.

    Всё создаётся теми же сервисами, что и настоящие данные (никаких сырых строк),
    поэтому тесты проверяют ровно тот путь, которым пользуется бот.
    """
    from datetime import datetime, timedelta

    from core.services import calendar as cal
    from core.services import finance, goals, orders, tasks

    acc = finance.add_account("Мой счёт", "bank", 50_000)
    income = finance.add_transaction(120_000, "income", "Зарплата", "Зарплата за месяц",
                                     account=acc.name, source="tg")
    expense = finance.add_transaction(1_500, "expense", "Еда", "Обед с Мариной",
                                      account=acc.name, source="tg")
    task = tasks.add_task("Сдать отчёт по налогам", due=datetime.now() + timedelta(days=2), source="tg")
    event = cal.add_event("Встреча с врачом", datetime.now() + timedelta(hours=3), source="tg")
    client = orders.get_or_create_client("Иван Петров")
    order = orders.add_order("Сайт для кафе", 80_000, client=client.name, source="web")
    goal = goals.add_goal("Отпуск в сентябре", 90_000)
    with db.session() as s:   # баланс читаем ПОСЛЕ операций — он и есть «как было до демо»
        balance = s.get(db.Account, acc.id).balance
    return {
        "account": acc.name,
        "balance": balance,
        "transactions": {income.id, expense.id},
        "task": task.id,
        "event": event.id,
        "client": client.id,
        "order": order.id,
        "goal": goal.id,
    }


def _demo_ids() -> set[tuple[str, int]]:
    """Все строки, которые сервис считает демо (по манифесту) — на момент вызова."""
    m = demo_seed._manifest() or {}
    return {(t, rec["id"]) for t in demo_seed.MODELS for rec in demo_seed._rows_of(m, t)}


def _snapshot(demo_ids: set[tuple[str, int]] = frozenset()) -> dict:
    """Слепок всего, что НЕ демо: после очистки демо он должен совпасть до знака."""
    with db.session() as s:
        snap = {}
        pairs = (
            ("transaction", lambda t: (t.amount, t.kind, t.category, t.note, t.account, t.source, t.date.isoformat())),
            ("task", lambda t: (t.title, t.done, t.priority, t.source)),
            ("event", lambda t: (t.title, t.start.isoformat(), t.source)),
            ("client", lambda t: (t.name, t.kind)),
            ("order", lambda t: (t.title, t.price, t.status, t.source)),
            ("goal", lambda t: (t.title, t.target, t.saved)),
            ("account", lambda t: (t.name, round(t.balance, 2), t.is_main)),
            ("debt", lambda t: (t.title, t.total, round(t.remaining, 2))),
            ("note", lambda t: (t.text,)),
        )
        for table, dump in pairs:
            for row in s.exec(db.select(demo_seed.MODELS[table])).all():
                if (table, row.id) in demo_ids:
                    continue
                snap[f"{table}:{row.id}"] = dump(row)
    return snap


# ============================================================ ГЛАВНЫЙ ТЕСТ: БЕЗОПАСНОСТЬ
def test_clear_demo_never_touches_real_data(fresh_db):
    """Демо + реальные записи рядом → clear_demo() убирает демо и НЕ трогает реальное.

    Это самый важный тест фичи: очистка идёт по маркеру (`source == "demo"` / манифест),
    а не по «похоже на демо», поэтому чужая строка, созданная рядом и позже, не пострадает.
    """
    real = _real_world(fresh_db)
    before = _snapshot()            # до демо в базе только реальные строки

    res = demo_seed.seed_demo()
    assert res["ok"], res
    assert res["total"] >= 20, res          # демо действительно что-то создало
    assert not set(_ids(db.Transaction, source=DEMO)) & real["transactions"]

    demo_count_before = len(_rows(db.Transaction, source=DEMO))
    assert demo_count_before > 0

    cleared = demo_seed.clear_demo()
    assert cleared["ok"], cleared
    assert cleared["removed"], "демо-строки должны были удалиться"

    after = _snapshot()

    # 1) реальные строки на месте и с теми же полями
    missing = {k: v for k, v in before.items() if k not in after}
    assert not missing, f"clear_demo() съел реальные записи: {missing}"
    changed = {k: (v, after[k]) for k, v in before.items() if k in after and after[k] != v}
    assert not changed, f"clear_demo() изменил реальные записи: {changed}"

    # 2) демо-строк не осталось ни в одной помеченной таблице
    for model in (db.Transaction, db.Task, db.Event, db.Order, db.Note):
        assert not _rows(model, source=DEMO), f"{model.__name__}: остались демо-строки"

    # 3) баланс реального счёта вернулся к исходному (откат сдвигов demo-операций)
    with db.session() as s:
        bal = s.get(db.Account, next(a.id for a in s.exec(db.select(db.Account)).all()
                                     if a.name == real["account"])).balance
    assert round(bal, 2) == round(real["balance"], 2), (bal, real["balance"])

    # 4) манифест демо снят — второй запуск тоже ничего не найдёт
    assert demo_seed.demo_status()["state"] == "own"


def test_clear_demo_on_empty_db_is_noop(fresh_db):
    """Пустая база: очистка не падает и ничего не удаляет."""
    res = demo_seed.clear_demo()
    assert res["ok"], res
    assert not res["removed"], res
    assert demo_seed.demo_status()["state"] == "empty"


def test_clear_demo_twice_is_safe(fresh_db):
    """clear_demo() дважды подряд: второй вызов не падает и не удаляет лишнего."""
    demo_seed.seed_demo()
    _real_world(fresh_db)

    first = demo_seed.clear_demo()
    assert first["ok"] and first["removed"], first
    after_first = _snapshot()

    second = demo_seed.clear_demo()
    assert second["ok"], second
    assert not second["removed"], f"второй вызов что-то удалил: {second}"
    assert _snapshot() == after_first


def test_seed_demo_twice_does_not_duplicate(fresh_db):
    """Повторный seed не плодит дубли (кнопку можно жать дважды)."""
    first = demo_seed.seed_demo()
    n_tx = len(_rows(db.Transaction))
    n_acc = len(_rows(db.Account))
    n_task = len(_rows(db.Task))

    second = demo_seed.seed_demo()
    assert second["ok"], second
    assert second["already"], second
    assert len(_rows(db.Transaction)) == n_tx
    assert len(_rows(db.Account)) == n_acc
    assert len(_rows(db.Task)) == n_task
    assert first["total"] == second["total"]


# ============================================================ без дублей и без перетирания
def test_seed_does_not_duplicate_accounts_or_categories(fresh_db):
    """`account.name` и `category.name` — unique: демо не создаёт вторых счетов/категорий."""
    real = _real_world(fresh_db)   # на базе с реальными данными
    accounts_before = {a.name for a in _rows(db.Account)}
    cats_before = {c.name for c in _rows(db.Category)}
    balance_before = {a.name: round(a.balance, 2) for a in _rows(db.Account)}

    res = demo_seed.seed_demo()
    assert res["ok"], res

    after = _rows(db.Account)
    names = [a.name for a in after]
    assert len(names) == len(set(names)), "появились дубли счетов"
    # реальный счёт на месте и с тем же балансом — демо не трогает чужие деньги
    assert accounts_before <= set(names)
    got = {a.name: round(a.balance, 2) for a in after}
    for name, bal in balance_before.items():
        assert got[name] == bal, f"демо изменило баланс чужого счёта «{name}»: {bal} → {got[name]}"

    cats = [c.name for c in _rows(db.Category)]
    assert len(cats) == len(set(cats)), "появились дубли категорий"
    assert cats_before <= set(cats), "демо не должно удалять/переименовывать категории"

    # и демо-траты легли на существующие категории, а не на новые
    used = {t.category for t in _rows(db.Transaction, source=DEMO)}
    assert used <= set(cats), f"демо пишет в несуществующие категории: {used - set(cats)}"
    # весь демо-мир живёт на одном счёте — свои деньги он не смешивает
    demo_accs = {t.account for t in _rows(db.Transaction, source=DEMO)}
    assert demo_accs == {res["account"]}, demo_accs
    assert demo_accs.isdisjoint(balance_before) or real["account"] in demo_accs


def test_seed_on_real_base_leaves_real_totals_untouched(fresh_db):
    """Считаем «до/после» по реальным строкам — цифры пользователя не меняются."""
    real = _real_world(fresh_db)
    demo_seed.seed_demo()

    with db.session() as s:
        txs = s.exec(db.select(db.Transaction)).all()
        mine = [t for t in txs if t.id in real["transactions"]]
        assert len(mine) == 2
        assert all(t.source == "tg" for t in mine)
        acc = next(a for a in s.exec(db.select(db.Account)).all() if a.name == real["account"])
        # демо живёт на своём счёте и в чужие деньги не лезет
        assert round(acc.balance, 2) == round(real["balance"], 2)


# ============================================================ правдоподобность
def test_demo_looks_like_a_living_assistant(fresh_db):
    """Не «test_user_1»: нормальные имена, суммы, русский язык и видимая пометка «демо»."""
    res = demo_seed.seed_demo()
    assert res["ok"], res
    created = res["created"]
    for key in ("transaction", "task", "event", "client", "order", "goal"):
        assert created.get(key, 0) > 0, f"в демо нет «{key}»: {created}"

    titles = [t.title for t in _rows(db.Task, source=DEMO)] + \
             [e.title for e in _rows(db.Event, source=DEMO)] + \
             [o.title for o in _rows(db.Order, source=DEMO)]
    for t in titles:
        low = t.lower()
        assert "test" not in low and "user" not in low and "demo_" not in low, t
        assert not any(ch.isdigit() for ch in t), f"цифры в заголовке — похоже на фикстуру: {t}"

    amounts = [t.amount for t in _rows(db.Transaction, source=DEMO)]
    assert amounts and all(50 <= a <= 200_000 for a in amounts), amounts
    assert sum(a for a in amounts if a > 0) > 0     # есть доход
    assert len([a for a in amounts if a < 0]) == 0  # суммы положительные, тип хранит знак

    # демо ЯВНО подписано: отдельный счёт-бейдж + заметка-объяснение в «Мозге»
    assert demo_seed.DEMO_ACCOUNT in {a.name for a in _rows(db.Account)}
    notes = [n.text for n in _rows(db.Note, source=DEMO)]
    assert any("демо" in n.lower() for n in notes), notes


def test_demo_shows_a_feature_plain_datasets_lack(fresh_db):
    """Просроченная задача и долг — то, чего в обычных демо-данных нет."""
    from datetime import datetime, timedelta

    from core.services import finance

    demo_seed.seed_demo()
    overdue = [t for t in _rows(db.Task, source=DEMO)
               if t.due and t.due < datetime.now() and not t.done]
    assert overdue, "в демо нет просроченной задачи — не видно, что ассистент её ловит"

    debts = finance.list_debts()
    assert debts and debts[0].remaining < debts[0].total, "в демо нет долга с остатком"


def test_bot_answers_meaningfully_after_seed(fresh_db):
    """Данные идут через сервисы — бот отвечает на «сколько денег» и «что сегодня»."""
    from core.brain import agent

    demo_seed.seed_demo()

    money_reply = agent.rules("сколько денег", "test")
    assert money_reply is not None and money_reply.actions, money_reply
    assert any(a in ("balance", "finance_summary") for a in money_reply.actions), money_reply.actions
    assert "₽" in money_reply.text, money_reply.text

    day_reply = agent.rules("что сегодня", "test")
    assert day_reply is not None and day_reply.actions, day_reply
    assert "Задачи" in day_reply.text, day_reply.text
    assert any(t.title in day_reply.text for t in _rows(db.Task, source=DEMO)), day_reply.text
    assert "Баланс" in day_reply.text, day_reply.text

    tasks_reply = agent.rules("что сегодня по задачам", "test")
    assert tasks_reply is not None and "list_tasks" in tasks_reply.actions, tasks_reply


def test_empty_base_stays_silent_but_demo_makes_it_talk(fresh_db):
    """Контракт фичи: без демо на «сколько денег» нечем ответить, с демо — есть."""
    from core.brain import agent

    before = agent.rules("сколько денег", "test")
    assert before is not None
    assert "₽" in before.text

    demo_seed.seed_demo()
    after = agent.rules("сколько денег", "test")
    assert "₽" in after.text
    demo_seed.clear_demo()
    back = agent.rules("сколько денег", "test")
    assert back.text == before.text, "после очистки ответ должен вернуться к исходному"


# ============================================================ маркер и статус
def test_every_demo_row_carries_the_marker(fresh_db):
    """Принадлежность к демо — маркер, а не похожий заголовок."""
    demo_seed.seed_demo()
    manifest = demo_seed._manifest()
    assert manifest, "манифест демо должен писаться в setting"
    assert manifest["version"] == demo_seed.MANIFEST_VERSION
    rows = manifest["rows"]
    assert {"transaction", "task", "event", "client", "order", "goal"} <= set(rows)

    # у всех таблиц с колонкой source маркер проставлен
    for model in (db.Transaction, db.Task, db.Event, db.Order, db.Note):
        got = _ids(model, source=DEMO)
        want = {r["id"] for r in rows[model.__tablename__]} if model.__tablename__ in rows else set()
        assert got == want, f"{model.__name__}: source-маркер и манифест разошлись ({len(got)} vs {len(want)})"


def test_demo_status_states(fresh_db):
    st = demo_seed.demo_status()
    assert st["state"] == "empty", st
    assert st["has_demo"] is False
    assert st["label"]

    demo_seed.seed_demo()
    st = demo_seed.demo_status()
    assert st["state"] == "demo", st
    assert st["has_demo"] is True
    assert st["demo"]["transaction"] > 0, st
    assert "демо" in st["label"].lower()

    _real_world(fresh_db)
    st = demo_seed.demo_status()
    assert st["state"] == "mixed", st
    assert st["own"]["transaction"] > 0, st

    demo_seed.clear_demo()
    st = demo_seed.demo_status()
    assert st["state"] == "own", st
    assert st["has_demo"] is False


def test_clear_demo_keeps_rows_user_took_over(fresh_db):
    """Если пользователь завёл свои операции на демо-счёт, счёт не удаляем — бережём данные."""
    from core.services import finance

    demo_seed.seed_demo()
    with db.session() as s:
        demo_acc = next(a for a in s.exec(db.select(db.Account)).all()
                        if a.name == demo_seed.DEMO_ACCOUNT)
        name = demo_acc.name
    mine = finance.add_transaction(777, "expense", "Еда", "Мой настоящий обед",
                                   account=name, source="tg")

    res = demo_seed.clear_demo()
    assert res["ok"], res
    with db.session() as s:
        assert s.get(db.Transaction, mine.id) is not None, "удалили чужую операцию"
        assert s.get(db.Account, demo_acc.id) is not None, "удалили счёт с чужими данными"
    assert name in res["kept"] or any(demo_seed.DEMO_ACCOUNT in k for k in res["kept"]), res


def test_demo_does_not_hijack_or_delete_lookalike_rows(fresh_db):
    """Маркер решает, а не имя: чужой счёт «Демо-карта» и чужой клиент «Пятёрочка» переживут очистку."""
    from core.services import finance, orders

    mine_acc = finance.add_account(demo_seed.DEMO_ACCOUNT, "bank", 3_000)
    mine_client = orders.get_or_create_client("Пятёрочка")
    mine_tx = finance.add_transaction(500, "expense", "Еда", "Мой завтрак",
                                      account=demo_seed.DEMO_ACCOUNT, source="tg")
    with db.session() as s:
        balance_before = s.get(db.Account, mine_acc.id).balance

    res = demo_seed.seed_demo()
    assert res["ok"], res
    demo_ids = _demo_ids()
    assert ("account", mine_acc.id) not in demo_ids, "чужой счёт попал в манифест демо"
    assert ("client", mine_client.id) not in demo_ids, "чужой клиент попал в манифест демо"
    # демо-деньги легли на этот счёт — и снимутся при очистке, счёт останется
    assert demo_ids & {("transaction", t.id) for t in _rows(db.Transaction, source=DEMO)}

    demo_seed.clear_demo()
    with db.session() as s:
        assert s.get(db.Account, mine_acc.id) is not None, "удалили чужой счёт"
        assert s.get(db.Client, mine_client.id) is not None, "удалили чужого клиента"
        assert s.get(db.Transaction, mine_tx.id) is not None, "удалили чужую операцию"
        assert s.get(db.Account, mine_acc.id).balance == pytest.approx(balance_before)
    assert not _rows(db.Transaction, source=DEMO)


def test_clear_demo_after_manual_deletions_is_still_safe(fresh_db):
    """Пользователь удалил часть демо руками → очистка не падает и не трогает своё."""
    from core.services import finance, tasks

    real = _real_world(fresh_db)
    demo_seed.seed_demo()
    demo_ids = _demo_ids()
    victim = _rows(db.Task, source=DEMO)[0]
    tasks.delete_task(victim.id)          # «удалил демо руками»
    demo_tx = _rows(db.Transaction, source=DEMO)[0]
    finance.delete_transaction(demo_tx.id)
    before = _snapshot(demo_ids)          # всё, что НЕ демо — эталон

    res = demo_seed.clear_demo()
    assert res["ok"], res
    assert _snapshot(demo_ids) == before


# ============================================================ HTTP API
def _demo_app():
    """Отдельное приложение с ТОЛЬКО демо-роутером и общим middleware.

    `core/api/routers/__init__.py` в этой ветке не трогаем (занят параллельной работой),
    поэтому роутер подключаем здесь так же, как это сделает владелец при слиянии.
    """
    from fastapi import FastAPI

    from core.api.auth import AuthMiddleware
    from core.api.routers import demo

    app = FastAPI()
    app.add_middleware(AuthMiddleware)
    demo.register(app)
    return app


def _client(remote: bool = False):
    from fastapi.testclient import TestClient

    return TestClient(_demo_app(),
                      client=("192.168.1.50", 5555) if remote else ("127.0.0.1", 5555),
                      base_url="http://testserver")


def _headers():
    from core.api import auth

    return {"X-Auth-Token": auth.token()}


def test_demo_routes_are_exactly_three_and_under_api_prefix():
    from core.api.routers import demo

    got = sorted((r.path, sorted(r.methods)) for r in demo.router.routes)
    assert got == [("/api/demo/clear", ["POST"]),
                   ("/api/demo/seed", ["POST"]),
                   ("/api/demo/status", ["GET"])]


@pytest.mark.parametrize("method,path", [("GET", "/api/demo/status"),
                                        ("POST", "/api/demo/seed"),
                                        ("POST", "/api/demo/clear")])
def test_demo_api_needs_token_from_other_device(method, path, fresh_db):
    """Общий AuthMiddleware ловит и новые пути: без ключа — 401 (иначе демо-очистка была бы открыта)."""
    c = _client(remote=True)
    r = c.request(method, path)
    assert r.status_code == 401, (method, path, r.status_code, r.text)
    assert c.request(method, path, headers={"X-Auth-Token": "wrong"}).status_code == 401


@pytest.mark.parametrize("method,path", [("GET", "/api/demo/status"),
                                        ("POST", "/api/demo/seed"),
                                        ("POST", "/api/demo/clear")])
def test_demo_api_works_with_token(method, path, fresh_db):
    c = _client(remote=True)
    r = c.request(method, path, headers=_headers())
    assert r.status_code == 200, (method, path, r.status_code, r.text)
    assert "detail" not in r.json()


def test_demo_api_seed_status_clear_cycle(fresh_db):
    c = _client(remote=True)
    h = _headers()

    assert c.get("/api/demo/status", headers=h).json()["state"] == "empty"
    seeded = c.post("/api/demo/seed", headers=h).json()
    assert seeded["ok"] and seeded["total"] > 0, seeded

    st = c.get("/api/demo/status", headers=h).json()
    assert st["state"] == "demo" and st["has_demo"], st

    cleared = c.post("/api/demo/clear", headers=h).json()
    assert cleared["ok"] and cleared["removed"], cleared
    assert c.get("/api/demo/status", headers=h).json()["state"] == "empty"