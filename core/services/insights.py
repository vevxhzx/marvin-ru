"""Аналитика и «умные» подсказки: прогноз кассы, подписки, стрик, дни рождения, дайджест недели, связи заметок.

Всё считается локально по базе. LLM (локальная) — только для еженедельного дайджеста мыслей.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlmodel import select

from ..db import Memory, Note, Task, Transaction, get_setting, session, set_setting
from . import calendar, finance
from .finance import money

log = logging.getLogger("assistant.insights")


# ---------------------------------------------------------------- прогноз кассы
def cash_forecast(days: int = 30) -> dict:
    """Баланс по дням на N дней вперёд: регулярные платежи/доходы + средние переменные траты в день."""
    now = datetime.now()
    accounts = finance.list_accounts()
    balance = sum(a.balance for a in accounts if a.kind != "debt_only")
    rec = finance.list_recurring()
    # средние переменные траты в день за 30 дней (без авто и долгов)
    txs = [t for t in finance.list_transactions(30, 100_000) if t.kind == "expense" and "(авто)" not in (t.note or "") and t.category != "Долги"]
    first = min((t.date for t in txs), default=now - timedelta(days=30))
    span = max(7, (now - first).days) if txs else 30
    per_day = sum(t.amount for t in txs) / span if txs else 0.0
    # события регулярных
    sched: dict[date, list[tuple[str, float]]] = defaultdict(list)
    for r in rec:
        d = r.next_date
        for _ in range(6):
            if d.date() > (now + timedelta(days=days)).date():
                break
            sched[d.date()].append((r.title, r.amount if r.kind == "income" else -r.amount))
            d = finance._next_date(r.day, r.period, d)
    points, cur, low, low_day = [], balance, balance, now.date()
    for i in range(days + 1):
        d = (now + timedelta(days=i)).date()
        items = sched.get(d, [])
        if i > 0:
            cur -= per_day
            cur += sum(a for _, a in items)
        if cur < low:
            low, low_day = cur, d
        points.append({"date": d.isoformat(), "balance": round(cur), "events": [{"title": t, "amount": a} for t, a in items]})
    incomes = [r for r in rec if r.kind == "income"]
    next_income = min((r.next_date for r in incomes), default=None)
    days_to_income = (next_income.date() - now.date()).days if next_income else None
    # сколько можно тратить в день, чтобы к зарплате не уйти ниже нуля
    reserved = sum(r.amount for r in rec if r.kind == "expense" and next_income and r.next_date < next_income)
    safe_per_day = ((balance - reserved) / max(1, days_to_income)) if days_to_income else None
    return {"points": points, "per_day": round(per_day), "low": round(low), "low_date": low_day.isoformat(),
            "next_income": next_income.isoformat() if next_income else None, "days_to_income": days_to_income,
            "safe_per_day": round(safe_per_day) if safe_per_day is not None else None,
            "ok": low >= 0}


def cash_forecast_text() -> str:
    f = cash_forecast(30)
    parts = [f"Сейчас **{money(f['points'][0]['balance'])}**, тратите в среднем **{money(f['per_day'])}** в день."]
    if f["days_to_income"] is not None:
        parts.append(f"До ближайшего дохода {f['days_to_income']} дн. — безопасно тратить до **{money(f['safe_per_day'])}** в день.")
    if not f["ok"]:
        d = datetime.fromisoformat(f["low_date"])
        parts.append(f"⚠️ При текущем темпе **{d:%d.%m}** уйдёте в минус ({money(f['low'])}). Стоит притормозить.")
    else:
        parts.append(f"Минимум за месяц — {money(f['low'])}, в минус не уходите. Держитесь, сэр.")
    return " ".join(parts)


# ---------------------------------------------------------------- подписки: повторяющиеся списания
def detect_subscriptions() -> list[dict]:
    """Одинаковые суммы с той же заметкой/категорией раз в ~месяц, которых нет в регулярных."""
    txs = [t for t in finance.list_transactions(120, 100_000) if t.kind == "expense" and "(авто)" not in (t.note or "")]
    known = {(r.title or "").lower() for r in finance.list_recurring(active_only=False)}
    groups: dict[tuple, list[Transaction]] = defaultdict(list)
    for t in txs:
        key = (round(t.amount), re.sub(r"[^\w]+", " ", (t.note or t.category or "").lower()).strip()[:24])
        groups[key].append(t)
    out = []
    for (amount, name), items in groups.items():
        if len(items) < 2 or not name:
            continue
        ds = sorted(t.date for t in items)
        gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
        if not gaps or not all(24 <= g <= 37 for g in gaps):
            continue
        if any(name in k or k in name for k in known if k):
            continue
        out.append({"name": name, "amount": amount, "times": len(items), "last": ds[-1].isoformat(), "yearly": amount * 12,
                    "category": items[-1].category})
    out.sort(key=lambda x: -x["amount"])
    return out


# ---------------------------------------------------------------- стрик ведения
def streak() -> dict:
    """Сколько дней подряд что-то записывали (траты/задачи/заметки/события)."""
    with session() as s:
        days = {m.created_at.date() for m in s.exec(select(Memory).where(Memory.created_at >= datetime.now() - timedelta(days=400), Memory.channel != "system"))}
    today = date.today()
    cur, d = 0, today
    if today not in days:
        d = today - timedelta(days=1)   # сегодня ещё не записывали — стрик пока держится со вчера
    while d in days:
        cur += 1; d -= timedelta(days=1)
    best_saved = int(get_setting("streak_best", "0") or 0)
    if cur > best_saved:
        set_setting("streak_best", str(cur)); best_saved = cur
    return {"current": cur, "best": best_saved, "today_done": today in days,
            "days": sorted(x.isoformat() for x in days if x >= today - timedelta(days=371))}


def activity_heatmap(weeks: int = 26) -> list[dict]:
    """Количество записей по дням для тепловой карты."""
    since = datetime.now() - timedelta(weeks=weeks)
    with session() as s:
        rows = s.exec(select(Memory).where(Memory.created_at >= since, Memory.channel != "system")).all()
    counts: dict[str, int] = defaultdict(int)
    for m in rows:
        counts[m.created_at.date().isoformat()] += 1
    return [{"date": k, "count": v} for k, v in sorted(counts.items())]


# ---------------------------------------------------------------- дни рождения
BDAY_RX = re.compile(r"\b(др|день\s+рождени\w*|днюх\w*|birthday)\b", re.I)


def upcoming_birthdays(days: int = 7) -> list[dict]:
    """Ежегодные события с «др/день рождения» в названии в ближайшие N дней."""
    now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for e in calendar.list_events(now, now + timedelta(days=days + 1), limit=200):
        # только ежегодные: «др мамы каждый год 14 марта». Разовое «иду на др 12-го» — обычный план, не праздник
        if e.repeat == "yearly" and BDAY_RX.search(e.title):
            out.append({"id": e.id, "title": e.title, "date": e.start.isoformat(), "in_days": (e.start.date() - now.date()).days,
                        "who": re.sub(r"^\W*(др|день\s+рождения|днюха)\W*", "", e.title, flags=re.I).strip() or e.title})
    return out


# ---------------------------------------------------------------- связи между заметками
async def related_notes(note_id: int, limit: int = 3) -> list[dict]:
    """Похожие по смыслу заметки (эмбеддинги), исключая саму заметку."""
    from . import semantic
    with session() as s:
        n = s.get(Note, note_id)
    if not n:
        return []
    try:
        res = await semantic.search(n.title or n.text[:200], limit + 3)
    except Exception:
        return []
    items = [i for i in res["items"] if not (i.get("kind") == "note" and i.get("id") == note_id) and i.get("score", 0) >= 0.55]
    return items[:limit]


# ---------------------------------------------------------------- еженедельный дайджест мыслей
WEEKLY_PROMPT = """Ты — личный ассистент. Ниже заметки и ссылки человека за неделю, а также его незакрытые задачи.
Сделай короткий воскресный обзор по-русски, дружелюбно и с лёгкой иронией (обращение «сэр»), формат:

