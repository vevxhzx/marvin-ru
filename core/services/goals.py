"""Финансовые техники поверх транзакций: конверты-накопления, 50/30/20, сравнение месяцев, годовые расходы,
сверка предстоящих платежей с балансом, «до дохода хватит на N дней».

Всё считается из уже существующих данных (транзакции, категории, регулярные) + одна новая таблица Goal.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from sqlmodel import select

from ..db import Category, Goal, Recurring, Transaction, log_action, remember, session
from . import finance
from .finance import money

log = logging.getLogger("jarvis.goals")

BUCKETS = ("need", "want", "save")
BUCKET_LABEL = {"need": "обязательное", "want": "хотелки", "save": "накопления", "": "не размечено"}
BUCKET_NORM = {"need": 0.5, "want": 0.3, "save": 0.2}


# ---------------------------------------------------------------- конверты / цели
def add_goal(title: str, target: float, due: datetime | None = None, saved: float = 0, icon: str = "🎯", source: str = "web") -> Goal:
    title = (title or "").strip(" .«»\"'")
    if not title:
        raise finance.FinanceError("Нужно название цели")
    target = float(target)
    if target <= 0:
        raise finance.FinanceError("Сумма цели должна быть больше нуля")
    with session() as s:
        g = Goal(title=title[0].upper() + title[1:], target=target, due=due, saved=max(0.0, float(saved or 0)), icon=icon or "🎯")
        s.add(g); s.commit(); s.refresh(g)
        remember(s, "finance", f"Цель: «{g.title}» {money(target)}" + (f" к {due:%d.%m.%Y}" if due else ""), "goal", g.id, source)
        log_action(s, "add_goal", "goal", g.id, g.title, source)
        s.commit()
        return g


def list_goals(include_closed: bool = False) -> list[dict]:
    with session() as s:
        rows = list(s.exec(select(Goal).order_by(Goal.closed, Goal.due.is_(None), Goal.due)))
    return [goal_view(g) for g in rows if include_closed or not g.closed]


def goal_view(g: Goal) -> dict:
    d = g.model_dump()
    left = max(0.0, g.target - g.saved)
    d["left"] = left
    d["pct"] = min(1.0, g.saved / g.target) if g.target else 0
    months = None
    if g.due and left > 0:
        months = max(1, (g.due.year - datetime.now().year) * 12 + g.due.month - datetime.now().month + (1 if g.due.day >= datetime.now().day else 0))
    d["months_left"] = months
    d["per_month"] = round(left / months) if months else None
    d["days_left"] = (g.due.date() - datetime.now().date()).days if g.due else None
    return d


def find_goal(query: str | int) -> Goal | None:
    with session() as s:
        if isinstance(query, int) or str(query).strip().lstrip("#").isdigit():
            return s.get(Goal, int(str(query).strip().lstrip("#")))
        q = str(query).strip(" «»\"'").lower()
        rows = list(s.exec(select(Goal).where(Goal.closed == False)))  # noqa: E712
        from .match import same
        for g in rows:
            if g.title.lower() == q:
                return g
        for g in rows:
            if q in g.title.lower() or any(same(w, q) for w in g.title.lower().split()):
                return g
        return None


def put_to_goal(goal_id: int, amount: float, from_account: str | None = None, source: str = "web", record_tx: bool = True) -> dict:
    """Отложить в конверт. По умолчанию — это расход с основного счёта в категорию «Накопления» (деньги ушли из
    «свободных»), привязанный к цели; так баланс и «безопасно тратить» честные. record_tx=False — просто отметить."""
    amount = float(amount)
    if amount == 0:
        raise finance.FinanceError("Сумма не может быть нулём")
    with session() as s:
        g = s.get(Goal, goal_id)
        if not g:
            raise finance.FinanceError("Цель не найдена")
        g.saved = max(0.0, g.saved + amount)
        reached = g.saved >= g.target - 0.5
        if reached and not g.closed:
            g.closed = True
        s.add(g); s.commit(); s.refresh(g)
        title = g.title
    if record_tx:
        _ensure_save_category()
        finance.add_transaction(abs(amount), "expense" if amount > 0 else "income", "Накопления",
                                f"{'в' if amount > 0 else 'из'} «{title}»", from_account, source=source, goal_id=goal_id)
    return {"goal": goal_view(g), "reached": reached}


def update_goal(goal_id: int, **fields) -> Goal | None:
    with session() as s:
        g = s.get(Goal, goal_id)
        if not g:
            return None
        for k, v in fields.items():
            if k in ("title", "icon") and v:
                setattr(g, k, str(v).strip())
            elif k in ("target", "saved") and v is not None:
                setattr(g, k, max(0.0, float(v)))
            elif k == "due":
                g.due = v
            elif k == "closed" and v is not None:
                g.closed = bool(v)
        s.add(g); s.commit(); s.refresh(g)
        return g


def delete_goal(goal_id: int) -> bool:
    with session() as s:
        g = s.get(Goal, goal_id)
        if not g:
            return False
        for t in s.exec(select(Transaction).where(Transaction.goal_id == goal_id)).all():
            t.goal_id = None; s.add(t)
        s.delete(g); s.commit()
        return True


def _ensure_save_category() -> None:
    with session() as s:
        if not s.exec(select(Category).where(Category.name == "Накопления")).first():
            s.add(Category(name="Накопления", kind="expense", icon="🏦", keywords="накопления,отложил,подушка,копилка", bucket="save", custom=False))
            s.commit()


def goals_text() -> str:
    gs = list_goals()
    if not gs:
        return "Целей пока нет. Скажите: «цель: подушка 300к к марту» или «копим на камеру 120 тысяч»."
    lines = ["**Цели**"]
    for g in gs:
        bar = "▰" * int(g["pct"] * 10) + "▱" * (10 - int(g["pct"] * 10))
        tail = f" · по {money(g['per_month'])}/мес, чтобы успеть к {g['due']:%d.%m}" if g["per_month"] else (f" · к {g['due']:%d.%m}" if g["due"] else "")
        lines.append(f"{g['icon']} {g['title']}: {bar} {g['pct'] * 100:.0f}% — {money(g['saved'])} из {money(g['target'])}{tail}")
    return "\n".join(lines)


# ---------------------------------------------------------------- 50 / 30 / 20
def buckets_report(days: int | None = None) -> dict:
    """Доли обязательного / хотелок / накоплений от дохода за месяц (или за N дней) против нормы 50/30/20."""
    now = datetime.now()
    since = now - timedelta(days=days) if days else now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    with session() as s:
        cats = {c.name: c for c in s.exec(select(Category))}
        txs = s.exec(select(Transaction).where(Transaction.date >= since, Transaction.kind.in_(("expense", "income")))).all()
    income = sum(t.amount for t in txs if t.kind == "income")
    sums = {"need": 0.0, "want": 0.0, "save": 0.0, "": 0.0}
    for t in txs:
        if t.kind != "expense":
            continue
        c = cats.get(t.category or "")
        b = (c.bucket if c and c.bucket in BUCKETS else "")
        if c and c.name == "Долги":
            b = "need"
        sums[b] += t.amount
    # переводы в конверты без транзакции-расхода уже учтены как расход «Накопления» (bucket save)
    spent = sum(sums.values())
    base = income if income > 0 else spent
    out = {"since": since.isoformat(), "income": income, "spent": spent, "base": base, "buckets": []}
    for b in BUCKETS:
        share = sums[b] / base if base else 0
        out["buckets"].append({"bucket": b, "label": BUCKET_LABEL[b], "amount": sums[b], "share": share, "norm": BUCKET_NORM[b],
                               "status": "over" if share > BUCKET_NORM[b] * 1.15 and b != "save" else "low" if b == "save" and share < BUCKET_NORM[b] * 0.5 else "ok"})
    out["unassigned"] = sums[""]
    out["unassigned_cats"] = sorted({t.category or "Другое" for t in txs if t.kind == "expense" and not (cats.get(t.category or "") and cats[t.category or ""].bucket)})
    return out


def buckets_text() -> str:
    r = buckets_report()
    if not r["base"]:
        return "За этот месяц пока нет операций — считать нечего."
    who = "от дохода" if r["income"] > 0 else "от трат (доходов в этом месяце ещё нет)"
    lines = [f"**50 / 30 / 20** за месяц, {who}:"]
    for b in r["buckets"]:
        mark = " ⚠️" if b["status"] == "over" else " ↓" if b["status"] == "low" else ""
        lines.append(f"• {b['label']}: **{b['share'] * 100:.0f}%** ({money(b['amount'])}) — норма {b['norm'] * 100:.0f}%{mark}")
    if r["unassigned"]:
        lines.append(f"Не размечено: {money(r['unassigned'])} ({', '.join(r['unassigned_cats'][:4])}) — отметьте корзину в Финансы → категории.")
    need = next(b for b in r["buckets"] if b["bucket"] == "need")
    if need["share"] > 0.7:
        lines.append("Обязательные съедают больше 70% — подушка при таком раскладе не появится; либо резать фикс, либо поднимать доход.")
    return "\n".join(lines)


# ---------------------------------------------------------------- месяц к месяцу
def month_compare() -> dict:
    now = datetime.now()
    m0 = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    p0 = m0 - relativedelta(months=1)
    same_day_prev = min(now.day, ((m0 - timedelta(days=1)).day))
    p_same = p0.replace(day=same_day_prev, hour=now.hour, minute=now.minute)
    with session() as s:
        cur = s.exec(select(Transaction).where(Transaction.date >= m0)).all()
        prev = s.exec(select(Transaction).where(Transaction.date >= p0, Transaction.date < m0)).all()
    def by_cat(rows, until=None):
        d: dict[str, float] = {}
        for t in rows:
            if t.kind == "expense" and (until is None or t.date <= until):
                d[t.category or "Другое"] = d.get(t.category or "Другое", 0) + t.amount
        return d
    c_cat, p_cat_full, p_cat_same = by_cat(cur), by_cat(prev), by_cat(prev, p_same)
    cats = sorted(set(c_cat) | set(p_cat_same), key=lambda k: -(c_cat.get(k, 0) + p_cat_same.get(k, 0)))
    rows = []
    for k in cats:
        a, b = c_cat.get(k, 0.0), p_cat_same.get(k, 0.0)
        rows.append({"category": k, "current": a, "prev_same": b, "prev_full": p_cat_full.get(k, 0.0),
                     "delta": a - b, "delta_pct": ((a - b) / b) if b else None})
    cur_exp = [t for t in cur if t.kind == "expense"]
    prev_exp = [t for t in prev if t.kind == "expense"]
    return {"month": m0.strftime("%Y-%m"), "prev": p0.strftime("%Y-%m"), "day": now.day,
            "spent": sum(t.amount for t in cur_exp), "spent_prev_same": sum(t.amount for t in prev_exp if t.date <= p_same),
            "spent_prev_full": sum(t.amount for t in prev_exp),
            "earned": sum(t.amount for t in cur if t.kind == "income"), "earned_prev": sum(t.amount for t in prev if t.kind == "income"),
            "avg_check": (sum(t.amount for t in cur_exp) / len(cur_exp)) if cur_exp else 0,
            "avg_check_prev": (sum(t.amount for t in prev_exp) / len(prev_exp)) if prev_exp else 0,
            "categories": rows[:10]}


def month_compare_text() -> str:
    r = month_compare()
    if not r["spent"] and not r["spent_prev_same"]:
        return "Сравнивать пока нечего — за этот и прошлый месяц нет трат."
    d = r["spent"] - r["spent_prev_same"]
    sign = "больше" if d > 0 else "меньше"
    lines = [f"**Этот месяц vs прошлый** (на {r['day']}-е число): потрачено **{money(r['spent'])}** — на {money(abs(d))} {sign}, чем в прошлом к этому дню ({money(r['spent_prev_same'])}; весь прошлый месяц — {money(r['spent_prev_full'])})."]
    grown = [c for c in r["categories"] if c["delta"] > 0 and (c["delta_pct"] is None or c["delta_pct"] > 0.25) and c["delta"] >= 500][:3]
    if grown:
        lines.append("Выросло: " + "; ".join(f"{c['category']} +{money(c['delta'])}" + (f" ({c['delta_pct'] * 100:+.0f}%)" if c["delta_pct"] is not None else " (новое)") for c in grown) + ".")
    fell = [c for c in r["categories"] if c["delta"] < -500][:2]
    if fell:
        lines.append("Меньше: " + "; ".join(f"{c['category']} {money(c['delta'])}" for c in fell) + ".")
    if r["avg_check"] and r["avg_check_prev"]:
        lines.append(f"Средний чек {money(r['avg_check'])} (было {money(r['avg_check_prev'])}).")
    return "\n".join(lines)


# ---------------------------------------------------------------- годовые / нерегулярные расходы
def annual_reserve() -> dict:
    """Регулярные yearly + крупные разовые траты за год, которые повторяются раз в год (страховка, налоги, ТО):
    сколько откладывать в месяц, чтобы они не были «внезапными»."""
    rec = [r for r in finance.list_recurring() if r.kind == "expense" and r.period == "yearly"]
    items = [{"title": r.title, "amount": r.amount, "next": r.next_date, "months": max(1, (r.next_date.year - datetime.now().year) * 12 + r.next_date.month - datetime.now().month)} for r in rec]
    total = sum(i["amount"] for i in items)
    per_month = round(sum(i["amount"] / 12 for i in items))
    return {"items": items, "total_year": total, "per_month": per_month}


# ---------------------------------------------------------------- сверка платежей с балансом, дней до дохода
def payment_check(days: int = 7) -> dict:
    """Ближайшие обязательные платежи против того, что есть на счетах (без конвертов и долговых счетов)."""
    now = datetime.now()
    balance = sum(a.balance for a in finance.list_accounts() if a.kind != "debt_only")
    upcoming = [r for r in finance.upcoming_payments(days) if r.kind == "expense"]
    need = sum(r.amount for r in upcoming)
    incomes = [r for r in finance.list_recurring() if r.kind == "income" and r.next_date <= now + timedelta(days=days)]
    short = max(0.0, need - balance - sum(r.amount for r in incomes)) if upcoming else 0.0
    return {"balance": balance, "need": need, "short": short, "days": days,
            "payments": [{"title": r.title, "amount": r.amount, "date": r.next_date.isoformat()} for r in upcoming],
            "incoming": [{"title": r.title, "amount": r.amount, "date": r.next_date.isoformat()} for r in incomes]}


def payment_alert() -> str | None:
    """Планировщик, раз в день: если на ближайшие платежи не хватает — сказать один раз в день."""
    from ..db import get_setting, set_setting
    r = payment_check(5)
    if r["short"] <= 0:
        return None
    key = f"pay_short:{datetime.now():%Y-%m-%d}"
    if get_setting(key):
        return None
    set_setting(key, "1")
    first = min(r["payments"], key=lambda p: p["date"])
    return (f"⚠️ В ближайшие 5 дней платежей на **{money(r['need'])}** (первый — «{first['title']}» {datetime.fromisoformat(first['date']):%d.%m}), "
            f"а на счетах **{money(r['balance'])}**. Не хватает {money(r['short'])}" + (" даже с учётом ожидаемого дохода." if r["incoming"] else ".")
            + " Пополнить счёт или перенести платёж?")


def runway() -> dict:
    """«До дохода хватит на N дней» при текущем среднем расходе, после резерва на обязательные платежи."""
    st = finance.safe_to_spend()
    f = _per_day_30()
    free = st["free"]
    days = int(free / f) if f > 0 else None
    return {"free": free, "per_day_avg": f, "days_left_to_income": st["days_left"], "runway_days": days,
            "ok": days is None or days >= st["days_left"], "safe_per_day": st["per_day"]}


def _per_day_30() -> float:
    txs = [t for t in finance.list_transactions(30, 100_000) if t.kind == "expense" and "(авто)" not in (t.note or "") and t.category not in ("Долги", "Накопления")]
    if not txs:
        return 0.0
    first = min(t.date for t in txs)
    span = max(7, (datetime.now() - first).days)
    return sum(t.amount for t in txs) / span
