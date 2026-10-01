"""Финансы, аналитика, экспорт (ФАЗА 7, шаг 7.1).

Роуты перенесены из `core/api/app.py` МЕХАНИЧЕСКИ: пути, методы, тела функций,
порядок ответов и логика не менялись. Декораторы сохраняют полный путь
(`/api/...`), поэтому `router` создаётся БЕЗ prefix — пути совпадают 1:1.

Инвариант регистрации (см. `core/api/routers/__init__.py`): `register(app)`
вызывается из `app.py` ПОСЛЕ `include_router(_crm_router)` и ДО статики и
catch-all SPA. Порядок роутов внутри модуля = порядок в `app.py` на шаге 7.0.

Локальные импорты внутри тел роутов сохранены как есть (в проекте это осознанный
приём: быстрый старт, обход циклов) — у них ровно на одну точку больше,
т.к. модуль лежит на уровне `core/api/routers/`.
"""
from __future__ import annotations

import asyncio as _asyncio
import json as _json
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request

from ...brain import agent
from ...db import Debt, Event, Link, Note, Recurring, Task, Transaction, session
from ...services import finance, goals, insights
from .._shared import broadcast
from ..schemas import (TxIn, TxPatch, CategoryIn, CategoryPatch, BalanceIn, AccountIn, AccountPatch, DebtIn,
                       PayIn, DebtPatch, RecurringIn, RecurringPatch, GoalIn, GoalPatch, GoalPut)

router = APIRouter()


def register(app) -> None:
    app.include_router(router)


@router.post("/api/finance/import")
async def finance_import(request: Request):
    """Импорт выписки (CSV/PDF/XLSX Т-Банка). multipart: file=..., account=... (необязательно)."""
    from ...services import bank_import
    form = await request.form()
    up = form.get("file")
    if up is None:
        raise HTTPException(400, "Нет файла")
    data = await up.read()
    if len(data) > 25 * 1024 * 1024:
        raise HTTPException(413, "Выписка больше 25 МБ")
    res = bank_import.import_file(up.filename or "", data, (form.get("account") or None))
    if res.added:
        broadcast("chat", {"channel": "web", "actions": ["import"]})
    agent._log_chat("assistant", res.text(), "web")
    return {"ok": bool(res.rows), "text": res.text(), "added": res.added, "dup": res.skipped_dup, "rows": res.rows}


# ---------------- аналитика ----------------
@router.get("/api/insights/forecast")
def insights_forecast(days: int = 30):
    from ...services import insights
    return {**insights.cash_forecast(days), "text": insights.cash_forecast_text()}


@router.get("/api/insights/subscriptions")
def insights_subs():
    from ...services import insights
    return insights.detect_subscriptions()


@router.get("/api/insights/streak")
def insights_streak():
    from ...services import insights
    return {**insights.streak(), "heatmap": insights.activity_heatmap(26)}


@router.get("/api/insights/birthdays")
def insights_bdays(days: int = 14):
    from ...services import insights
    return insights.upcoming_birthdays(days)


@router.get("/api/insights/weekly")
async def insights_weekly():
    from ...services import insights
    return {"text": await insights.weekly_digest() or "За неделю заметок не было — обозревать нечего, сэр."}


@router.get("/api/missed")
def missed_endpoint():
    """«Что я упускаю»: один экран упущений (просроченные оплаты, долги, дела без срока, цели без движения). Read-only."""
    from ...services import missed as _missed
    return _missed.missed()


@router.get("/api/snapshot/month.png", include_in_schema=False)
async def snapshot_month():
    """Экспорт-снимок «как я жил в этом месяце» одной картинкой (открывается в новой вкладке)."""
    from fastapi.responses import FileResponse
    from ...services import cards
    p = await _asyncio.to_thread(cards.month_snapshot_card)
    if not p:
        raise HTTPException(status_code=500, detail="не смог нарисовать снимок месяца")
    return FileResponse(str(p), media_type="image/png")


@router.get("/api/finance/summary")
def fin_summary(days: int = 30):
    return finance.summary(days)


