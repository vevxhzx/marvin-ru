"""Рутины = повторяющиеся события календаря (тренировка по пн/ср/пт, «созвон с мамой» по воскресеньям).

Новой таблицы нет: рутина — это Event с repeat, а «сделано в этот раз» — уже существующие done_dates.
Здесь только выводы: серия (сколько раз подряд не пропускал), пропуски подряд, и один повод для proactive —
«тренировку пропустил два раза подряд» — без нотаций, один раз, не чаще раза в неделю на рутину.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlmodel import select

from ..db import Event, session
from . import calendar
from .match import score

LOOKBACK_DAYS = 60


def _routines() -> list[Event]:
    with session() as s:
        return [e for e in s.exec(select(Event).where(Event.repeat != "")).all() if e.repeat in ("daily", "weekly")]


def stats(ev: Event, now: datetime | None = None) -> dict:
    """{title, streak, missed_in_row, done_30, total_30, last_done}. Считаются только прошедшие разы (сегодняшний — если время уже прошло)."""
    now = now or datetime.now()
    since = now - timedelta(days=LOOKBACK_DAYS)
    occ = [o for o in calendar.expand([ev], since, now) if o.start <= now]
    occ.sort(key=lambda o: o.start)
    done_flags = [calendar.is_done(ev, o.start) for o in occ]
    streak = 0
    for f in reversed(done_flags):
        if not f:
            break
        streak += 1
    missed = 0
    for f in reversed(done_flags):
        if f:
            break
        missed += 1
    m30 = [(o, f) for o, f in zip(occ, done_flags) if o.start >= now - timedelta(days=30)]
    last_done = next((o.start for o, f in reversed(list(zip(occ, done_flags))) if f), None)
    return {"id": ev.id, "title": ev.title, "streak": streak, "missed_in_row": missed,
            "done_30": sum(1 for _, f in m30 if f), "total_30": len(m30), "last_done": last_done}


def all_stats(now: datetime | None = None) -> list[dict]:
    return [stats(e, now) for e in _routines()]


def find(query: str) -> Event | None:
    rows = _routines()
    best = max(((score(e.title, query), e) for e in rows), key=lambda x: x[0], default=(0, None))
    return best[1] if best[0] >= 0.5 else None


def text(query: str | None = None, now: datetime | None = None) -> str:
    if query:
        ev = find(query)
        if not ev:
            return f"Рутины «{query}» не вижу. Рутина — это повторяющееся событие: «тренировка по пн, ср, пт в 19:00»."
        st = stats(ev, now)
        return _line(st, full=True)
    rows = all_stats(now)
    if not rows:
        return "Повторяющихся дел в календаре нет. «Тренировка по пн, ср, пт в 19:00» — и я начну считать серию."
    return "Рутины:\n" + "\n".join("· " + _line(r) for r in rows)


def _line(st: dict, full: bool = False) -> str:
    if not st["total_30"]:
        return f"{st['title']} — ещё ни одного раза не было."
    s = f"{st['title']}: {st['done_30']} из {st['total_30']} за месяц"
    if st["streak"] >= 2:
        s += f", серия {st['streak']}"
    elif st["missed_in_row"] >= 2:
        s += f", пропущено {st['missed_in_row']} подряд"
    if full and st["last_done"]:
        s += f". Последний раз — {st['last_done']:%d.%m}"
    return s + "."


def nudges(now: datetime | None = None) -> list[dict]:
    """Поводы для proactive: рутина пропущена ≥2 раз подряд (и раньше держалась — было хоть 3 выполнения за месяц)."""
    out = []
    for st in all_stats(now):
        if st["missed_in_row"] >= 2 and st["done_30"] >= 3:
            out.append({"key": f"routine:{st['id']}:{st['missed_in_row']}", "title": st["title"], "missed": st["missed_in_row"],
                        "text": f"«{st['title']}» — {st['missed_in_row']} раза подряд мимо. Сломалась привычка или просто неделя такая?"})
    return out


ROUTINE_RX = re.compile(r"^\s*(?:(?:мои\s+)?рутины|(?:как\s+(?:у\s+меня\s+)?(?:дела\s+)?с|серия\s+по|стрик\s+по|сколько\s+раз\s+подряд)\s+(.+?))\s*\??\s*$", re.I)


def chat_rule(t: str) -> str | None:
    m = ROUTINE_RX.match(t or "")
    if not m:
        return None
    q = (m.group(1) or "").strip()
    if q and not find(q):
        return None   # «как дела с деньгами» — не про рутины, дальше по цепочке
    return text(q or None)
