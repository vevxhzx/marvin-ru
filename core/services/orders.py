"""Заказы для фрилансера: клиенты, заказы, дедлайны, оплаты и таймер-помодоро.

Принципы:
- Деньги по заказу — обычные транзакции с order_id: доход, баланс и статистика — одна правда, ничего не считается дважды.
- Незакрытые заказы = ожидаемый доход: их видит прогноз кассы (insights.cash_forecast).
- Помодоро — WorkSession; из них реальные часы и ставка ₽/час по заказу и по клиенту.
- Один активный таймер на всё приложение (сайт, Telegram, голос видят один и тот же).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlmodel import select

from ..db import Client, Order, Transaction, WorkSession, log_action, now, remember, session
from . import finance
from .finance import money
from .match import same

log = logging.getLogger("assistant.orders")

STATUSES = ("new", "work", "review", "done", "paid", "cancelled")
STATUS_LABEL = {"new": "обсуждение", "work": "в работе", "review": "на правках", "done": "сдан", "paid": "оплачен", "cancelled": "отменён"}
OPEN = ("new", "work", "review")
UNPAID = ("new", "work", "review", "done")
INCOME_CATEGORY = "Фриланс"


class OrderError(ValueError):
    pass


# ---------------------------------------------------------------- клиенты
def list_clients() -> list[Client]:
    with session() as s:
        return list(s.exec(select(Client).order_by(Client.name)))


def get_or_create_client(name: str | None, kind: str = "client") -> Client | None:
    """Найти человека по имени/псевдониму или завести. Из заказа — «клиент» (и «человек» без типа становится клиентом:
    раз есть заказ — значит заказчик; семью/друзей не трогаем). Из people.add_person — kind="person"."""
    name = (name or "").strip(" «»\"'")
    if not name:
        return None
    with session() as s:
        for c in s.exec(select(Client)).all():
            names = [c.name] + [a.strip() for a in (c.aliases or "").split(",") if a.strip()]
            if any(n.lower() == name.lower() or same(n, name) for n in names):
                if kind == "client" and c.kind == "person":
                    c.kind = "client"; s.add(c); s.commit(); s.refresh(c)
                return c
        c = Client(name=name, kind=kind)
        s.add(c); s.commit(); s.refresh(c)
        return c


def update_client(cid: int, **fields) -> Client | None:
    with session() as s:
        c = s.get(Client, cid)
        if not c:
            return None
        for k, v in fields.items():
            if k in ("name", "contact", "notes") and v is not None:
                setattr(c, k, str(v).strip() or None if k != "name" else str(v).strip())
        s.add(c); s.commit(); s.refresh(c)
        return c


def delete_client(cid: int) -> bool:
    with session() as s:
        c = s.get(Client, cid)
        if not c:
            return False
        for o in s.exec(select(Order).where(Order.client_id == cid)).all():
            o.client_id = None; s.add(o)
        s.delete(c); s.commit()
        return True


# ---------------------------------------------------------------- заказы
def add_order(title: str, price: float = 0, client: str | None = None, deadline: datetime | None = None,
              notes: str | None = None, estimate_h: float = 0, status: str = "work", source: str = "web") -> Order:
    title = (title or "").strip(" .")
    if not title:
        raise OrderError("Нужно название заказа")
    price = float(price or 0)
    if price < 0:
        raise OrderError("Сумма не может быть отрицательной")
    c = get_or_create_client(client)
    with session() as s:
        o = Order(title=title[0].upper() + title[1:], price=price, client_id=c.id if c else None, deadline=deadline,
                  notes=(notes or None), estimate_h=float(estimate_h or 0), status=status if status in STATUSES else "work", source=source)
        s.add(o); s.commit(); s.refresh(o)
        remember(s, "order", f"Заказ: «{o.title}»" + (f" для {c.name}" if c else "") + (f" · {money(price)}" if price else "")
                 + (f" · до {deadline:%d.%m %H:%M}" if deadline else ""), "order", o.id, source)
        log_action(s, "add_order", "order", o.id, o.title, source)
        s.commit()
        return o


def get_order(oid: int) -> Order | None:
    with session() as s:
        return s.get(Order, oid)


def find_order(query: str | int, open_only: bool = True) -> Order | None:
    """По номеру, точному/нечёткому названию или имени клиента. Сначала открытые."""
    if isinstance(query, int) or str(query).strip().lstrip("#").isdigit():
        return get_order(int(str(query).strip().lstrip("#")))
    q = str(query).strip(" «»\"'").lower()
    if not q:
        return None
    with session() as s:
        rows = list(s.exec(select(Order).order_by(Order.created_at.desc())))
        clients = {c.id: c.name for c in s.exec(select(Client))}
    pools = [[o for o in rows if o.status in OPEN], [o for o in rows if o.status not in OPEN]] if open_only else [rows]
    for pool in pools:
        for o in pool:
            if o.title.lower() == q:
                return o
        for o in pool:
            if q in o.title.lower() or same(o.title, q):
                return o
        for o in pool:
            cname = clients.get(o.client_id, "")
            if cname and (q in cname.lower() or same(cname, q)):
                return o
    return None


def update_order(oid: int, **fields) -> Order | None:
    with session() as s:
        o = s.get(Order, oid)
        if not o:
            return None
        if "client" in fields:
            c = get_or_create_client(fields.pop("client"))
            o.client_id = c.id if c else None
        for k, v in fields.items():
            if k == "status":
                if v not in STATUSES:
                    raise OrderError(f"Статус: {', '.join(STATUSES)}")
                if v == "done" and o.status != "done":
                    o.done_at = now()
                if v == "paid" and o.status != "paid":
                    o.paid_at = now(); o.done_at = o.done_at or now()
                o.status = v
            elif k == "price":
                if float(v or 0) < 0:
                    raise OrderError("Цена не может быть отрицательной")
                o.price = float(v or 0)
            elif k == "estimate_h":
                o.estimate_h = max(0.0, float(v or 0))
            elif k in ("title", "notes"):
                setattr(o, k, (str(v).strip() or None) if k == "notes" else str(v).strip())
            elif k == "deadline":
                o.deadline = v
        s.add(o); s.commit(); s.refresh(o)
        remember(s, "order", f"Заказ «{o.title}»: {STATUS_LABEL[o.status]}" + (f" · {money(o.price)}" if o.price else ""), "order", o.id)
        s.commit()
        return o


def delete_order(oid: int) -> bool:
    with session() as s:
        o = s.get(Order, oid)
        if not o:
            return False
        for ws in s.exec(select(WorkSession).where(WorkSession.order_id == oid)).all():
            s.delete(ws)
        for t in s.exec(select(Transaction).where(Transaction.order_id == oid)).all():
            t.order_id = None; s.add(t)   # деньги остаются в финансах — их реально получили
        s.delete(o); s.commit()
        return True


def paid_for(oid: int) -> float:
    with session() as s:
        return sum(t.amount for t in s.exec(select(Transaction).where(Transaction.order_id == oid, Transaction.kind == "income")))


def add_payment(oid: int, amount: float, note: str | None = None, account: str | None = None, source: str = "web",
                date: datetime | None = None) -> Transaction:
    """Аванс/оплата по заказу — доход в категории «Фриланс» с привязкой. Полная оплата закрывает заказ в «оплачен».
    `date` — когда пришли деньги (старый заказ задним числом); по умолчанию сейчас."""
    o = get_order(oid)
    if not o:
        raise OrderError("Заказ не найден")
    if float(amount) <= 0:
        raise OrderError("Сумма оплаты должна быть больше нуля")
    with session() as s:
        cname = s.get(Client, o.client_id).name if o.client_id else None
    t = finance.add_transaction(amount, "income", INCOME_CATEGORY, note or (f"{o.title}" + (f" · {cname}" if cname else "")),
                                account, date=date, source=source, order_id=oid)
    total = paid_for(oid)
    if o.price and total >= o.price - 0.5 and o.status in UNPAID:
        update_order(oid, status="paid")
        if date and date < datetime.now() - timedelta(days=1):   # задним числом — сдан и оплачен тогда же, а не сегодня
            with session() as s:
                oo = s.get(Order, oid)
                if oo:
                    oo.paid_at = date; oo.done_at = min(oo.done_at or date, date); s.add(oo); s.commit()
    return t


def payments_for(oid: int) -> list[Transaction]:
    with session() as s:
        return list(s.exec(select(Transaction).where(Transaction.order_id == oid).order_by(Transaction.date.desc())))


def sessions_for(oid: int, limit: int = 50) -> list[WorkSession]:
    with session() as s:
        return list(s.exec(select(WorkSession).where(WorkSession.order_id == oid, WorkSession.kind == "focus")
                           .order_by(WorkSession.started_at.desc()).limit(limit)))


def hours_for(oid: int) -> float:
    with session() as s:
        rows = s.exec(select(WorkSession).where(WorkSession.order_id == oid, WorkSession.kind == "focus")).all()
    return round(sum(_session_min(w) for w in rows) / 60, 2)


def _session_min(w: WorkSession) -> float:
    end = w.ended_at or min(datetime.now(), w.started_at + timedelta(minutes=w.planned_min))
    return max(0.0, (end - w.started_at).total_seconds() / 60)


def _boards_by_order() -> dict[int, int]:
    """Доска заказа (id) по id заказа — одним запросом; кэш на 2 секунды, чтобы список из 300 заказов не делал 300 запросов."""
    import time as _t
    from ..db import Board
    cache = _boards_by_order.__dict__
    if cache.get("at", 0) + 2 > _t.monotonic():
        return cache["val"]
    with session() as s:
        val = {b.order_id: b.id for b in s.exec(select(Board).where(Board.order_id != None, Board.archived == False)).all()}  # noqa: E711,E712
    cache["at"], cache["val"] = _t.monotonic(), val
    return val


def order_view(o: Order, clients: dict[int, str] | None = None) -> dict:
    """Заказ + производные: оплачено, остаток, часы, ставка, срочность."""
    if clients is None:
        clients = {c.id: c.name for c in list_clients()}
    paid = paid_for(o.id)
    hours = hours_for(o.id)
    d = o.model_dump()
    # закрытый заказ ничего не «ждёт», даже если оплату не записывали (старый заказ закрыт статусом вручную)
    left = 0.0 if o.status in ("paid", "cancelled") else max(0.0, o.price - paid)
    d.update({"client": clients.get(o.client_id), "paid": paid, "left": left, "hours": hours,
              "rate": round(o.price / hours) if hours >= 0.25 and o.price else None,
              "status_label": STATUS_LABEL.get(o.status, o.status),
              "days_left": (o.deadline.date() - datetime.now().date()).days if o.deadline and o.status in OPEN else None,
              # «на правках» после срока — не просрочка: первая версия сдана, идут правки; срок показываем, но не краснеем
              "overdue": bool(o.deadline and o.status in ("new", "work") and o.deadline < datetime.now()),
              "past_due": bool(o.deadline and o.status == "review" and o.deadline < datetime.now())})
    from . import pulse
    d["pulse"] = pulse.rate_check(d)
    d["board_id"] = _boards_by_order().get(o.id)
    return d


def list_orders(status: str | None = None, include_closed: bool = False, limit: int = 300) -> list[dict]:
    with session() as s:
        q = select(Order)
        if status:
            q = q.where(Order.status == status)
        elif not include_closed:
            q = q.where(Order.status.in_(UNPAID))
        rows = list(s.exec(q.order_by(Order.created_at.desc()).limit(limit)))
    clients = {c.id: c.name for c in list_clients()}
    out = [order_view(o, clients) for o in rows]
    # открытые — по дедлайну (без дедлайна в конец), закрытые — по дате
    out.sort(key=lambda d: (d["status"] not in OPEN, d["deadline"] or datetime.max, -(d["id"])))
    return out


def expected_income(days: int = 30) -> list[dict]:
    """Ожидаемые поступления: остаток по незакрытым заказам. Дата — дедлайн (или +7 дней, если его нет)."""
    from . import pulse
    habits = pulse.client_pay_habits() if pulse.enabled() else {}
    with session() as s:
        clients = {c.id: c for c in s.exec(select(Client))}
    out = []
    batched: dict[tuple[int, object], dict] = {}   # клиент-«пачкой»: все его сданные заказы — одна точка на день выплат
    horizon = (datetime.now() + timedelta(days=days)).date()
    for d in list_orders():
        if d["status"] in UNPAID and d["left"] > 0 and d["status"] != "new":
            when = d["deadline"] or (datetime.now() + timedelta(days=7))
            c = clients.get(d.get("client_id") or -1)
            if d["status"] == "done":
                # сдан — деньги ждём «на днях»; в режиме фрилансера — когда этот клиент обычно платит / в его день выплат
                when = pulse.expected_date_for(d.get("done_at"), d.get("client_id"), max(when, datetime.now()), habits, client=c) if habits or pulse.enabled() else max(when, datetime.now())
                if c and c.pay_mode in ("batch", "monthly"):
                    key = (c.id, when.date())
                    b = batched.get(key)
                    if b:
                        b["amount"] += d["left"]; b["n"] += 1
                        b["title"] = f"{c.name}, {b['n']} заказа" if b["n"] < 5 else f"{c.name}, {b['n']} заказов"
                    else:
                        batched[key] = {"title": f"{c.name}: {d['title']}", "client": d["client"], "amount": d["left"], "date": when, "order_id": d["id"], "n": 1}
                    continue
            if when.date() <= horizon:
                out.append({"title": d["title"], "client": d["client"], "amount": d["left"], "date": when, "order_id": d["id"]})
    out.extend(b for b in batched.values() if b["date"].date() <= horizon)
    out.sort(key=lambda x: x["date"])
    return out


# ---------------------------------------------------------------- помодоро / таймер
POMO_DEFAULTS = {"focus": 25, "short": 5, "long": 15, "long_every": 4, "auto_break": True,
                 "sound": "bell", "voice": True, "volume": 0.6}
_POMO_SOUNDS = ("bell", "ding", "tick", "off")


def pomo_settings() -> dict:
    """Настройки помодоро — в базе (setting `pomodoro`), общие для сайта, Telegram и голоса; менять без перезапуска."""
    import json
    from ..db import get_setting
    out = dict(POMO_DEFAULTS)
    try:
        raw = get_setting("pomodoro")
        if raw:
            out.update({k: v for k, v in json.loads(raw).items() if k in POMO_DEFAULTS})
    except Exception:
        pass
    return out


def save_pomo_settings(changes: dict) -> dict:
    import json
    from ..db import set_setting
    cur = pomo_settings()
    for k, v in (changes or {}).items():
        if k not in POMO_DEFAULTS:
            continue
        if k in ("focus", "short", "long"):
            cur[k] = max(1, min(180, int(v)))
        elif k == "long_every":
            cur[k] = max(0, min(12, int(v)))
        elif k in ("auto_break", "voice"):
            cur[k] = bool(v)
        elif k == "sound":
            cur[k] = v if v in _POMO_SOUNDS else "bell"
        elif k == "volume":
            cur[k] = max(0.0, min(1.0, float(v)))
    set_setting("pomodoro", json.dumps(cur, ensure_ascii=False))
    return cur


def next_break_minutes() -> int:
    """Короткий перерыв, а каждый N-й (long_every) — длинный."""
    st = pomo_settings()
    n = today_sessions()
    if st["long_every"] and n and n % st["long_every"] == 0:
        return st["long"]
    return st["short"]


def active_session() -> WorkSession | None:
    with session() as s:
        w = s.exec(select(WorkSession).where(WorkSession.ended_at == None).order_by(WorkSession.id.desc())).first()  # noqa: E711
        if not w:
            return None
        # таймер, про который забыли на 3 часа, — закрываем по плану, а не по факту
        if datetime.now() > w.started_at + timedelta(minutes=w.planned_min + 180):
            w.ended_at = w.started_at + timedelta(minutes=w.planned_min); s.add(w); s.commit()
            return None
        return w


def start_session(order_id: int | None = None, minutes: int | None = None, kind: str = "focus", source: str = "web", note: str | None = None) -> WorkSession:
    if not minutes:
        minutes = pomo_settings()["focus"] if kind != "break" else next_break_minutes()
    minutes = max(1, min(180, int(minutes)))
    stop_session()   # один таймер на всех
    with session() as s:
        w = WorkSession(order_id=order_id, planned_min=minutes, kind=kind if kind in ("focus", "break") else "focus", source=source, note=note)
        s.add(w); s.commit(); s.refresh(w)
        if kind == "focus" and order_id:
            o = s.get(Order, order_id)
            if o and o.status == "new":
                o.status = "work"; s.add(o); s.commit()
        return w


def stop_session(note: str | None = None) -> WorkSession | None:
    with session() as s:
        w = s.exec(select(WorkSession).where(WorkSession.ended_at == None).order_by(WorkSession.id.desc())).first()  # noqa: E711
        if not w:
            return None
        w.ended_at = min(datetime.now(), w.started_at + timedelta(minutes=w.planned_min + 180))
        if note:
            w.note = note
        s.add(w); s.commit(); s.refresh(w)
        if w.kind == "focus" and _session_min(w) >= 1 and w.order_id:
            o = s.get(Order, w.order_id)
            if o:
                remember(s, "order", f"Работал над «{o.title}» {int(_session_min(w))} мин", "order", o.id, w.source)
                s.commit()
        return w


def timer_state() -> dict:
    """Что показывать в шапке сайта / говорить голосом."""
    w = active_session()
    st = pomo_settings()
    base = {"today_min": today_focus_min(), "today_sessions": today_sessions(),
            "focus_min": st["focus"], "break_min": next_break_minutes(), "sound": st["sound"], "volume": st["volume"]}
    if not w:
        return {"active": False, **base}
    end = w.started_at + timedelta(minutes=w.planned_min)
    left = max(0, int((end - datetime.now()).total_seconds()))
    o = get_order(w.order_id) if w.order_id else None
    return {"active": True, "id": w.id, "kind": w.kind, "order_id": w.order_id, "order": o.title if o else None,
            "started_at": w.started_at, "planned_min": w.planned_min, "ends_at": end, "left_sec": left, "overtime": left == 0, **base}


def today_focus_min() -> int:
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    with session() as s:
        rows = s.exec(select(WorkSession).where(WorkSession.kind == "focus", WorkSession.started_at >= start)).all()
    return int(sum(_session_min(w) for w in rows))


def today_sessions() -> int:
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    with session() as s:
        rows = s.exec(select(WorkSession).where(WorkSession.kind == "focus", WorkSession.started_at >= start, WorkSession.ended_at != None)).all()  # noqa: E711
    # «помидор» — это отработанная сессия, а не таймер, остановленный через минуту
    return len([w for w in rows if _session_min(w) >= w.planned_min * 0.8])


def due_timer_ping() -> dict | None:
    """Планировщик раз в 20 с: таймер только что истёк — один раз сообщить (сайт/TG/голос). Возвращает событие или None."""
    w = active_session()
    if not w:
        return None
    end = w.started_at + timedelta(minutes=w.planned_min)
    if datetime.now() < end or w.note == "__pinged__":
        return None
    with session() as s:
        row = s.get(WorkSession, w.id)
        row.note = "__pinged__"; s.add(row); s.commit()
    o = get_order(w.order_id) if w.order_id else None
    st = pomo_settings()
    if w.kind == "break":
        return {"kind": "timer", "text": "Перерыв окончен. Продолжаем?", "order_id": w.order_id, "session_kind": "break", "settings": st}
    n = today_sessions() + 1
    brk = next_break_minutes()
    text = f"Помодоро №{n} готово" + (f" — «{o.title}»" if o else "") + f". Сегодня {today_focus_min()} мин фокуса."
    auto = False
    if st["auto_break"]:
        # фокус закрыт по плану, перерыв стартует сам — как договорились в настройках
        with session() as s:
            row = s.get(WorkSession, w.id)
            row.ended_at = end; s.add(row); s.commit()
        start_session(w.order_id, brk, kind="break", source="system")
        text += f" Перерыв {brk} минут — пошёл."
        auto = True
    else:
        text += f" Перерыв {brk} минут?"
    return {"kind": "timer", "text": text, "order_id": w.order_id, "session_kind": "focus", "break_min": brk, "auto_break": auto, "settings": st}


# ---------------------------------------------------------------- статистика
def stats(months: int = 6) -> dict:
    nowd = datetime.now()
    since = (nowd.replace(day=1) - timedelta(days=31 * (months - 1))).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with session() as s:
        txs = s.exec(select(Transaction).where(Transaction.order_id != None, Transaction.kind == "income", Transaction.date >= since)).all()  # noqa: E711
        orders = list(s.exec(select(Order)))
        sessions = s.exec(select(WorkSession).where(WorkSession.kind == "focus", WorkSession.started_at >= since)).all()
        clients = {c.id: c for c in s.exec(select(Client))}
    by_month: dict[str, float] = {}
    for t in txs:
        k = t.date.strftime("%Y-%m")
        by_month[k] = by_month.get(k, 0) + t.amount
    months_out = []
    cur = since
    while cur <= nowd:
        k = cur.strftime("%Y-%m")
        months_out.append({"month": k, "income": round(by_month.get(k, 0))})
        cur = (cur.replace(day=28) + timedelta(days=4)).replace(day=1)
    by_client: dict[int | None, dict] = {}
    for o in orders:
        paid_period = sum(t.amount for t in txs if t.order_id == o.id)   # за окно статистики — для ставки
        paid_all = paid_for(o.id)                                         # за всё время — «сколько получено от клиента»
        hrs = sum(_session_min(w) for w in sessions if w.order_id == o.id) / 60
        b = by_client.setdefault(o.client_id, {"client": clients[o.client_id].name if o.client_id in clients else "без клиента",
                                                "client_id": o.client_id, "orders": 0, "paid": 0.0, "_paid_period": 0.0, "total": 0.0,
                                                "hours": 0.0, "open": 0, "unpaid": 0.0})
        b["orders"] += 1; b["paid"] += paid_all; b["_paid_period"] += paid_period; b["hours"] += hrs
        if o.status != "cancelled":
            b["total"] += o.price                                         # на какую сумму заказов всего
        if o.status in OPEN:
            b["open"] += 1
        if o.status in UNPAID:
            b["unpaid"] += max(0.0, o.price - paid_all)
    top = sorted(by_client.values(), key=lambda b: -b["paid"])
    for b in top:
        b["rate"] = round(b["_paid_period"] / b["hours"]) if b["hours"] >= 1 else None
        del b["_paid_period"]
        b["paid"] = round(b["paid"]); b["total"] = round(b["total"]); b["hours"] = round(b["hours"], 1); b["unpaid"] = round(b["unpaid"])
    done = [o for o in orders if o.status in ("done", "paid") and o.done_at]
    lead = [max(0, (o.done_at - o.created_at).days) for o in done]
    total_h = sum(_session_min(w) for w in sessions) / 60
    total_paid = sum(t.amount for t in txs)
    open_orders = [o for o in orders if o.status in OPEN]
    return {"months": months_out, "clients": top[:12],
            "total_income": round(total_paid), "total_hours": round(total_h, 1),
            "rate": round(total_paid / total_h) if total_h >= 1 else None,
            "avg_check": round(sum(o.price for o in done) / len(done)) if done else None,
            "avg_lead_days": round(sum(lead) / len(lead), 1) if lead else None,
            "open": len(open_orders), "unpaid": round(sum(max(0.0, o.price - paid_for(o.id)) for o in orders if o.status in UNPAID)),
            "week_load_h": round(sum(_session_min(w) for w in sessions if w.started_at >= nowd - timedelta(days=7)) / 60, 1),
            "focus_days": _focus_days(sessions, 14)}


def _focus_days(sessions: list[WorkSession], days: int) -> list[dict]:
    out = []
    for i in range(days - 1, -1, -1):
        d = (datetime.now() - timedelta(days=i)).date()
        out.append({"date": d.isoformat(), "min": int(sum(_session_min(w) for w in sessions if w.started_at.date() == d))})
    return out


def deadline_nudges() -> list[str]:
    """Утренний дайджест / планировщик: что горит по заказам."""
    out = []
    for d in list_orders():
        if d["status"] not in OPEN or not d["deadline"]:
            continue
        if d["overdue"]:
            out.append(f"🔴 «{d['title']}»{' · ' + d['client'] if d['client'] else ''} — дедлайн прошёл {d['deadline']:%d.%m}, статус «{d['status_label']}».")
        elif d["past_due"]:
            continue   # на правках после срока — сдано, идут правки; не горит
        elif d["days_left"] is not None and d["days_left"] <= 2:
            when = "сегодня" if d["days_left"] == 0 else "завтра" if d["days_left"] == 1 else "послезавтра"
            hrs = f", наработано {d['hours']} ч" if d["hours"] else ", сессий по нему ещё не было" if d["status"] == "work" else ""
            out.append(f"⏳ «{d['title']}»{' · ' + d['client'] if d['client'] else ''} — сдать {when} ({d['deadline']:%H:%M}){hrs}.")
    return out


def summary_text() -> str:
    """«Заказы» / «что по заказам» — короткий расклад."""
    rows = list_orders()
    if not rows:
        return "Заказов нет. Добавьте: «заказ: ролик для Пятёрочки, 25к, до пятницы»."
    st = stats(1)
    lines = [f"**Заказы**: {st['open']} в работе, не оплачено **{money(st['unpaid'])}**" + (f", за неделю {st['week_load_h']} ч фокуса" if st["week_load_h"] else "") + "."]
    for d in rows[:8]:
        dl = ""
        if d["deadline"]:
            dl = " · 🔴 просрочен" if d["overdue"] else f" · срок был {d['deadline']:%d.%m}" if d["past_due"] else f" · до {d['deadline']:%d.%m}" + (f" ({d['days_left']} дн.)" if d["days_left"] is not None and 0 < d["days_left"] <= 7 else " (сегодня)" if d["days_left"] == 0 else "")
        pay = f" · осталось {money(d['left'])}" if d["left"] and d["paid"] else f" · {money(d['price'])}" if d["price"] else ""
        lines.append(f"• #{d['id']} {d['title']}{' — ' + d['client'] if d['client'] else ''} · {d['status_label']}{pay}{dl}" + (f" · {d['hours']} ч" if d["hours"] else ""))
    from . import pulse
    lines += pulse.late_lines(3)
    tm = pulse.tax_month()
    if tm["percent"] and (tm["received"] or tm["expected"]):
        lines.append(f"🧾 Налог {tm['percent']} %: с полученного в этом месяце ~{money(tm['tax_received'])}" + (f", с ожидаемого ещё ~{money(tm['tax_expected'])}" if tm["expected"] else "") + ".")
    return "\n".join(lines)