@router.get("/api/finance/daily")
def fin_daily(days: int = 30):
    return finance.daily_series(days)


@router.get("/api/finance/forecast")
def fin_forecast(days: int = 30):
    """График «касса» на сайте и в разделе «финансы»: прошлые дни — по реальным операциям,
    будущие — по регулярным платежам и среднему темпу. Формат (points / kind / min_balance)
    совпадает с тем, что ждёт фронтенд, — иначе график молча показывал бы пустоту."""
    horizon = max(7, min(int(days or 30), 365))
    hist = max(30, min(horizon, 90))
    balance = finance.total_balance()
    today = insights.now_tz().date()          # та же зона, что у insights.cash_series (P2 ревью B)

    # дельта ОБЩЕГО баланса: перевод между своими счетами и «чисто долговые» счета его
    # не трогают — иначе ряд расходится с total_balance() (P1 ревью B, второй случай)
    debt_only = {a.name for a in finance.list_accounts() if a.kind == "debt_only"}
    txs = [t for t in finance.list_transactions(hist + 1, 100_000) if t.date]
    deltas: dict = {}
    spent = income = 0.0
    for t in txs:
        d0 = t.date.date()
        deltas[d0] = deltas.get(d0, 0.0) + insights._tx_balance_delta(t, debt_only)
        if t.kind == "expense":
            spent += float(t.amount)
        elif t.kind == "income":
            income += float(t.amount)

    # баланс на конец дня = текущий баланс − всё, что случилось ПОСЛЕ него. Идём от сегодня
    # вглубь и разворачиваем — ровно как в insights.cash_series: иначе в первую точку попадал
    # баланс на НАЧАЛО дня, «сегодня» отставал от карточек, а завтрашний день зеркалил
    # вчерашний (P1 ревью B, B1 — см. reviews/review_B.md).
    points: list[dict] = []
    after = 0.0
    for i in range(0, hist + 1):
        d = today - timedelta(days=i)
        points.append({"date": d.isoformat(), "balance": round(balance - after), "kind": "past"})
        after += deltas.get(d, 0.0)
    points.reverse()

    fc = insights.cash_forecast(horizon)
    points.extend({"date": p["date"], "balance": p["balance"], "kind": "future", "events": p.get("events") or []}
                  for p in fc["points"][1:])

    fut = [p for p in points if p["kind"] == "future"]
    low = min((p["balance"] for p in fut), default=balance)
    low_date = next((p["date"] for p in fut if p["balance"] == low), today.isoformat())
    runway = next((i + 1 for i, p in enumerate(fut) if p["balance"] <= 0), None)
    return {"points": points, "horizon_days": horizon, "avg_day_spent": round(spent / hist),
            "avg_day_income": round(income / hist), "runway_days": runway, "min_balance": round(low),
            "min_date": low_date, "balance": round(balance),
            # реалистичный/пессимистичный сценарии (ожидаемые оплаты заказов) — только добавление
            "scenarios": fc.get("scenarios")}


@router.get("/api/finance/transactions")
def fin_tx(days: int = 30):
    # Сайт шлёт days=0 для периода «всё» (Finance.jsx, переключатель периода).
    # Раньше 0 означал «отсечка = сейчас» → пустой список; теперь это «без нижней
    # границы», т.е. вся история (P1 ревью D, D1).
    if days <= 0:
        days = 36500
    return finance.list_transactions(days, 1000)


@router.post("/api/finance/transactions")
def fin_add(t: TxIn):
    return finance.add_transaction(t.amount, t.kind, t.category, t.note, t.account, t.to_account, t.date, "web")


@router.put("/api/finance/transactions/{tx_id}")
def fin_tx_update(tx_id: int, p: TxPatch):
    return finance.update_transaction(tx_id, **p.model_dump(exclude_unset=True))


@router.delete("/api/finance/transactions/{tx_id}")
def fin_del(tx_id: int):
    if not finance.delete_transaction(tx_id):
        raise HTTPException(404)
    return {"ok": True}


