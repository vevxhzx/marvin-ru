# -*- coding: utf-8 -*-
"""Правила заказов: заказы, помодоро, цели-конверты, фин-отчёты, оплата по заказу.

Вынесено из core/brain/agent.py 1:1. Regexes, Reply, CONFIRM_AMOUNT,
_pending_*, say/money остаются в agent и импортируются здесь.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from ..agent import (
    CONFIRM_AMOUNT,
    FIN_TECH_RX,
    GOAL_RX,
    GOALS_Q_RX,
    LATE_Q_RX,
    NO_RX,
    ORDER_RX,
    ORDERS_Q_RX,
    PAYMENT_RX,
    POMO_BREAK_RX,
    POMO_Q_RX,
    POMO_RX,
    POMO_STOP_RX,
    SAVE_RX,
    Reply,
    _MONTH_N,
    _MONTH_TARGET_RX,
    _pending_consume,
    _pending_set,
    money,
    say,
)
from .people import people_rule


def _month_target(text: str):
    """«к марту», «до декабря 2027» → первое число того месяца (следующего такого, если уже прошёл)."""
    m = _MONTH_TARGET_RX.search(text)
    if not m:
        return None, text
    mon = _MONTH_N[m.group(1).lower()]
    now = datetime.now()
    year = int(m.group(2)) if m.group(2) else (now.year if mon > now.month else now.year + 1)
    return datetime(year, mon, 1, 23, 59), (text[:m.start()] + " " + text[m.end():]).strip()


def record_order_payment(oid: int, amount: float, channel: str, pay_date) -> Reply:
    """Платёж по заказу + честный ответ. Заказ не выдумываем — его ищет вызывающий."""
    from core.services import orders

    try:
        orders.add_payment(oid, amount, source=channel, date=pay_date)
    except Exception as e:
        return Reply(f"Не записал: {e}", [], "rules")
    v = orders.order_view(orders.get_order(oid))
    return Reply(f"Оплата {money(amount)} по «{v['title']}» — в доходах" + (f" за {pay_date:%d.%m}" if pay_date else "") + "."
                 + (f" Осталось {money(v['left'])}." if v["left"] > 0 else " Заказ закрыт как оплаченный ✓"), ["order_payment"])


def pay_ask_rule(text: str, low: str, channel: str) -> Reply | None:
    """Батч 1: ответ на «оплата по заказу [кандидат] или обычный доход?».
    «заказ» → платёж по заказу-кандидату (заказ не выдумываем);
    «доход» → обычный доход; «нет» — не пишем. Чужой слот не трогаем."""
    from core.services import finance as _finance

    p = _pending_consume(channel, prefix="pay_ask|")   # TTL + one-shot; чужой слот цел
    if not p:
        return None
    orig, _ts = p
    try:
        d = json.loads(orig[8:])
    except (ValueError, IndexError):
        return None
    amount = d.get("amount")
    q = (d.get("q") or "").strip()
    oid = d.get("oid")
    try:
        pay_date = datetime.fromisoformat(d["date"]) if d.get("date") else None
    except ValueError:
        pay_date = None
    if re.match(r"^\s*(?:это\s+)?(заказ|по\s+заказу|оплата(?:\s+по\s+заказу)?|аванс(?:\s+по\s+заказу)?)\s*[.!]*\s*$", text, re.I):
        from core.services import orders
        o = None
        if oid:
            try:
                o = orders.get_order(oid)
            except Exception:
                o = None
        if o is None and q:
            o = orders.find_order(q)
        if o is None:
            return Reply(f"Заказ{(' «' + q + '»') if q else ''} не нашёл, сэр — не выдумываю. "
                         f"Скажите «заказ: …», чтобы завести, или «доход», чтобы записать {money(amount)} как обычный доход.", [])
        return record_order_payment(o.id if hasattr(o, "id") else o["id"], amount, channel, pay_date)
    if re.match(r"^\s*(?:это\s+)?(доход|обычный\s+доход)\s*[.!]*\s*$", text, re.I):
        try:
            tx = _finance.add_transaction(amount, "income", None, (q or "доход"), source=channel, date=pay_date)
        except _finance.FinanceError as e:
            return Reply(f"Не записал: {e}", [], "rules")
        s = _finance.summary(1)
        return Reply(say("income", amount=money(tx.amount), category=tx.category, balance=money(s["total_balance"])), ["add_income"])
    if NO_RX.match(text):
        return Reply("Ок, не записываю.", [])
    # «это заказ кот прод» / «заказ кот прод» / голое имя заказа — платёж к нему.
    # Раньше такое падало мимо всех веток: слот снимался, а 10к терялись (жалоба с «Кот прод»).
    name = None
    m = re.search(r"заказ\s*[:\-—]?\s*(.+)", text, re.I)
    if m:
        name = m.group(1).strip(" .!?«»\"'")
    else:
        cand = text.strip(" .!?")
        if cand and len(cand.split()) <= 6:
            from core.services import orders as _ox
            if _ox.find_order(cand):
                name = cand
    if name:
        from core.services import orders
        o = orders.find_order(name)
        if o is None:
            return Reply(f"Заказ «{name}» не нашёл, сэр — не выдумываю. "
                         f"Скажите «заказ: …», чтобы завести, или «доход», чтобы записать {money(amount)} как обычный доход.", [])
        return record_order_payment(o.id if hasattr(o, "id") else o["id"], amount, channel, pay_date)
    return None   # заговорили о другом — вопрос уже снят (consume), ничего не пишем


def orders_rule(text: str, low: str, channel: str) -> Reply | None:
    """Заказы, помодоро, цели и фин-отчёты без модели — мгновенно."""
    from core.services import goals, orders
    from core.tools import registry

    t = text
    r = people_rule(t, low, channel)
    if r:
        return r
    if LATE_Q_RX.match(t):
        from core.services import pulse
        return Reply(pulse.late_text(), ["late_payments"])
    if ORDERS_Q_RX.match(t):
        return Reply(orders.summary_text(), ["list_orders"])
    if GOALS_Q_RX.match(t):
        return Reply(goals.goals_text(), ["list_goals"])
    m = FIN_TECH_RX.match(t)
    if m:
        kind = "buckets" if m.group(1) else "compare" if m.group(2) else "runway" if m.group(3) else "payments"
        return Reply(registry.finance_report(kind), ["finance_report"])
    if POMO_STOP_RX.match(t):
        return Reply(registry.pomodoro("stop", _channel=channel), ["pomodoro"])
    if POMO_Q_RX.match(t):
        return Reply(registry.pomodoro("status", _channel=channel), ["pomodoro"])
    m = POMO_BREAK_RX.match(t)
    if m:
        return Reply(registry.pomodoro("break", minutes=int(m.group(1)) if m.group(1) else None, _channel=channel), ["pomodoro"])
    m = POMO_RX.match(t)
    if m and re.search(r"таймер|помодоро|помидор|фокус", low):
        mins = int(m.group(1)) if m.group(1) else None
        q = (m.group(2) or "").strip(" «»\"'")
        if q and not orders.find_order(q):
            return Reply(f"Заказ «{q}» не нашёл, сэр. Запустил бы без привязки — скажите «таймер» без названия, или добавьте заказ: «заказ: {q}».", [])
        return Reply(registry.pomodoro("start", query=q or None, minutes=mins, _channel=channel), ["pomodoro"])
    m = GOAL_RX.match(t)
    if m:
        from core.brain.dates import parse_amount as _pa
        from core.brain.dates import parse_datetime as _pd

        body = m.group(1).strip()
        amount, rest = _pa(body)
        dt, rest = _month_target(rest)
        if not dt:
            dt, rest = _pd(rest)
        title = re.sub(r"\s{2,}", " ", rest).strip(" ,.-—:;")
        if amount and title:
            g = goals.add_goal(title, amount, dt, source=channel)
            v = goals.goal_view(g)
            return Reply(f"Цель «{g.title}»: {money(g.target)}" + (f" к {g.due:%d.%m.%Y} — откладывать по {money(v['per_month'])} в месяц" if v["per_month"] else "")
                         + ". Пополнять: «отложил 10к — " + g.title.lower() + "».", ["add_goal"])
    m = SAVE_RX.match(t)
    if m:
        from core.brain.dates import parse_amount as _pa

        amount, rest = _pa(m.group(2))
        q = re.sub(r"^\s*(?:в|на|—|-)\s*", "", rest).strip(" ,.-—:;«»\"'")
        if amount and q:
            g = goals.find_goal(q)
            if not g:
                return Reply(f"Цель «{q}» не нашёл, сэр. Есть: " + (", ".join(x["title"] for x in goals.list_goals()) or "пока ни одной — «цель: подушка 300к»") + ".", [])
            r_ = goals.put_to_goal(g.id, -amount if m.group(1).lower().startswith(("взял", "снял", "достал")) else amount, source=channel)
            v = r_["goal"]
            return Reply(f"«{v['title']}»: {money(v['saved'])} из {money(v['target'])} ({v['pct'] * 100:.0f}%)." + (" Цель достигнута 🎉" if r_["reached"] else ""), ["save_to_goal"])
    m = PAYMENT_RX.match(t)
    if m:
        from core.brain.agent import _too_long_for_rules as _too_long
        from core.brain.dates import parse_amount as _pa
        from core.brain.dates import parse_datetime as _pd

        if not _too_long(t):
            amount, rest = _pa(t)
            q = re.sub(r"^\s*(?:пришл[аои]|приш[её]л|получил\w*|перевели|заплатил\w*|оплатил\w*)\s*(?:аванс|оплат\w*|предоплат\w*|деньги)?\s*(?:за|от|по)?\s*", "", rest, flags=re.I).strip(" ,.-—:;«»\"'")
            q = re.sub(r"\s*(?:за|от|по)\s+(?:заказ\w*|ролик\w*|проект\w*)?\s*$", "", q).strip()
            when, q2 = _pd(q)   # «…за ролик 20 августа» — деньги пришли задним числом
            pay_date = None
            if when and q2.strip() != q.strip():
                if when > datetime.now():   # парсер дат смотрит вперёд; оплата в будущем — это прошлый год
                    when = when.replace(year=when.year - 1)
                pay_date = when.replace(hour=12, minute=0)
                q = q2.strip(" ,.-—:;«»\"'")
            if amount:
                o = orders.find_order(q) if q else (orders.list_orders()[0] if len(orders.list_orders()) == 1 else None)
                if o and hasattr(o, "id"):
                    oid = o.id
                elif isinstance(o, dict):
                    oid = o["id"]
                else:
                    oid = None
                if amount >= CONFIRM_AMOUNT:
                    return None   # крупная сумма — через модель с подтверждением
                # Батч 1: входящие «пришёл аванс 10к за ролик» / «получил 15000» — ВСЕГДА спрашиваем
                # «оплата по заказу [кандидат] или обычный доход?», заказ не выдумываем.
                # Исходящие «заплатил/оплатил» — как раньше (трата, заказ только если точно найден).
                if not re.match(r"^\s*(?:пришл[аои]|приш[её]л|получил\w*|перевели)", t, re.I):
                    if oid:
                        orders.add_payment(oid, amount, source=channel, date=pay_date)
                        v = orders.order_view(orders.get_order(oid))
                        return Reply(f"Оплата {money(amount)} по «{v['title']}» — в доходах" + (f" за {pay_date:%d.%m}" if pay_date else "") + "." + (f" Осталось {money(v['left'])}." if v["left"] > 0 else " Заказ закрыт как оплаченный ✓"), ["order_payment"])
                    return None
                _pending_set(channel, "pay_ask|" + json.dumps(
                    {"amount": amount, "q": q, "oid": oid,
                     "date": pay_date.isoformat() if pay_date else None}, ensure_ascii=False))
                if oid:
                    try:
                        v = orders.order_view(orders.get_order(oid))
                        title = v["title"]
                    except Exception:
                        title = q or "заказ"
                    return Reply(f"«{t.strip()}» — это оплата по заказу «{title}» ({money(amount)}) или обычный доход? "
                                 f"Ответьте «заказ» или «доход», сэр.", ["clarify"],
                                 buttons=[("📦 " + title[:24], "заказ"), ("💰 Доход", "доход"), ("❌ Нет", "нет")])
                if q:
                    return Reply(f"Заказа «{q}» не нашёл, сэр — не выдумываю. "
                                 f"Записать {money(amount)} как обычный доход? Ответьте «доход» или «нет».", ["clarify"],
                                 buttons=[("💰 Доход", "доход"), ("❌ Нет", "нет")])
                return Reply(f"«{t.strip()}» — это оплата по заказу или обычный доход? "
                             f"Ответьте «заказ» или «доход», сэр.", ["clarify"],
                             buttons=[("📦 Заказ", "заказ"), ("💰 Доход", "доход"), ("❌ Нет", "нет")])
    m = ORDER_RX.match(t)
    if m:
        from core.brain.agent import _too_long_for_rules as _too_long
        from core.brain.dates import parse_amount as _pa
        from core.brain.dates import parse_datetime as _pd

        if not _too_long(t):
            body = m.group(1).strip()
            # «ролик для Пятёрочки, 25к, до пятницы» — клиент («для X» с заглавной), сумма и дата вырезаются, остаток — название
            client = None
            mc = re.search(r"(?:^|\s)(?:для|от|клиент[:\s])\s*([А-ЯЁA-Z][\w\-]*(?:\s+[А-ЯЁA-Z][\w\-]*)?)", body)
            if mc:
                client = mc.group(1); body = (body[:mc.start()] + " " + body[mc.end():]).strip()
            amount, rest = _pa(body)
            dt, rest = _pd(rest)
            title = re.sub(r"\s{2,}", " ", rest).strip(" ,.-—:;")
            title = title[0].upper() + title[1:] if title else title
            if title:
                o = orders.add_order(title, amount or 0, client, dt, source=channel)
                v = orders.order_view(o)
                return Reply(f"Заказ #{o.id} «{o.title}»" + (f" · {v['client']}" if v["client"] else "") + (f" · {money(o.price)}" if o.price else " · сумму уточним")
                             + (f" · до {o.deadline:%d.%m}" if o.deadline else "") + ". В работе. Скажите «таймер на " + o.title.split()[0].lower() + "», когда сядете за него.", ["add_order"])
    return None


RULES = [orders_rule]
