"""«Что я упускаю» — один экран упущений: просроченные оплаты клиентов, долги к оплате,
дела без срока и цели без движения. Только чтение: ничего не меняет, никуда не пишет.

Собирается из уже готовых сервисов (orders / finance / tasks / goals), поэтому не расходится с ними в цифрах.
"""
from __future__ import annotations

import logging
from datetime import datetime

from . import finance, goals, orders, tasks

log = logging.getLogger("jarvis.missed")


def _dt(v):
    if isinstance(v, datetime):
        return v
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v)
        except Exception:
            return None
    return None


def missed(limit: int = 5) -> dict:
    """Упущения по четырём категориям. Пустые списки — это хорошо, а не поломка."""
    now = datetime.now()
    out: dict = {"unpaid": [], "overdue_debts": [], "tasks_no_due": [], "goals_stale": []}

    # 1. Оплаты по заказам: срок прошёл, а деньги не пришли
    try:
        for o in orders.list_orders(include_closed=False):
            if (o.get("left") or 0) <= 0:
                continue
            dl = _dt(o.get("deadline"))
            if o.get("overdue") or o.get("past_due") or (dl and dl < now):
                out["unpaid"].append({"id": o.get("id"), "title": o.get("title"), "client": o.get("client"),
                                      "left": round(o.get("left") or 0), "deadline": dl.isoformat() if dl else None})
    except Exception as e:  # pragma: no cover
        log.warning("missed orders: %s", e)

    # 2. Платежи по долгам: день списания в этом месяце уже прошёл
    try:
        for d in finance.list_debts():
            if getattr(d, "closed", False) or (getattr(d, "remaining", 0) or 0) <= 0:
                continue
            pay_day = getattr(d, "pay_day", 1) or 1
            if now.day > pay_day and (getattr(d, "payment", 0) or 0) > 0:
                out["overdue_debts"].append({"title": d.title, "payment": round(d.payment), "pay_day": pay_day})
    except Exception as e:  # pragma: no cover
        log.warning("missed debts: %s", e)

    # 3. Дела без срока — самые старые первыми (их обычно и забывают)
    try:
        ts = [t for t in tasks.list_tasks() if not getattr(t, "due", None) and not getattr(t, "done", False)]
        ts.sort(key=lambda t: getattr(t, "created_at", now) or now)
        for t in ts[:limit]:
            c = getattr(t, "created_at", None)
            out["tasks_no_due"].append({"id": t.id, "title": t.title, "since": c.isoformat() if c else None})
    except Exception as e:  # pragma: no cover
        log.warning("missed tasks: %s", e)

    # 4. Цели без движения: срок прошёл или копилка стоит на нуле давно
    try:
        for g in goals.list_goals():
            if g.get("closed"):
                continue
            created = _dt(g.get("created_at"))
            stale = False
            if g.get("days_left") is not None and g["days_left"] < 0:
                stale = True
            elif (g.get("saved") or 0) <= 0 and created and (now - created).days >= 7:
                stale = True
            if stale:
                out["goals_stale"].append({"id": g.get("id"), "title": g.get("title"),
                                           "pct": round((g.get("pct") or 0) * 100),
                                           "left": round(g.get("left") or 0), "days_left": g.get("days_left")})
    except Exception as e:  # pragma: no cover
        log.warning("missed goals: %s", e)

    out["count"] = sum(len(out[k]) for k in ("unpaid", "overdue_debts", "tasks_no_due", "goals_stale"))
    return out


def missed_text() -> str:
    """Короткая сводка для Telegram/чата."""
    m = missed()
    if not m["count"]:
        return "Ничего не упускаете, сэр. Редкое и подозрительное состояние."
    lines = ["**Что вы упускаете:**"]
    if m["unpaid"]:
        lines.append(f"💰 **Ждут оплаты ({len(m['unpaid'])})** — срок прошёл, денег нет:")
        lines += [f"— {o['title']}" + (f" · {o['client']}" if o.get("client") else "") +
                  f" — **{finance.money(o['left'])}**" for o in m["unpaid"][:4]]
    if m["overdue_debts"]:
        lines.append(f"💳 **Платежи по долгам ({len(m['overdue_debts'])})** — день списания прошёл:")
        lines += [f"— {d['title']} — **{finance.money(d['payment'])}** (обычно {d['pay_day']}-го)" for d in m["overdue_debts"][:4]]
    if m["tasks_no_due"]:
        lines.append(f"📋 **Дела без срока ({len(m['tasks_no_due'])})** — висят и не горят, а стоило бы:")
        lines += [f"— {t['title']}" for t in m["tasks_no_due"][:4]]
    if m["goals_stale"]:
        lines.append(f"🎯 **Цели без движения ({len(m['goals_stale'])})**:")
        lines += [f"— {g['title']} — {g['pct']}%" + (f", осталось {finance.money(g['left'])}" if g.get("left") else "") for g in m["goals_stale"][:4]]
    lines.append("Разобрать? Скажите «покажи упущения» или закройте по одному.")
    return "\n".join(lines)