@router.post("/api/finance/categories")
def fin_cat_add(c: CategoryIn):
    return finance.add_category(c.name, c.kind, c.icon, c.keywords, c.budget, c.bucket)


@router.put("/api/finance/categories/{cid}")
def fin_cat_update(cid: int, p: CategoryPatch):
    return finance.update_category(cid, **p.model_dump(exclude_none=True))


@router.delete("/api/finance/categories/{cid}")
def fin_cat_del(cid: int):
    if not finance.delete_category(cid):
        raise HTTPException(404)
    return {"ok": True}


@router.get("/api/finance/budgets")
def fin_budgets():
    return {"budgets": finance.budgets(), "safe": finance.safe_to_spend()}


@router.get("/api/finance/categories")
def fin_cats():
    return finance.list_categories()


@router.get("/api/finance/accounts")
def fin_accounts():
    return finance.list_accounts()


@router.post("/api/finance/accounts/balance")
def fin_balance(b: BalanceIn):
    return finance.set_balance(b.name, b.balance)


@router.post("/api/finance/accounts")
def fin_account_add(a: AccountIn):
    return finance.add_account(a.name, a.kind, a.balance)


@router.put("/api/finance/accounts/{aid}")
def fin_account_update(aid: int, p: AccountPatch):
    return finance.update_account(aid, **p.model_dump(exclude_unset=True))


@router.delete("/api/finance/accounts/{aid}")
def fin_account_del(aid: int):
    if not finance.delete_account(aid):
        raise HTTPException(404)
    return {"ok": True}


@router.get("/api/finance/debts")
def fin_debts():
    return [{**d.model_dump(), **finance.debt_forecast(d)} for d in finance.list_debts(include_closed=True)]


@router.post("/api/finance/debts")
def fin_debt_add(d: DebtIn):
    x = finance.add_debt(d.title, d.total, d.payment, d.rate, d.pay_day, d.creditor, d.remaining)
    return {**x.model_dump(), **finance.debt_forecast(x)}


@router.post("/api/finance/debts/{debt_id}/pay")
def fin_debt_pay(debt_id: int, p: PayIn):
    d = finance.pay_debt(debt_id, p.amount, account=p.account, source="web", date=p.date)
    if not d:
        raise HTTPException(404)
    return {**d.model_dump(), **finance.debt_forecast(d)}


@router.get("/api/finance/debts/{debt_id}/payments")
def fin_debt_payments(debt_id: int):
    # Несуществующий долг → 404, а не пустой список с 200: иначе опечатка в ID выглядит
    # как «платежей нет» (P2 ревью A; DELETE /api/finance/debts/{id} уже отдаёт 404).
    if not any(d.id == debt_id for d in finance.list_debts(include_closed=True)):
        raise HTTPException(404)
    return finance.debt_payments(debt_id)


@router.put("/api/finance/debts/{debt_id}")
def fin_debt_update(debt_id: int, p: DebtPatch):
    d = finance.update_debt(debt_id, **p.model_dump(exclude_unset=True))
    return {**d.model_dump(), **finance.debt_forecast(d)}


@router.delete("/api/finance/debts/{debt_id}")
def fin_debt_del(debt_id: int):
    if not finance.delete_debt(debt_id):
        raise HTTPException(404)
    return {"ok": True}


@router.get("/api/finance/recurring")
def fin_recurring(all: bool = False):
    # по умолчанию — как раньше (только активные); ?all=true отдаёт и паузы,
    # чтобы UI мог показать «выключенные» регулярные и вернуть их в расчёт
    return finance.list_recurring(active_only=not all)


@router.post("/api/finance/recurring")
def fin_recurring_add(r: RecurringIn):
    return finance.add_recurring(r.title, r.amount, r.day, r.kind, r.category, r.period)


@router.put("/api/finance/recurring/{rid}")
def fin_recurring_update(rid: int, p: RecurringPatch):
    return finance.update_recurring(rid, **p.model_dump(exclude_unset=True))


