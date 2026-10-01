"""Заказы, фриланс, таймер, помодоро, клиенты заказов (ФАЗА 7, шаг 7.2).

Роуты перенесены из `core/api/app.py` МЕХАНИЧЕСКИ: пути, методы, тела функций,
порядок ответов и логика не менялись. Декораторы сохраняют полный путь
(`/api/...`), поэтому `router` создаётся БЕЗ prefix — пути совпадают 1:1.

Инвариант регистрации (см. `core/api/routers/__init__.py`): `register(app)`
вызывается из `app.py` ПОСЛЕ `include_router(_crm_router)` и ДО статики и
catch-all SPA. Порядок роутов внутри модуля = порядок в `app.py` на шаге 7.0.

CRM-роутер (`core/crm/router.py`, prefix `/api/crm`) обслуживает заказы отдельно
(`/api/crm/orders/{oid}/...`) — он НЕ трогается и не дублируется: перенесены
ровно те `/api/orders*`-роуты, что жили в `app.py`.

Локальные импорты внутри тел роутов сохранены как есть (в проекте это осознанный
приём: быстрый старт, обход циклов) — у них ровно на одну точку больше,
т.к. модуль лежит на уровне `core/api/routers/`.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from ...services import finance, orders, pulse
from .._shared import broadcast
from ..schemas import (ClientIn, FreelanceIn, ManualTimeIn, OrderIn, OrderPatch, PaymentIn, PomoSettingsIn,
                       ScreenImportIn, TimerIn)

router = APIRouter()


def register(app) -> None:
    app.include_router(router)


@router.get("/api/orders/suggest")
def orders_suggest(title: str = "", client_id: Optional[int] = None):
    """Подсказка цены/часов для нового заказа по похожим прошлым (read-only)."""
    return orders.suggestion(title, client_id)


# ---------------- заказы / фриланс ----------------
def _order_or_404(oid: int):
    o = orders.get_order(oid)
    if not o:
        raise HTTPException(404, "Заказ не найден")
    return o


@router.get("/api/orders/clients")
def clients_list():
    return [c.model_dump() for c in orders.list_clients()]


@router.post("/api/orders/clients")
def clients_add(c: ClientIn):
    r = orders.get_or_create_client(c.name)
    if not r:
        raise HTTPException(400, "Нужно имя клиента")
    if c.contact or c.notes:
        r = orders.update_client(r.id, contact=c.contact, notes=c.notes)
    return r.model_dump()


@router.put("/api/orders/clients/{cid}")
def clients_update(cid: int, c: ClientIn):
    r = orders.update_client(cid, name=c.name, contact=c.contact, notes=c.notes)
    if not r:
        raise HTTPException(404)
    return r.model_dump()


@router.delete("/api/orders/clients/{cid}")
def clients_del(cid: int):
    if not orders.delete_client(cid):
        raise HTTPException(404)
    return {"ok": True}


@router.get("/api/orders")
def orders_list(status: Optional[str] = None, all: bool = False):
    return orders.list_orders(status, include_closed=all)


@router.get("/api/orders/stats")
def orders_stats(months: int = 6):
    return orders.stats(months)


@router.get("/api/orders/timer")
def orders_timer():
    return orders.timer_state()


@router.get("/api/orders/pomodoro")
def pomo_get():
    return orders.pomo_settings()


@router.get("/api/orders/freelance")
def freelance_get():
    pulse.auto_enable_if_used()
    return pulse.freelance_settings()


@router.put("/api/orders/freelance")
def freelance_put(p: FreelanceIn):
    r = pulse.save_freelance_settings(p.model_dump(exclude_none=True))
    broadcast("freelance_settings", r)
    return r


@router.get("/api/orders/pulse")
def pulse_get():
    """Пульс: задержки оплат + налог за месяц. Пусто, если режим фрилансера выключен."""
    st = pulse.freelance_settings()
    if not st["enabled"]:
        return {"enabled": False, "late": [], "tax": None}
    return {"enabled": True, "late": pulse.late_payments() if st["late_nudge"] else [], "tax": pulse.tax_month() if st["tax_percent"] else None, "settings": st}


@router.put("/api/orders/pomodoro")
def pomo_put(p: PomoSettingsIn):
    r = orders.save_pomo_settings(p.model_dump(exclude_none=True))
    broadcast("pomo_settings", r)
    return r


@router.post("/api/orders/timer")
def orders_timer_start(t: TimerIn):
    if t.order_id:
        _order_or_404(t.order_id)
    orders.start_session(t.order_id, t.minutes or None, t.kind, source="web")
    broadcast("timer", {"action": "start"})
    return orders.timer_state()


@router.delete("/api/orders/timer")
def orders_timer_stop():
    orders.stop_session()
    broadcast("timer", {"action": "stop"})
    return orders.timer_state()


@router.post("/api/orders")
def orders_add(o: OrderIn):
    try:
        r = orders.add_order(o.title, o.price, o.client, o.deadline, o.notes, o.estimate_h, o.status, source="web")
    except orders.OrderError as e:
        raise HTTPException(400, str(e))
    broadcast("order", {"id": r.id, "action": "add"})
    return orders.order_view(r)


@router.get("/api/orders/{oid}")
def orders_get(oid: int):
    o = _order_or_404(oid)
    return {**orders.order_view(o), "payments": [t.model_dump() for t in orders.payments_for(oid)],
            "sessions": [w.model_dump() for w in orders.sessions_for(oid)]}


@router.post("/api/orders/{oid}/time")
def orders_add_manual_time(oid: int, p: ManualTimeIn):
    _order_or_404(oid)
    try:
        row = orders.add_manual_time(oid, p.minutes, p.started_at, p.note)
    except orders.OrderError as e:
        raise HTTPException(400, str(e))
    return {"session": row.model_dump(), "order": orders.order_view(orders.get_order(oid))}


@router.post("/api/orders/{oid}/time/from-screen")
def orders_add_screen_time(oid: int, p: ScreenImportIn):
    _order_or_404(oid)
    note = f"{p.app} · {p.project}".strip(" ·")
    try:
        row = orders.add_manual_time(oid, p.minutes, note=note, source="screen")
    except orders.OrderError as e:
        raise HTTPException(400, str(e))
    return {"session": row.model_dump(), "order": orders.order_view(orders.get_order(oid))}


@router.put("/api/orders/{oid}")
def orders_update(oid: int, p: OrderPatch):
    _order_or_404(oid)
    try:
        r = orders.update_order(oid, **p.model_dump(exclude_unset=True))
    except orders.OrderError as e:
        raise HTTPException(400, str(e))
    broadcast("order", {"id": oid, "action": "edit"})
    return orders.order_view(r)


@router.delete("/api/orders/{oid}")
def orders_del(oid: int):
    if not orders.delete_order(oid):
        raise HTTPException(404)
    broadcast("order", {"id": oid, "action": "delete"})
    return {"ok": True}


@router.post("/api/orders/{oid}/payments")
def orders_pay(oid: int, p: PaymentIn):
    _order_or_404(oid)
    try:
        t = orders.add_payment(oid, p.amount, p.note, p.account, source="web", date=p.date)
    except (orders.OrderError, finance.FinanceError) as e:
        raise HTTPException(400, str(e))
    broadcast("order", {"id": oid, "action": "pay"})
    return {"tx": t.model_dump(), "order": orders.order_view(orders.get_order(oid))}