**Темы недели** — 2–3 главные темы одной строкой каждая.
**Стоит превратить в задачу** — 1–3 мысли, которые звучат как дело, но задачей не стали (цитируй кратко).
**Забросили** — 1–2 задачи, которые висят дольше всего (если есть).
**Одна мысль** — короткое наблюдение или мотивирующий подкол в конце.

Не выдумывай того, чего нет в данных. Если заметок мало — так и скажи, коротко."""


async def weekly_digest() -> str | None:
    from ..brain import llm
    since = datetime.now() - timedelta(days=7)
    with session() as s:
        notes = s.exec(select(Note).where(Note.created_at >= since).order_by(Note.created_at)).all()
        from ..db import Link
        links = s.exec(select(Link).where(Link.created_at >= since)).all()
        open_tasks = s.exec(select(Task).where(Task.done == False).order_by(Task.created_at)).all()  # noqa: E712
        done_week = s.exec(select(Task).where(Task.done == True, Task.done_at != None, Task.done_at >= since)).all()  # noqa: E711,E712
    if not notes and not links:
        return None
    data = ["ЗАМЕТКИ:"] + [f"- [{n.created_at:%a}] {n.title or ''}: {n.text[:200]}" for n in notes]
    data += ["ССЫЛКИ:"] + [f"- {l.title or l.url} ({', '.join(filter(None, [l.comment, l.tags]))})" for l in links[:15]]
    data += ["ОТКРЫТЫЕ ЗАДАЧИ (старые первыми):"] + [f"- {t.title} (с {t.created_at:%d.%m})" for t in open_tasks[:12]]
    data += [f"ВЫПОЛНЕНО ЗА НЕДЕЛЮ: {len(done_week)}"]
    if not await llm.ollama_available():
        # без LLM — простой вариант
        tags: dict[str, int] = defaultdict(int)
        for n in notes:
            for t in filter(None, n.tags.split(",")):
                tags[t] += 1
        top = ", ".join(k for k, _ in sorted(tags.items(), key=lambda kv: -kv[1])[:3]) or "без тегов"
        return (f"🗓 **Неделя в мыслях**: {len(notes)} заметок, {len(links)} ссылок, закрыто задач — {len(done_week)}.\n"
                f"Темы: {top}. Открытых задач: {len(open_tasks)}" + (f", самая старая — «{open_tasks[0].title}»." if open_tasks else "."))
    try:
        out = await llm.ollama_chat([{"role": "system", "content": WEEKLY_PROMPT}, {"role": "user", "content": "\n".join(data)}], temperature=0.5)
        txt = (out.get("content") or "").strip()
        return ("🗓 **Неделя в мыслях**\n" + txt) if txt else None
    except Exception as e:
        log.warning("weekly digest failed: %s", e)
        return None


# ---------------------------------------------------------------- лимиты: вечерний статус
def budget_alerts() -> list[str]:
    """Категории, где перешли 80% / 100% лимита (сообщаем один раз на порог в месяц)."""
    out = []
    month = datetime.now().strftime("%Y-%m")
    for b in finance.budgets():
        for thr, label in ((1.0, "over"), (0.8, "warn")):
            if b["pct"] >= thr:
                key = f"budget_alert:{month}:{b['id']}:{label}"
                if get_setting(key):
                    break
                set_setting(key, "1")
                if label == "over":
                    out.append(f"🚨 «{b['name']}»: лимит {money(b['budget'])} исчерпан — потрачено {money(b['spent'])}. Дальше только сила воли, сэр.")
                else:
                    out.append(f"⚠️ «{b['name']}»: {b['pct'] * 100:.0f}% лимита ({money(b['spent'])} из {money(b['budget'])}), а месяц прошёл на {b['pace'] * 100:.0f}%.")
                break
    return out


def subscriptions_nudge() -> str | None:
    """Раз в месяц: найденные подписки, о которых ассистент ещё не говорил."""
    subs = detect_subscriptions()
    if not subs:
        return None
    told = set(filter(None, (get_setting("subs_told", "") or "").split("|")))
    new = [s for s in subs if s["name"] not in told]
    if not new:
        return None
    set_setting("subs_told", "|".join(told | {s["name"] for s in new}))
    lines = ["🔁 **Похоже на подписки** (списываются каждый месяц, но в регулярных их нет):"]
    lines += [f"— {s['name']} · **{money(s['amount'])}**/мес ({s['times']} раз, ~{money(s['yearly'])} в год)" for s in new[:5]]
    lines.append("Скажите «регулярный <название> <сумма>» — добавлю в обязательные, или «отмени подписку» — напомню отменить.")
    return "\n".join(lines)


# ---------------------------------------------------------------- «протокол Чистый лист»
def archive_done_tasks(days: int = 30) -> int:
    """Убрать из выдачи выполненные задачи старше N дней (пометкой project='archive' — ничего не удаляем)."""
    cutoff = datetime.now() - timedelta(days=days)
    n = 0
    with session() as s:
        for t in s.exec(select(Task).where(Task.done == True, Task.done_at != None, Task.done_at < cutoff)).all():  # noqa: E711,E712
            if t.project != "archive":
                t.project = "archive"; s.add(t); n += 1
        s.commit()
    return n
