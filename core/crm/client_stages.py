"""Стадии КЛИЕНТА (CRM) — вторая, независимая сущность.

Воронка заказов (`core/crm/stages.py`) не трогается: это разные сущности и разные
правила. Стадия клиента — аддитивные колонки в `client`:
    `stage` (текущее значение), `stage_manual` (флаг «выставлено руками»),
    `stage_auto` (последний авто-сигнал), `stage_updated_at` (миграция v3).

Правила авто-сигнала — чистая функция `auto_stage()` (легко тестируется, без БД):

    1) ≥2 оплаченных заказа              → «постоянный»
    2) ≥1 оплаченного заказа             → «клиент»
    3) нет активности ≥ 90 дней           → «спит/ушёл»
    4) иначе                              → None (сигнала нет, значение НЕ перетираем)

Ручное значение приоритетнее: при `stage_manual=True` авто-логика обновляет только
`stage_auto` и никогда не перетирает `stage`. Ручной режим можно снять («вернуть авто»).
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional

from sqlmodel import select

from ..db import Client, Order, Transaction, now, session

log = logging.getLogger("jarvis.crm.client_stages")

# (stage, русская подпись) — порядок = «лестница» отношений
CLIENT_STAGES: tuple[tuple[str, str], ...] = (
    ("lead", "лид"),
    ("negotiation", "переговоры"),
    ("client", "клиент"),
    ("permanent", "постоянный"),
    ("asleep", "спит/ушёл"),
)

CLIENT_STAGE_ORDER: dict[str, int] = {k: i for i, (k, _) in enumerate(CLIENT_STAGES)}
CLIENT_STAGE_LABEL: dict[str, str] = {k: label for k, label in CLIENT_STAGES}

PERMANENT_PAID_ORDERS = 2   # столько оплаченных заказов → «постоянный»
SLEEP_DAYS = 90             # столько дней без заказов/контакта → «спит/ушёл»
DEFAULT_STAGE = "lead"      # для клиента без заказов и без авто-сигнала


class ClientStageError(ValueError):
    """Неизвестная стадия / клиент не найден (роутер превращает в 400/404)."""


# ------------------------------------------------------------------ чистые правила
def is_client_stage(value: str | None) -> bool:
    return bool(value) and value in CLIENT_STAGE_ORDER


def label(stage: str | None) -> str:
    return CLIENT_STAGE_LABEL.get(stage or "", stage or "")


def _naive(dt: datetime | None) -> datetime | None:
    """SQLite отдаёт datetime без tzinfo — сравниваем только такие."""
    if dt is None:
        return None
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def auto_stage(paid_orders: int = 0, last_activity: datetime | None = None,
               now_dt: datetime | None = None, sleep_days: int = SLEEP_DAYS) -> str | None:
    """ЧИСТАЯ функция: авто-стадия клиента по его заказам.

    `paid_orders` — сколько заказов оплачено (статус «оплачен», `paid_at` или оплачена
    целиком сумма). `last_activity` — последний признак жизни (заказ/оплата/контакт).
    Возвращает `None`, если авто-сигнала нет: текущее значение не перетирается.

    Приоритет (по требованию задачи): «постоянный» → «клиент» → «спит/ушёл» → нет сигнала.
    """
    paid = max(0, int(paid_orders or 0))
    if paid >= PERMANENT_PAID_ORDERS:
        return "permanent"
    if paid >= 1:
        return "client"
    last = _naive(last_activity)
    if last is not None:
        ref = _naive(now_dt) or datetime.now()
        if (ref - last).days >= sleep_days:
            return "asleep"
    return None


def resolve(stored: str | None, manual: bool, auto: str | None) -> str:
    """Эффективная стадия: ручная → как есть; иначе авто; иначе сохранённая; иначе «лид».

    Старые записи (`stage` пуст/None) → авто-логика, обратная совместимость.
    """
    stored = stored or ""
    if manual and is_client_stage(stored):
        return stored
    if is_client_stage(stored):
        return stored
    if is_client_stage(auto):
        return auto
    return DEFAULT_STAGE


# ------------------------------------------------------------------ сбор фактов из БД
def _paid_sums(s) -> dict[int, float]:
    """Сумма оплат по каждому заказу (одним запросом, без N+1)."""
    out: dict[int, float] = {}
    rows = s.exec(select(Transaction).where(Transaction.order_id != None,  # noqa: E711
                                          Transaction.kind == "income")).all()
    for t in rows:
        out[t.order_id] = out.get(t.order_id, 0.0) + float(t.amount)
    return out


def _order_is_paid(o: Order, paid_sum: float) -> bool:
    if o.status == "paid" or o.paid_at is not None:
        return True
    return bool(o.price and paid_sum >= o.price - 0.5)


def _facts(orders_rows: Iterable[Order], paid_sums: dict[int, float],
           client: Client | None = None, now_dt: datetime | None = None) -> dict:
    """Чистые числа по заказам клиента: сколько оплачено и когда была последняя активность."""
    rows = list(orders_rows)
    last = _naive(getattr(client, "last_contact_at", None))
    if last is None and client is not None:
        last = _naive(getattr(client, "created_at", None))
    paid = 0
    total_paid = 0.0
    for o in rows:
        psum = paid_sums.get(o.id, 0.0)
        if _order_is_paid(o, psum):
            paid += 1
        total_paid += psum
        for d in (o.paid_at, o.done_at, o.last_contact_at, o.created_at, o.deadline):
            d = _naive(d)
            if d and (last is None or d > last):
                last = d
    ref = _naive(now_dt) or datetime.now()
    auto = auto_stage(paid, last, now_dt=ref)
    return {
        "paid_orders": paid,
        "orders_count": len(rows),
        "paid_total": round(total_paid),
        "last_activity": last,
        "days_since": (ref - last).days if last else None,
        "auto": auto,
    }


# ------------------------------------------------------------------ чтение
def view(c: Client, auto: str | None = None, facts: dict | None = None) -> dict:
    """Единый формат ответа по стадии клиента (для всех эндпоинтов и карточки)."""
    stored = c.stage or ""
    manual = bool(getattr(c, "stage_manual", False))
    if facts is None:
        facts = {"paid_orders": 0, "orders_count": 0, "paid_total": 0,
                 "last_activity": None, "days_since": None, "auto": None}
    eff = resolve(stored, manual, auto)
    auto_now = auto if auto is not None else (c.stage_auto or "")
    return {
        "client_id": c.id,
        "name": c.name,
        "stage": eff,
        "label": label(eff),
        "manual": manual,
        "stage_manual": manual,            # синоним (как колонка в БД)
        "auto": auto_now or "",
        "auto_label": label(auto_now) if auto_now else "",
        "stored": stored,                   # что реально лежит в client.stage
        "changed": eff != stored,           # расходится ли сохранённое с эффективным
        "updated_at": getattr(c, "stage_updated_at", None),
        "paid_orders": facts.get("paid_orders", 0),
        "orders_count": facts.get("orders_count", 0),
        "paid_total": facts.get("paid_total", 0),
        "last_activity": facts.get("last_activity"),
        "days_since": facts.get("days_since"),
    }


def get(cid: int) -> dict:
    """Прочитать стадию клиента (read-only, ничего не меняет)."""
    with session() as s:
        c = s.get(Client, cid)
        if not c:
            raise ClientStageError("Клиент не найден")
        rows = list(s.exec(select(Order).where(Order.client_id == cid)))
        f = _facts(rows, _paid_sums(s), c)
    return view(c, auto=f["auto"], facts=f)


def stages_payload() -> dict:
    """Справочник стадий + пороги авто-логики (для UI)."""
    return {
        "stages": [{"stage": k, "label": label(k), "order": i}
                   for i, (k, _) in enumerate(CLIENT_STAGES)],
        "order": list(CLIENT_STAGE_ORDER),
        "sleeper_days": SLEEP_DAYS,
        "permanent_paid_orders": PERMANENT_PAID_ORDERS,
    }


# ------------------------------------------------------------------ запись
def _log(client_id: int, kind: str, text: str, channel: str) -> None:
    """Лента активности клиента (таблица уже есть с фазы 4)."""
    from .service import log_event
    try:
        log_event(client_id=client_id, kind=kind, text=text, channel=channel)
    except Exception:  # pragma: no cover — лента не должна ронять основную операцию
        log.warning("стадия клиента: не записать активность %s", client_id, exc_info=True)


def set_stage(cid: int, stage: str, channel: str = "web") -> dict:
    """Поставить стадию ВРУЧНУЮ: `stage_manual=True`, авто-логика её больше не перетирает."""
    if not is_client_stage(stage):
        raise ClientStageError(f"Стадия клиента: {', '.join(CLIENT_STAGE_ORDER)}")
    with session() as s:
        c = s.get(Client, cid)
        if not c:
            raise ClientStageError("Клиент не найден")
        before = resolve(c.stage, bool(c.stage_manual), None)
        c.stage = stage
        c.stage_manual = True
        c.stage_updated_at = now()
        s.add(c); s.commit(); s.refresh(c)
    if before != stage:
        _log(cid, "client_stage", f"{label(before)} → {label(stage)} (вручную)", channel)
    out = get(cid)
    out["before"] = before
    out["changed"] = before != stage
    out["note"] = "выставлено вручную, авто не перетирает"
    return out


def clear_manual(cid: int, channel: str = "web") -> dict:
    """Снять ручной режим («вернуть авто»): значение сразу пересчитывается по заказам."""
    with session() as s:
        c = s.get(Client, cid)
        if not c:
            raise ClientStageError("Клиент не найден")
        before = resolve(c.stage, bool(c.stage_manual), None)
        was_manual = bool(c.stage_manual)
        c.stage_manual = False
        s.add(c); s.commit()
    out = recalc(cid, channel=channel)
    out["was_manual"] = was_manual
    out["before"] = before
    return out


def recalc(cid: int, channel: str = "web") -> dict:
    """Пересчитать авто-стадию клиента по его заказам.

    Ручное значение (`stage_manual=True`) не перетирается — обновляется только `stage_auto`.
    Если авто-сигнала нет, текущее значение сохраняется.
    """
    with session() as s:
        c = s.get(Client, cid)
        if not c:
            raise ClientStageError("Клиент не найден")
        rows = list(s.exec(select(Order).where(Order.client_id == cid)))
        f = _facts(rows, _paid_sums(s), c)
        before = resolve(c.stage, bool(c.stage_manual), f["auto"])
        stored_before = c.stage or ""
        manual = bool(c.stage_manual)
        if c.stage_auto != (f["auto"] or ""):
            c.stage_auto = f["auto"] or ""
        if not manual and f["auto"] and c.stage != f["auto"]:
            c.stage = f["auto"]
            c.stage_updated_at = now()
        s.add(c); s.commit(); s.refresh(c)
        stored_after = c.stage or ""
    if stored_before != stored_after:
        _log(cid, "client_stage", f"{label(before)} → {label(stored_after)} (авто)", channel)
    out = get(cid)
    out["changed"] = stored_before != stored_after     # сохранённое в БД значение изменилось
    out["before"] = before
    out["manual"] = manual
    out["note"] = ("ручная стадия — авто не перетирает" if manual
                   else ("авто-сигнала нет, значение сохранено" if not f["auto"] else "пересчитано по заказам"))
    return out


def recalc_all(channel: str = "web") -> dict:
    """Массовый пересчёт по всем клиентам (ручные значения не трогаем)."""
    with session() as s:
        ids = [c.id for c in s.exec(select(Client)).all()]
    updated: list[dict] = []
    skipped = 0
    for cid in ids:
        try:
            r = recalc(cid, channel=channel)
        except ClientStageError:  # pragma: no cover — клиент исчез между запросами
            continue
        if r.get("changed"):
            updated.append({"client_id": r["client_id"], "name": r["name"],
                            "stage": r["stage"], "label": r["label"]})
        if r.get("manual"):
            skipped += 1
    return {"total": len(ids), "updated": len(updated), "manual_skipped": skipped, "clients": updated}
