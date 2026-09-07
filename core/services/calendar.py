"""Календарь и напоминания. Поддерживает повторяющиеся события (каждый день / пн-ср-пт / месяц / год)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from dateutil.relativedelta import relativedelta
from sqlmodel import select

from ..db import icontains, Event, log_action, remember, session

WEEKDAYS = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"]
WD_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
REPEATS = ("", "daily", "weekly", "monthly", "yearly")


def fmt_dt(dt: datetime) -> str:
    today = datetime.now().date()
    d = dt.date()
    if d == today:
        day = "сегодня"
    elif d == today + timedelta(days=1):
        day = "завтра"
    elif 0 < (d - today).days < 7:
        day = f"{WD_SHORT[d.weekday()]} {d.strftime('%d.%m')}"
    else:
        day = d.strftime("%d.%m.%Y")
    return f"{day} в {dt.strftime('%H:%M')}"


def fmt_repeat(ev: Event) -> str:
    if not ev.repeat:
        return ""
    if ev.repeat == "daily":
        return "каждый день"
    if ev.repeat == "weekly":
        days = [int(x) for x in ev.repeat_days.split(",") if x.strip().isdigit()] or [ev.start.weekday()]
        return "каждую неделю: " + ", ".join(WD_SHORT[d] for d in sorted(days))
    if ev.repeat == "monthly":
        return f"каждый месяц {ev.start.day}-го"
    if ev.repeat == "yearly":
        return f"каждый год {ev.start:%d.%m}"
    return ""


# ---------------------------------------------------------------- Google (push-only, не блокирует)
def _gcal_push(event_id: int) -> None:
    try:
        from . import gcal
        gcal.schedule_push(event_id)
    except Exception as e:  # pragma: no cover
        import logging
        logging.getLogger("assistant.calendar").warning("gcal push hook: %s", e)


def _gcal_remove(event_id: int, google_id: str | None) -> None:
    try:
        from . import gcal
        gcal.schedule_remove(event_id, google_id)
    except Exception as e:  # pragma: no cover
        import logging
        logging.getLogger("assistant.calendar").warning("gcal remove hook: %s", e)


# ---------------------------------------------------------------- повторы
def _occurrences(ev: Event, start: datetime, end: datetime) -> list[datetime]:
    """Все даты начала события в окне [start, end)."""
    if not ev.repeat:
        return [ev.start] if start <= ev.start < end else []
    skip = set(filter(None, (ev.skip_dates or "").split(",")))
    until = ev.repeat_until or (end + timedelta(days=1))
    out: list[datetime] = []
    dur_days = 0
    if ev.repeat == "daily":
        cur = ev.start
        if cur < start:
            cur = cur + timedelta(days=(start.date() - cur.date()).days)
            if cur < start:
                cur += timedelta(days=1)
        while cur < end and cur <= until:
            if cur >= ev.start and cur.date().isoformat() not in skip:
                out.append(cur)
            cur += timedelta(days=1)
    elif ev.repeat == "weekly":
        days = sorted({int(x) for x in (ev.repeat_days or "").split(",") if x.strip().isdigit()} or {ev.start.weekday()})
        day0 = max(start.date(), ev.start.date())
        cur = ev.start.replace(year=day0.year, month=day0.month, day=day0.day)
        while cur < end and cur <= until:
            if cur.weekday() in days and cur >= ev.start and cur >= start and cur.date().isoformat() not in skip:
                out.append(cur)
            cur += timedelta(days=1)
    elif ev.repeat == "monthly":
        cur = ev.start
        while cur < end and cur <= until:
            if cur >= start and cur.date().isoformat() not in skip:
                out.append(cur)
            nxt = cur + relativedelta(months=1)
            # 31-го → в коротком месяце последний день
            want = ev.start.day
            last = (nxt.replace(day=1) + relativedelta(months=1) - timedelta(days=1)).day
            cur = nxt.replace(day=min(want, last))
    elif ev.repeat == "yearly":
        cur = ev.start
        while cur < end and cur <= until:
            if cur >= start and cur.date().isoformat() not in skip:
                out.append(cur)
            cur = cur + relativedelta(years=1)
    return out


def _instance(ev: Event, when: datetime) -> Event:
    """Копия события, сдвинутая на конкретную дату повтора (для отображения)."""
    if when == ev.start:
        return ev
    dur = (ev.end - ev.start) if ev.end else timedelta(hours=1)
    inst = Event(**ev.model_dump())
    inst.start = when
    inst.end = when + dur
    object.__setattr__(inst, "_anchor", ev.start)   # исходная дата правила (нужна сайту при правке времени)
    return inst


def expand(events: list[Event], start: datetime, end: datetime) -> list[Event]:
    out: list[Event] = []
    for ev in events:
        for when in _occurrences(ev, start, end):
            out.append(_instance(ev, when))
    out.sort(key=lambda e: e.start)
    return out


# ---------------------------------------------------------------- CRUD
def add_event(title: str, start: datetime, duration_min: int = 60, location: str | None = None,
              notes: str | None = None, remind_minutes: int = 30, source: str = "tg",
              repeat: str = "", repeat_days: list[int] | None = None, repeat_until: datetime | None = None) -> Event:
    repeat = repeat if repeat in REPEATS else ""
    with session() as s:
        # защита от дублей: то же название в тот же час (сказал дважды / из TG и с сайта)
        dup = s.exec(select(Event).where(Event.start >= start - timedelta(minutes=59), Event.start <= start + timedelta(minutes=59))).all()
        for d in dup:
            if d.title.strip().lower() == title.strip().lower() and d.repeat == repeat:
                return d
        ev = Event(title=title, start=start, end=start + timedelta(minutes=duration_min),
                   location=location, notes=notes, remind_minutes=remind_minutes, source=source,
                   repeat=repeat, repeat_days=",".join(str(d) for d in sorted(set(repeat_days or []))) if repeat == "weekly" else "",
                   repeat_until=repeat_until)
        s.add(ev)
        s.commit()
        s.refresh(ev)
        rep = f" ({fmt_repeat(ev)})" if ev.repeat else ""
        remember(s, "event", f"Запланировано: «{title}» {fmt_dt(start)}{rep}", "event", ev.id, source)
        log_action(s, "add_event", "event", ev.id, title, source)
        s.commit()
    _gcal_push(ev.id)
    return ev


def update_event(event_id: int, **fields) -> Event | None:
    with session() as s:
        ev = s.get(Event, event_id)
        if not ev:
            return None
        dur = (ev.end - ev.start) if ev.end else timedelta(hours=1)
        if fields.get("title") is not None:
            ev.title = fields["title"].strip() or ev.title
        if fields.get("start") is not None:
            st = fields["start"]
            ev.start = st if isinstance(st, datetime) else datetime.fromisoformat(str(st))
            ev.reminded = False
        if fields.get("duration_min") is not None:
            dur = timedelta(minutes=int(fields["duration_min"]))
        ev.end = ev.start + dur
        for k in ("location", "notes"):
            if k in fields:
                setattr(ev, k, (fields[k] or "").strip() or None)
        if fields.get("remind_minutes") is not None:
            ev.remind_minutes = int(fields["remind_minutes"]); ev.reminded = False
        if "repeat" in fields:
            ev.repeat = fields["repeat"] if fields["repeat"] in REPEATS else ""
        if "repeat_days" in fields:
            days = fields["repeat_days"] or []
            ev.repeat_days = ",".join(str(int(d)) for d in sorted(set(days))) if ev.repeat == "weekly" else ""
        if "repeat_until" in fields:
            ru = fields["repeat_until"]
            ev.repeat_until = (ru if isinstance(ru, datetime) else datetime.fromisoformat(str(ru))) if ru else None
        s.add(ev)
        remember(s, "event", f"Изменено: «{ev.title}» {fmt_dt(ev.start)}", "event", ev.id)
        s.commit(); s.refresh(ev)
    _gcal_push(ev.id)
    return ev


def move_event(query: str | int, new_start: datetime) -> Event | None:
    ev = find_event(query)
    if not ev:
        return None
    # для повторяющегося — переносим всё правило (сохраняя время недели)
    return update_event(ev.id, start=new_start)


def skip_occurrence(event_id: int, date: datetime) -> Event | None:
    """Пропустить один повтор («сегодня тренировки не будет»)."""
    with session() as s:
        ev = s.get(Event, event_id)
        if not ev or not ev.repeat:
            return ev
        dates = set(filter(None, (ev.skip_dates or "").split(",")))
        dates.add(date.date().isoformat())
        ev.skip_dates = ",".join(sorted(dates))
        s.add(ev); s.commit(); s.refresh(ev)
    _gcal_push(ev.id)
    return ev


def list_events(start: datetime | None = None, end: datetime | None = None, limit: int = 20) -> list[Event]:
    start = start or datetime.now().replace(hour=0, minute=0, second=0)
    end = end or (start + timedelta(days=60))
    with session() as s:
        single = list(s.exec(select(Event).where(Event.repeat == "", Event.start >= start, Event.start < end).order_by(Event.start)))
        rep = list(s.exec(select(Event).where(Event.repeat != "", Event.start < end)))
    out = single + expand(rep, start, end)
    out.sort(key=lambda e: e.start)
    return out[:limit]


def events_today() -> list[Event]:
    d0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return list_events(d0, d0 + timedelta(days=1), limit=100)


def delete_event(event_id: int) -> bool:
    with session() as s:
        ev = s.get(Event, event_id)
        if not ev:
            return False
        remember(s, "event", f"Отменено: «{ev.title}» {fmt_dt(ev.start)}", "event", ev.id)
        gid = ev.google_id
        s.delete(ev)
        s.commit()
    _gcal_remove(event_id, gid)
    return True


def find_events(query: str) -> list[Event]:
    with session() as s:
        return list(s.exec(select(Event).where(icontains(Event.title, query)).order_by(Event.start)))


def find_event(query: str | int) -> Event | None:
    """По id или части названия — ближайшее будущее, иначе последнее."""
    with session() as s:
        if isinstance(query, int) or str(query).isdigit():
            return s.get(Event, int(query))
        evs = []
        for q in stems(query):
            evs = list(s.exec(select(Event).where(icontains(Event.title, q)).order_by(Event.start)))
            if evs:
                break
        if not evs:
            # «встречу с ваней» → «Встреча с Ваней»: по словам, без падежей
            from .match import score
            recent = list(s.exec(select(Event).where(Event.start >= datetime.now() - timedelta(days=60)).order_by(Event.start)))
            scored = [(score(e.title, str(query)), e) for e in recent]
            top = max((sc for sc, _ in scored), default=0)
            if top >= 0.66:
                evs = [e for sc, e in scored if sc >= top]
    if not evs:
        return None
    now = datetime.now()
    exact = [e for e in evs if e.title.strip().lower() == str(query).strip().lower()]
    pool = exact or evs
    future = [e for e in pool if e.repeat or e.start >= now - timedelta(hours=1)]
    return future[0] if future else pool[-1]


def stems(query: str) -> list[str]:
    """«тренировки» → [«тренировки», «тренировк», «трениров»] — грубое склонение без словаря."""
    q = str(query).strip().lower()
    out = [q]
    words = q.split()
    if len(words) == 1 and len(q) >= 4:
        out.append(q[:-1])
        if len(q) > 5:
            out.append(q[:-2])
    elif len(words) > 1:
        out.append(" ".join(w[:-1] if len(w) >= 4 else w for w in words))
        out.append(" ".join(w[:-2] if len(w) > 5 else w for w in words))
    return out


def due_reminders() -> list[Event]:
    """События (включая повторы), для которых пора отправить напоминание."""
    now = datetime.now()
    due: list[Event] = []
    with session() as s:
        evs = s.exec(select(Event).where(Event.reminded == False, Event.repeat == "", Event.start > now - timedelta(minutes=5))).all()  # noqa: E712
        for e in evs:
            if e.start - timedelta(minutes=e.remind_minutes) <= now:
                e.reminded = True
                s.add(e)
                due.append(e)
        # повторы: смотрим ближайшее вхождение в окне
        for e in s.exec(select(Event).where(Event.repeat != "")).all():
            occ = _occurrences(e, now - timedelta(minutes=5), now + timedelta(days=2))
            for when in occ:
                key = when.strftime("%Y-%m-%dT%H:%M")
                if when - timedelta(minutes=e.remind_minutes) <= now and e.reminded_for != key and when > now - timedelta(minutes=5):
                    e.reminded_for = key
                    s.add(e)
                    due.append(_instance(e, when))
                    break
        s.commit()
    return due
