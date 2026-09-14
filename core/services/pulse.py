"""«Финансовый пульс» фрилансера — то, что реально двигает деньги, а не витрина:
  • задержки оплат: кто тянет после сдачи, сколько дней, как обычно платит;
  • ставка факт/план по заказу: съедает ли заказ больше часов, чем стоит;
  • налог самозанятого: сколько из ожидаемого/полученного уйдёт государству.
Всё под «режимом фрилансера» (freelance_settings) — каждая ручка отдельно, выключенное не показывается нигде."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from sqlmodel import select

from ..db import Order, Transaction, session, get_setting, set_setting

# ---------------------------------------------------------------- настройки режима
FREELANCE_DEFAULTS = {
    "enabled": False,        # мастер-выключатель: заказы, таймер, пульс — всё фриланс-меню
    "late_days": 3,          # оплата считается задержкой через N дней после сдачи
    "late_nudge": True,      # строки про задержки в дайджесте и на главной
    "rate_check": True,      # сравнивать часы факт/план в карточке заказа
    "rate_tolerance": 30,    # % перерасхода часов, после которого помечаем
    "tax_percent": 0,        # налог с фриланс-дохода (НПД 4 / 6); 0 — не считать
    "weekly": True,          # блок «фриланс за неделю» в недельном отчёте
}
_KEY = "freelance"


def freelance_settings() -> dict:
    out = dict(FREELANCE_DEFAULTS)
    try:
        raw = get_setting(_KEY)
        if raw:
            out.update({k: v for k, v in json.loads(raw).items() if k in FREELANCE_DEFAULTS})
    except Exception:
        pass
    return out


def save_freelance_settings(changes: dict) -> dict:
    cur = freelance_settings()
    for k, v in (changes or {}).items():
        if k not in FREELANCE_DEFAULTS:
            continue
        if k in ("late_days",):
            cur[k] = max(0, min(60, int(v)))
        elif k == "rate_tolerance":
            cur[k] = max(5, min(200, int(v)))
        elif k == "tax_percent":
            cur[k] = max(0, min(50, int(float(str(v).replace(",", ".")))))
        else:
            cur[k] = bool(v) if not isinstance(v, str) else v.lower() in ("1", "true", "yes", "on", "да")
    set_setting(_KEY, json.dumps(cur, ensure_ascii=False))
    return cur


def enabled() -> bool:
    return bool(freelance_settings()["enabled"])


def auto_enable_if_used() -> bool:
    """Первый запуск после обновления: если заказы уже есть — режим включаем сами, чтобы ничего не пропало с экрана."""
    if get_setting(_KEY) is not None:
        return enabled()
    with session() as s:
        has = s.exec(select(Order).limit(1)).first() is not None
    save_freelance_settings({"enabled": has})
    return has


# ---------------------------------------------------------------- задержки оплат
def _paid_by_order() -> dict[int, float]:
    with session() as s:
        rows = s.exec(select(Transaction).where(Transaction.order_id != None, Transaction.kind == "income")).all()  # noqa: E711
    out: dict[int, float] = {}
    for t in rows:
        out[t.order_id] = out.get(t.order_id, 0.0) + t.amount
    return out


def client_pay_habits() -> dict[int, dict]:
    """По каждому клиенту: за сколько дней после сдачи обычно платит (медиана по закрытым заказам), сколько заказов оплачено."""
    with session() as s:
        done = s.exec(select(Order).where(Order.status == "paid", Order.done_at != None, Order.paid_at != None)).all()  # noqa: E711
    by: dict[int, list[int]] = {}
    for o in done:
        if o.client_id is None:
            continue
        by.setdefault(o.client_id, []).append(max(0, (o.paid_at - o.done_at).days))
    out = {}
    for cid, days in by.items():
        days.sort()
        out[cid] = {"typical_days": days[len(days) // 2], "paid_orders": len(days), "max_days": days[-1]}
    return out


def late_payments(now: datetime | None = None) -> list[dict]:
    """Сданные, но не оплаченные заказы старше порога. Сортировка: самые давние сверху."""
    st = freelance_settings()
    now = now or datetime.now()
    cut = now - timedelta(days=st["late_days"])
    paid = _paid_by_order()
    habits = client_pay_habits()
    from .orders import list_clients
    names = {c.id: c.name for c in list_clients()}
    with session() as s:
        rows = s.exec(select(Order).where(Order.status == "done", Order.done_at != None, Order.done_at <= cut)).all()  # noqa: E711
    out = []
    for o in rows:
        left = max(0.0, o.price - paid.get(o.id, 0.0))
        if left <= 0:
            continue
        days = (now - o.done_at).days
        h = habits.get(o.client_id or -1)
        out.append({"order_id": o.id, "title": o.title, "client": names.get(o.client_id), "client_id": o.client_id,
                    "left": round(left), "days": days, "done_at": o.done_at,
                    "typical_days": h["typical_days"] if h else None,
                    "beyond_habit": bool(h and days > h["typical_days"])})
    out.sort(key=lambda x: -x["days"])
    return out


def late_lines(limit: int = 3) -> list[str]:
    """Строки для дайджеста/главной. Пусто, если режим выключен или подсказки выключены."""
    st = freelance_settings()
    if not (st["enabled"] and st["late_nudge"]):
        return []
    from .finance import money
    out = []
    for x in late_payments()[:limit]:
        who = x["client"] or f"«{x['title']}»"
        tail = f" (обычно платит за {x['typical_days']} дн.)" if x["typical_days"] is not None else ""
        out.append(f"💸 {who} задерживает {money(x['left'])} за «{x['title']}» — {x['days']} дн. после сдачи{tail}.")
    return out


def late_text() -> str:
    """«кто задерживает» в чате."""
    st = freelance_settings()
    from .finance import money
    rows = late_payments()
    if not rows:
        return f"Никто не задерживает: все сданные заказы оплачены или ещё в пределах {st['late_days']} дн. после сдачи."
    total = sum(r["left"] for r in rows)
    lines = [f"**Задерживают оплату** — {money(total)}:"]
    for x in rows:
        who = x["client"] or "без клиента"
        tail = f", обычно платит за {x['typical_days']} дн." if x["typical_days"] is not None else ""
        lines.append(f"• {who} — «{x['title']}», {money(x['left'])}, {x['days']} дн. после сдачи{tail}")
    lines.append("Скажите «задача: напомнить … про оплату» — поставлю напоминание.")
    return "\n".join(lines)


def expected_date_for(o_done_at: datetime | None, client_id: int | None, fallback: datetime, habits: dict | None = None) -> datetime:
    """Когда ждать деньги по сданному заказу: дата сдачи + как обычно платит клиент (не раньше сегодня)."""
    if o_done_at is None:
        return fallback
    habits = habits if habits is not None else client_pay_habits()
    h = habits.get(client_id or -1)
    when = o_done_at + timedelta(days=(h["typical_days"] if h else freelance_settings()["late_days"]))
    return max(when, datetime.now())


# ---------------------------------------------------------------- ставка: факт против плана
def rate_check(o: dict) -> dict | None:
    """o — order_view(). Есть смысл, только если гоняли таймер и была оценка часов.
    Возвращает {'hours','estimate_h','over_pct','rate','planned_rate','warn'} или None."""
    st = freelance_settings()
    if not (st["enabled"] and st["rate_check"]):
        return None
    hours, est, price = float(o.get("hours") or 0), float(o.get("estimate_h") or 0), float(o.get("price") or 0)
    if hours < 0.25 or not price:
        return None
    out = {"hours": round(hours, 1), "estimate_h": est or None, "rate": round(price / hours),
           "planned_rate": round(price / est) if est else None, "over_pct": None, "warn": False}
    if est:
        out["over_pct"] = round((hours - est) / est * 100)
        out["warn"] = out["over_pct"] > st["rate_tolerance"]
    return out


def rate_line(o: dict) -> str | None:
    r = rate_check(o)
    if not r:
        return None
    from .finance import money
    if r["estimate_h"]:
        s = f"{r['hours']} ч из {r['estimate_h']} · {money(r['rate'])}/ч"
        if r["warn"]:
            s += f" вместо {money(r['planned_rate'])} — заказ съедает на {r['over_pct']} % больше времени, чем планировали"
        return s
    return f"{r['hours']} ч · {money(r['rate'])}/ч"


# ---------------------------------------------------------------- налог
def tax_rate() -> float:
    st = freelance_settings()
    return (st["tax_percent"] / 100.0) if st["enabled"] and st["tax_percent"] else 0.0


def tax_of(amount: float) -> float:
    return round(amount * tax_rate())


def tax_month(now: datetime | None = None) -> dict:
    """Налог за текущий месяц: с уже полученного по заказам и с того, что ещё ждём. 0 — если выключено."""
    now = now or datetime.now()
    rate = tax_rate()
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with session() as s:
        got = sum(t.amount for t in s.exec(select(Transaction).where(Transaction.order_id != None, Transaction.kind == "income", Transaction.date >= start)))  # noqa: E711
    from .orders import expected_income
    exp = sum(e["amount"] for e in expected_income(60))
    return {"percent": round(rate * 100), "received": round(got), "tax_received": round(got * rate),
            "expected": round(exp), "tax_expected": round(exp * rate), "tax_total": round((got + exp) * rate)}


# ---------------------------------------------------------------- неделя
def weekly_block() -> list[str]:
    """Три строки для недельного отчёта. Пусто, если режим/блок выключен или нечего сказать."""
    st = freelance_settings()
    if not (st["enabled"] and st["weekly"]):
        return []
    from .finance import money
    from .orders import stats
    since = datetime.now() - timedelta(days=7)
    with session() as s:
        got = sum(t.amount for t in s.exec(select(Transaction).where(Transaction.order_id != None, Transaction.kind == "income", Transaction.date >= since)))  # noqa: E711
    stt = stats(1)
    lines = []
    if got or stt["week_load_h"]:
        s_ = f"💼 За неделю по заказам: {money(got)}" + (f" · {stt['week_load_h']} ч фокуса" if stt["week_load_h"] else "")
        if got and stt["week_load_h"] >= 1:
            s_ += f" · {money(got / stt['week_load_h'])}/ч"
        if tax_rate() and got:
            s_ += f" · налог ~{money(tax_of(got))}"
        lines.append(s_ + ".")
    lines += late_lines(2)
    return lines
