"""HTTP-роутер CRM (фаза 4). Подключается в `core/api/app.py` одной строкой.

Все пути — только новые (`/api/crm/...`), существующие эндпоинты не трогаются.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..services import orders
from ..services.orders import OrderError
from . import service, stages

router = APIRouter(prefix="/api/crm", tags=["crm"])


def _bump(kind: str, payload: dict | None = None) -> None:
    """Сообщить сайту об изменениях (ленивый импорт — чтобы не было цикла с app.py)."""
    try:
        from ..api.app import broadcast
        broadcast(kind, payload)
    except Exception:  # pragma: no cover
        pass


class StageIn(BaseModel):
    stage: str
    lost_reason: Optional[str] = None


class CrmPaymentIn(BaseModel):
    amount: float
    note: Optional[str] = None
    account: Optional[str] = None
    date: Optional[datetime] = None
    idem_key: Optional[str] = Field(default=None, max_length=120)


class CommentIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)
    client_id: Optional[int] = None
    author: str = "вы"


class CheckIn(BaseModel):
    title: str = Field(..., min_length=1, max_length=300)


class CheckPatch(BaseModel):
    done: Optional[bool] = None


class ClientPatch(BaseModel):
    source: Optional[str] = None
    next_step: Optional[str] = None
    next_step_at: Optional[datetime] = None
    last_contact_at: Optional[datetime] = None


class FollowupIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    order_id: Optional[int] = None
    client_id: Optional[int] = None
    kind: str = "manual"
    due_at: Optional[datetime] = None


@router.get("/stages")
def crm_stages():
    return {"stages": [{"stage": k, "label": stages.label(k), "status": stages.status_for(k)}
                       for k in stages.STAGE_ORDER],
            "order": list(stages.STAGE_ORDER)}


def _stage_of_view(v: dict) -> str:
    st = v.get("stage") or ""
    return st if st in stages.STAGE_ORDER else stages.STATUS_TO_STAGE.get(v.get("status", ""), "lead")


@router.get("/board")
def crm_board(all: bool = False):
    """Канбан: заказы, сгруппированные по стадиям воронки."""
    rows = orders.list_orders(include_closed=all)
    cols: dict[str, list[dict]] = {k: [] for k in stages.STAGE_ORDER}
    for v in rows:
        cols.setdefault(_stage_of_view(v), []).append(v)
    return {"columns": [{"stage": k, "label": stages.label(k), "orders": cols.get(k, [])} for k in stages.STAGE_ORDER],
            "orders": rows}


@router.get("/orders/{oid}/card")
def crm_order_card(oid: int):
    card = service.order_card(oid)
    if not card:
        raise HTTPException(404, "Заказ не найден")
    return card


@router.put("/orders/{oid}/stage")
def crm_set_stage(oid: int, p: StageIn):
    try:
        v = service.set_stage(oid, p.stage, p.lost_reason)
    except OrderError as e:
        raise HTTPException(400, str(e))
    _bump("order", {"id": oid, "action": "stage"})
    return v


@router.post("/orders/{oid}/payments")
def crm_pay(oid: int, p: CrmPaymentIn):
    try:
        r = service.payment(oid, p.amount, p.note, p.account, p.date, p.idem_key)
    except ValueError as e:   # OrderError и finance.FinanceError — оба ValueError
        raise HTTPException(400, str(e))
    _bump("order", {"id": oid, "action": "pay"})
    return r


@router.get("/orders/{oid}/activity")
def crm_order_activity(oid: int):
    if not orders.get_order(oid):
        raise HTTPException(404, "Заказ не найден")
    return service.feed(order_id=oid)


@router.get("/orders/{oid}/comments")
def crm_comments(oid: int):
    if not orders.get_order(oid):
        raise HTTPException(404, "Заказ не найден")
    return service.comments(oid)


@router.post("/orders/{oid}/comments")
def crm_add_comment(oid: int, p: CommentIn):
    try:
        r = service.add_comment(oid, p.text, p.client_id, p.author)
    except OrderError as e:
        raise HTTPException(400, str(e))
    return r


@router.get("/orders/{oid}/checklist")
def crm_checklist(oid: int):
    if not orders.get_order(oid):
        raise HTTPException(404, "Заказ не найден")
    return service.checklist(oid)


@router.post("/orders/{oid}/checklist")
def crm_add_check(oid: int, p: CheckIn):
    try:
        r = service.add_check(oid, p.title)
    except OrderError as e:
        raise HTTPException(400, str(e))
    return r


@router.patch("/checklist/{cid}")
def crm_toggle_check(cid: int, p: CheckPatch):
    try:
        return service.toggle_check(cid, p.done)
    except OrderError as e:
        raise HTTPException(404, str(e))


@router.delete("/checklist/{cid}")
def crm_delete_check(cid: int):
    if not service.delete_check(cid):
        raise HTTPException(404)
    return {"ok": True}


@router.get("/clients/{cid}/card")
def crm_client_card(cid: int):
    card = service.customer_card(cid)
    if not card:
        raise HTTPException(404, "Клиент не найден")
    return card


@router.put("/clients/{cid}")
def crm_update_client(cid: int, p: ClientPatch):
    r = service.update_client_fields(cid, **p.model_dump(exclude_unset=True))
    if not r:
        raise HTTPException(404, "Клиент не найден")
    return r


@router.get("/followups")
def crm_followups(all: bool = False):
    return service.followups(only_open=not all)


@router.post("/followups")
def crm_add_followup(p: FollowupIn):
    try:
        return service.create_followup(p.text, p.order_id, p.client_id, p.kind, p.due_at)
    except OrderError as e:
        raise HTTPException(400, str(e))


@router.post("/followups/{fid}/done")
def crm_done_followup(fid: int, done: bool = True):
    try:
        created = service.complete_followup(fid, done)
    except OrderError as e:
        raise HTTPException(404, str(e))
    return created


@router.post("/followups/scan")
def crm_scan_followups():
    """Пересчитать напоминания по данным (создаёт недостающие, без отправки)."""
    return {"created": service.scan()}


@router.get("/templates")
def crm_templates(order_id: Optional[int] = None):
    return service.templates(order_id)


@router.get("/analytics")
def crm_analytics(months: int = 6):
    return service.analytics(months)
