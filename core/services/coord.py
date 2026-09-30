"""Координация «задача ↔ встреча».

Если встреча привязана к задаче (`Event.task_id`), держим их синхронными:
- **время**: срок задачи = начало встречи (в обе стороны);
- **завершение**: закрыл задачу — закрылась и встреча, и наоборот.

Правки делаем прямыми записями в БД (не вызываем публичные update_*/set_done второй стороны),
поэтому рекурсии не бывает. Веб-API дополняет это каскадом по заказам (`/api/events/{id}/done`).
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlmodel import select

from ..db import Event, Task, session

log = logging.getLogger("jarvis.coord")

_EPS = 60  # секунды: меньше минуты разницы — уже «то же время», не дёргаем базу зря


def events_for_task(task_id: int) -> list[Event]:
    with session() as s:
        return list(s.exec(select(Event).where(Event.task_id == task_id)))


def _set_task_due(task_id: int, when: datetime) -> bool:
    with session() as s:
        t = s.get(Task, task_id)
        if not t:
            return False
        if t.due and abs((t.due - when).total_seconds()) < _EPS:
            return False
        t.due = when
        t.remind_stage = 0
        s.add(t)
        s.commit()
    return True


def _set_event_start(ids: list[int], when: datetime) -> bool:
    if not ids:
        return False
    changed = False
    with session() as s:
        for ev in s.exec(select(Event).where(Event.id.in_(ids))).all():
            if ev.start and abs((ev.start - when).total_seconds()) < _EPS:
                continue
            dur = (ev.end - ev.start) if ev.end else None
            ev.start = when
            if dur is not None:
                ev.end = when + dur
            ev.reminded = False
            s.add(ev)
            changed = True
        s.commit()
    return changed


def sync_from_event(event_id: int) -> None:
    """Встречу создали/перенесли — подтягиваем срок привязанной задачи."""
    try:
        with session() as s:
            ev = s.get(Event, event_id)
            if not ev or not ev.task_id or not ev.start:
                return
            tid, when = ev.task_id, ev.start
        _set_task_due(tid, when)
    except Exception as e:  # pragma: no cover
        log.warning("sync event→task: %s", e)


def sync_from_task(task_id: int) -> None:
    """У задачи поменяли срок — переносим привязанные встречи на то же время."""
    try:
        with session() as s:
            t = s.get(Task, task_id)
            if not t or not t.due:
                return
            when = t.due
        _set_event_start([e.id for e in events_for_task(task_id)], when)
    except Exception as e:  # pragma: no cover
        log.warning("sync task→event: %s", e)


def complete_events_for_task(task_id: int, done: bool) -> list[str]:
    """Задачу закрыли/вернули — закрываем/возвращаем привязанные встречи. Возвращает, что изменилось."""
    from . import calendar as _cal
    out: list[str] = []
    try:
        for ev in events_for_task(task_id):
            if bool(ev.done) == done:
                continue
            _cal.set_done(ev.id, done)
            out.append(f"встреча «{ev.title}»")
    except Exception as e:  # pragma: no cover
        log.warning("complete events for task: %s", e)
    return out


def complete_task_for_event(event_id: int, done: bool) -> list[str]:
    """Встречу закрыли/вернули — закрываем/возвращаем привязанную задачу. Возвращает, что изменилось."""
    try:
        with session() as s:
            ev = s.get(Event, event_id)
            if not ev or not ev.task_id or ev.repeat:
                return []   # у повторов галочка — про один раз, задачу целиком не трогаем
            tid = ev.task_id
        with session() as s:
            t = s.get(Task, tid)
            if not t or bool(t.done) == done:
                return []
            title = t.title
            t.done = done
            t.done_at = datetime.now() if done else None
            s.add(t)
            s.commit()
        return [f"задача «{title}»"]
    except Exception as e:  # pragma: no cover
        log.warning("complete task for event: %s", e)
        return []