@router.delete("/api/finance/recurring/{rid}")
def fin_recurring_del(rid: int):
    with session() as s:
        r = s.get(Recurring, rid)
        if not r:
            raise HTTPException(404)
        r.active = False
        s.add(r); s.commit()
    return {"ok": True}


# ---------------- цели / конверты / техники ----------------
@router.get("/api/finance/goals")
def goals_list(all: bool = False):
    return goals.list_goals(include_closed=all)


@router.post("/api/finance/goals")
def goals_add(g: GoalIn):
    try:
        r = goals.add_goal(g.title, g.target, g.due, g.saved, g.icon, source="web")
    except finance.FinanceError as e:
        raise HTTPException(400, str(e))
    return goals.goal_view(r)


@router.put("/api/finance/goals/{gid}")
def goals_update(gid: int, p: GoalPatch):
    r = goals.update_goal(gid, **p.model_dump(exclude_unset=True))
    if not r:
        raise HTTPException(404)
    return goals.goal_view(r)


@router.delete("/api/finance/goals/{gid}")
def goals_del(gid: int):
    if not goals.delete_goal(gid):
        raise HTTPException(404)
    return {"ok": True}


@router.post("/api/finance/goals/{gid}/put")
def goals_put(gid: int, p: GoalPut):
    try:
        r = goals.put_to_goal(gid, p.amount, p.account, source="web", record_tx=p.record_tx)
    except finance.FinanceError as e:
        raise HTTPException(400, str(e))
    broadcast("chat", {"channel": "web", "actions": ["save_to_goal"]})
    return r


@router.get("/api/finance/techniques")
def finance_techniques():
    """Все «умные» финансы одним запросом: 50/30/20, месяц к месяцу, годовой резерв, хватит ли на платежи, подушка."""
    return {"buckets": goals.buckets_report(), "compare": goals.month_compare(), "annual": goals.annual_reserve(),
            "payments": goals.payment_check(7), "runway": goals.runway()}


@router.get("/api/export/{what}.{fmt}")
def export(what: str, fmt: str):
    """Экспорт данных: /api/export/transactions.csv, /api/export/all.json …"""
    import csv
    import io
    from fastapi.responses import Response
    from sqlmodel import select
    from ...db import Account, Client, Goal, Order, WorkSession
    # «operations» — читаемый алиас для операций (то же, что transactions); заказы добавлены отдельно
    tables = {"transactions": Transaction, "orders": Order, "clients": Client, "goals": Goal,
              "accounts": Account, "work_sessions": WorkSession,
              "events": Event, "tasks": Task, "notes": Note, "links": Link, "debts": Debt, "recurring": Recurring}
    if what == "operations":
        what = "transactions"
    if what != "all" and what not in tables:
        raise HTTPException(404)
    with session() as s:
        def _row(r):
            d = r.model_dump()
            first = [k for k in ("id", "date", "start", "created_at", "title", "amount", "kind", "category") if k in d]
            return {k: d[k] for k in first} | {k: v for k, v in d.items() if k not in first}
        data = {name: [_row(r) for r in s.exec(select(model)).all()] for name, model in tables.items() if what in ("all", name)}
    stamp = datetime.now().strftime("%Y%m%d")
    if fmt == "json":
        body = _json.dumps(data if what == "all" else data[what], ensure_ascii=False, default=str, indent=1)
        return Response(body, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="jarvis-{what}-{stamp}.json"'})
    if fmt == "csv":
        buf = io.StringIO()
        buf.write("\ufeff")  # BOM — чтобы Excel открыл кириллицу
        for name, rows in data.items():
            if what == "all":
                buf.write(f"# {name}\n")
            if rows:
                w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), delimiter=";")
                w.writeheader()
                for r in rows:
                    w.writerow({k: (str(v).replace("T", " ")[:19] if isinstance(v, datetime) else v) for k, v in r.items()})
            buf.write("\n")
        return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="jarvis-{what}-{stamp}.csv"'})
    raise HTTPException(400, "fmt: csv или json")
