"""CRM-логика фазы 4: воронка, карточки клиента/заказа, платежи, follow-up, аналитика.

Деньги по-прежнему — обычные `Transaction` с `order_id`, поэтому доход и баланс остаются
одной правдой; CRM только добавляет идемпотентность и ленту/карточки поверх.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlmodel import select

from ..db import (
    Client, CrmActivity, CrmChecklist, CrmComment, CrmFollowup, Order, Transaction,
    WorkSession, now, session,
)
from ..services import orders
from ..services.finance import money
from ..services.orders import OrderError
from . import stages

log = logging.getLogger("jarvis.crm")

# через сколько дней «клиент молчит» и «не оплачено» считаем поводом для follow-up
SILENT_DAYS = 7
UNPAID_DAYS = 14

TEMPLATES: dict[str, str] = {
    "payment": "Привет! По заказу «{order}» осталось {left}. Скинуть реквизиты или счёт?",
    "revisions": "Привет! Правки по «{order}» принял в работу, вернусь с новой версией {when}.",
    "silent": "Привет! Как дела с «{order}»? Нужно что-то с моей стороны — скажите.",
    "thanks": "Спасибо за заказ «{order}»! Если всё ок — буду рад отзыву.",
}


# ---------------------------------------------------------------- активность
def _log(s, *, order_id=None, client_id=None, kind="note", text="", author="вы", channel="web") -> None:
    s.add(CrmActivity(order_id=order_id, client_id=client_id, kind=kind, text=text, author=author, channel=channel))


def log_event(order_id=None, client_id=None, kind="note", text="", author="вы", channel="web") -> None:
    with session() as s:
        _log(s, order_id=order_id, client_id=client_id, kind=kind, text=text, author=author, channel=channel)
        s.commit()


def feed(order_id: int | None = None, client_id: int | None = None, limit: int = 100) -> list[dict]:
    with session() as s:
        q = select(CrmActivity)
        if order_id is not None:
            q = q.where(CrmActivity.order_id == order_id)
        if client_id is not None:
            q = q.where(CrmActivity.client_id == client_id)
        rows = list(s.exec(q.order_by(CrmActivity.created_at.desc(), CrmActivity.id.desc()).limit(limit)))
    return [r.model_dump() for r in rows]


# ---------------------------------------------------------------- стадии
def set_stage(oid: int, stage: str, lost_reason: str | None = None, channel: str = "web") -> dict:
    if not stages.is_stage(stage):
        raise OrderError(f"Стадия: {', '.join(stages.STAGE_ORDER)}")
    order = orders.get_order(oid)
    if not order:
        raise OrderError("Заказ не найден")
    before = stages.stage_of(order)
    fields: dict = {"stage": stage, "lost_reason": (lost_reason if stage == "lost" else None)}
    if stage == "revisions" and before != "revisions":       # новый круг правок — счётчик +1
        fields["revisions"] = (order.revisions or 0) + 1
    orders.update_order(oid, **fields)
    log_event(order_id=oid, client_id=order.client_id, kind="stage",
              text=f"{stages.label(before)} → {stages.label(stage)}" + (f" · {lost_reason}" if lost_reason else ""),
              channel=channel)
    return orders.order_view(orders.get_order(oid))


# ---------------------------------------------------------------- платежи
def payment(oid: int, amount: float, note: str | None = None, account: str | None = None,
            date: datetime | None = None, idem_key: str | None = None, channel: str = "web") -> dict:
    """Оплата заказа. `idem_key` делает операцию идемпотентной: повтор не создаёт второй доход."""
    order = orders.get_order(oid)
    if not order:
        raise OrderError("Заказ не найден")
    duplicate = False
    if idem_key:
        with session() as s:
            duplicate = s.exec(select(Transaction).where(Transaction.idem_key == idem_key)).first() is not None
    try:
        tx = orders.add_payment(oid, amount, note, account, source=channel, date=date, idem_key=idem_key)
    except orders.OrderError:
        raise
    if not duplicate:
        log_event(order_id=oid, client_id=order.client_id, kind="payment",
                  text=f"Оплата {money(float(amount))}" + (f" · {note}" if note else ""), channel=channel)
    if order.client_id:
        # авто-стадия клиента: оплата заказа — сигнал «клиент/постоянный». Ручную стадию не трогает.
        try:
            from . import client_stages
            client_stages.recalc(order.client_id, channel=channel)
        except Exception:  # pragma: no cover — стадия клиента не должна ломать оплату
            log.warning("стадия клиента: не пересчитать для %s", order.client_id, exc_info=True)
    return {"tx": tx.model_dump(), "order": orders.order_view(orders.get_order(oid)), "duplicate": duplicate}


def payments(oid: int) -> list[dict]:
    return [t.model_dump() for t in orders.payments_for(oid)]


# ---------------------------------------------------------------- комментарии
def add_comment(oid: int | None, text: str, client_id: int | None = None, author: str = "вы") -> dict:
    text = (text or "").strip()
    if not text:
        raise OrderError("Пустой комментарий")
    if oid and not orders.get_order(oid):
        raise OrderError("Заказ не найден")
    with session() as s:
        row = CrmComment(order_id=oid, client_id=client_id, text=text[:4000], author=author)
        s.add(row); s.commit(); s.refresh(row)
        _log(s, order_id=oid, client_id=client_id, kind="comment", text=text[:200], author=author)
        s.commit()
        return row.model_dump()


def comments(oid: int) -> list[dict]:
    with session() as s:
        rows = list(s.exec(select(CrmComment).where(CrmComment.order_id == oid).order_by(CrmComment.created_at.desc())))
    return [r.model_dump() for r in rows]


# ---------------------------------------------------------------- чек-лист этапов
def checklist(oid: int) -> list[dict]:
    with session() as s:
        rows = list(s.exec(select(CrmChecklist).where(CrmChecklist.order_id == oid)
                           .order_by(CrmChecklist.position, CrmChecklist.id)))
    return [r.model_dump() for r in rows]


def add_check(oid: int, title: str) -> dict:
    title = (title or "").strip()
    if not title:
        raise OrderError("Нужен текст пункта")
    if not orders.get_order(oid):
        raise OrderError("Заказ не найден")
    with session() as s:
        pos = len(s.exec(select(CrmChecklist).where(CrmChecklist.order_id == oid)).all())
        row = CrmChecklist(order_id=oid, title=title[:300], position=pos)
        s.add(row); s.commit(); s.refresh(row)
        return row.model_dump()


def toggle_check(cid: int, done: bool | None = None) -> dict:
    with session() as s:
        row = s.get(CrmChecklist, cid)
        if not row:
            raise OrderError("Пункт не найден")
        row.done = (not row.done) if done is None else bool(done)
        s.add(row); s.commit(); s.refresh(row)
        _log(s, order_id=row.order_id, kind="checklist", text=("✓ " if row.done else "✗ ") + row.title)
        s.commit()
        return row.model_dump()


def delete_check(cid: int) -> bool:
    with session() as s:
        row = s.get(CrmChecklist, cid)
        if not row:
            return False
        s.delete(row); s.commit()
        return True


# ---------------------------------------------------------------- follow-up
def followups(only_open: bool = True, limit: int = 200) -> list[dict]:
    with session() as s:
        q = select(CrmFollowup)
        if only_open:
            q = q.where(CrmFollowup.done == False)  # noqa: E712
        rows = list(s.exec(q.order_by(CrmFollowup.done, CrmFollowup.due_at, CrmFollowup.id.desc()).limit(limit)))
    return [r.model_dump() for r in rows]


def create_followup(text: str, order_id: int | None = None, client_id: int | None = None,
                    kind: str = "manual", due_at: datetime | None = None) -> dict:
    text = (text or "").strip()
    if not text:
        raise OrderError("Нужен текст напоминания")
    with session() as s:
        row = CrmFollowup(text=text[:500], order_id=order_id, client_id=client_id, kind=kind, due_at=due_at)
        s.add(row); s.commit(); s.refresh(row)
        return row.model_dump()


def complete_followup(fid: int, done: bool = True) -> dict:
    with session() as s:
        row = s.get(CrmFollowup, fid)
        if not row:
            raise OrderError("Напоминание не найдено")
        row.done = bool(done)
        row.done_at = now() if done else None
        s.add(row); s.commit(); s.refresh(row)
        return row.model_dump()


def _has_open(s, kind: str, order_id: int) -> bool:
    return bool(s.exec(select(CrmFollowup).where(
        CrmFollowup.kind == kind, CrmFollowup.order_id == order_id, CrmFollowup.done == False)).first())  # noqa: E712


def scan() -> list[dict]:
    """Создать недостающие follow-up по данным (без спама: один повод на заказ). Ничего не отправляет."""
    created: list[dict] = []
    nowd = datetime.now()
    for v in orders.list_orders():
        oid = v["id"]
        stage = v.get("stage") or stages.STATUS_TO_STAGE.get(v.get("status", ""), "lead")
        reasons: list[tuple[str, str, datetime | None]] = []
        if stage in stages.OPEN_STAGES and v["overdue"]:
            reasons.append(("overdue", f"Просрочен дедлайн по «{v['title']}»", v["deadline"]))
        last = v.get("last_contact_at") or v.get("created_at")
        if stage in stages.OPEN_STAGES and last and (nowd - last).days >= SILENT_DAYS:
            reasons.append(("silent", f"Клиент молчит {(nowd - last).days} дн. по «{v['title']}»", None))
        if stage in ("delivered", "awaiting_payment") and not v.get("paid_at"):
            done_at = orders.get_order(oid).done_at if orders.get_order(oid) else None
            if done_at and (nowd - done_at).days >= UNPAID_DAYS:
                reasons.append(("unpaid", f"Нет оплаты {(nowd - done_at).days} дн. по «{v['title']}»", None))
        if not reasons:
            continue
        with session() as s:
            for kind, text, due in reasons:
                if _has_open(s, kind, oid):
                    continue
                row = CrmFollowup(kind=kind, text=text[:500], order_id=oid, client_id=v.get("client_id"), due_at=due)
                s.add(row); s.commit(); s.refresh(row)
                created.append(row.model_dump())
    return created


def templates(order_id: int | None = None) -> dict:
    """Шаблоны сообщений с подстановкой заказа (если указан)."""
    ctx = {"order": "…", "left": "…", "when": "…"}
    if order_id:
        v = orders.order_view(orders.get_order(order_id)) if orders.get_order(order_id) else None
        if v:
            ctx = {"order": v["title"], "left": money(v["left"]) if v["left"] else "оплачено", "when": "завтра"}
    return {k: tpl.format(**ctx) for k, tpl in TEMPLATES.items()}


# ---------------------------------------------------------------- карточки
def _client_stage(cid: int, client_dump: dict) -> dict:
    """Стадия клиента для карточки (read-only). Ошибки не ломают карточку."""
    try:
        from . import client_stages
        from ..db import Client, session as _s
        with _s() as s:
            c = s.get(Client, cid)
            if c is None:
                return {}
            return client_stages.view(c)
    except Exception:  # pragma: no cover — на старой БД без новых колонок карточка должна работать
        log.warning("стадия клиента: не прочитать для %s", cid, exc_info=True)
        return {"client_id": cid, "stage": client_dump.get("stage") or "", "manual": False}


def customer_card(cid: int) -> dict | None:
    with session() as s:
        c = s.get(Client, cid)
        if not c:
            return None
        client = c.model_dump()
        rows = list(s.exec(select(Order).where(Order.client_id == cid).order_by(Order.created_at.desc())))
        activities = list(s.exec(select(CrmActivity).where(CrmActivity.client_id == cid).order_by(CrmActivity.created_at.desc()).limit(40)))
        follow = list(s.exec(select(CrmFollowup).where(CrmFollowup.client_id == cid, CrmFollowup.done == False).order_by(CrmFollowup.due_at)))  # noqa: E712
    views = [orders.order_view(o) for o in rows]
    ltv = round(sum(v["paid"] for v in views))
    closed = [v for v in views if v.get("status") in ("done", "paid") or v["paid"]]
    avg_check = round(sum(v["price"] for v in closed) / len(closed)) if closed else None
    debt = round(sum(v["left"] for v in views if v.get("status") in ("work", "review", "done")))
    last_contact = client.get("last_contact_at")
    for v in views:
        lc = v.get("last_contact_at") or v.get("created_at")
        if lc and (last_contact is None or lc > last_contact):
            last_contact = lc
    source = client.get("source") or next((v.get("source") for v in views if v.get("source")), "")
    return {
        "client": client,
        # стадия клиента (отдельная сущность, миграция v3) — только чтение, ничего не перетирает
        "stage": _client_stage(cid, client),
        "orders": views,
        "orders_count": len(views),
        "ltv": ltv,
        "avg_check": avg_check,
        "debt": debt,
        "open": [v for v in views if v.get("status") in ("new", "work", "review")],
        "source": source,
        "tags": [t.strip() for t in (client.get("tags") or "").split(",") if t.strip()],
        "last_contact_at": last_contact,
        "next_step": client.get("next_step") or "",
        "next_step_at": client.get("next_step_at"),
        "activity": [a.model_dump() for a in activities],
        "followups": [f.model_dump() for f in follow],
    }


def order_card(oid: int) -> dict | None:
    o = orders.get_order(oid)
    if not o:
        return None
    v = orders.order_view(o)
    pays = orders.payments_for(oid)
    prepaid = min(pays, key=lambda t: t.date).amount if pays else 0.0
    timer = orders.timer_state()
    return {
        **v,
        "prepaid": round(prepaid),
        "remaining": round(v["left"]),
        "revisions": v["revisions"],
        "payments": [t.model_dump() for t in pays],
        "sessions": [w.model_dump() for w in orders.sessions_for(oid)],
        "checklist": checklist(oid),
        "comments": comments(oid),
        "activity": feed(order_id=oid, limit=60),
        "board_id": v.get("board_id"),
        "timer_active": bool(timer.get("active") and timer.get("order_id") == oid),
    }


def update_client_fields(cid: int, **fields) -> dict | None:
    with session() as s:
        c = s.get(Client, cid)
        if not c:
            return None
        for k in ("source", "next_step"):
            if k in fields and fields[k] is not None:
                setattr(c, k, str(fields[k]).strip())
        if "next_step_at" in fields:
            c.next_step_at = fields["next_step_at"]
        if "last_contact_at" in fields:
            c.last_contact_at = fields["last_contact_at"]
        s.add(c); s.commit(); s.refresh(c)
        return c.model_dump()


# ---------------------------------------------------------------- аналитика
def analytics(months: int = 6) -> dict:
    """Read-only: конверсия воронки, доход по клиентам, топ клиентов, средний чек."""
    since = (datetime.now().replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with session() as s:
        orders_rows = list(s.exec(select(Order)))
        txs = s.exec(select(Transaction).where(Transaction.order_id != None, Transaction.kind == "income", Transaction.date >= since)).all()  # noqa: E711
        clients = {c.id: c for c in s.exec(select(Client))}
    counts: dict[str, int] = {k: 0 for k in stages.STAGE_ORDER}
    for o in orders_rows:
        counts[stages.stage_of(o)] = counts.get(stages.stage_of(o), 0) + 1
    reached = len([o for o in orders_rows if stages.stage_of(o) not in ("lead", "lost")])
    total = len(orders_rows)
    won = counts.get("paid", 0)
    lost = counts.get("lost", 0)
    revenue_month = round(sum(t.amount for t in txs))
    by_client: dict[int | None, dict] = {}
    for o in orders_rows:
        c = clients.get(o.client_id)
        b = by_client.setdefault(o.client_id, {
            "client_id": o.client_id, "client": c.name if c else "без клиента",
            "orders": 0, "revenue": 0.0, "hours": 0.0,
        })
        b["orders"] += 1
        b["revenue"] += sum(t.amount for t in txs if t.order_id == o.id)
    with session() as s:
        sess = s.exec(select(WorkSession).where(WorkSession.kind == "focus", WorkSession.started_at >= since)).all()
    for o in orders_rows:
        b = by_client.get(o.client_id)
        if b:
            b["hours"] += sum(orders._session_min(w) for w in sess if w.order_id == o.id) / 60
    top = sorted(by_client.values(), key=lambda b: -b["revenue"])
    for b in top:
        b["revenue"] = round(b["revenue"])
        b["hours"] = round(b["hours"], 1)
        b["rate"] = round(b["revenue"] / b["hours"]) if b["hours"] >= 1 else None
    done = [o for o in orders_rows if stages.stage_of(o) in ("delivered", "awaiting_payment", "paid")]
    avg_check = round(sum(o.price for o in done) / len(done)) if done else None
    return {
        "funnel": [{"stage": k, "label": stages.label(k), "count": counts.get(k, 0)} for k in stages.STAGE_ORDER],
        "counts": counts,
        "total": total,
        "reached": reached,
        "won": won,
        "lost": lost,
        "conversion": round(won / total * 100, 1) if total else 0.0,
        "win_rate": round(won / (won + lost) * 100, 1) if (won + lost) else 0.0,
        "revenue_month": revenue_month,
        "avg_check": avg_check,
        "clients": top[:12],
        "top": top[:5],
    }
