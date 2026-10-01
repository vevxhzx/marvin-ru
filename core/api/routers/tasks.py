"""Задачи и календарь (ФАЗА 7, шаг 7.4).

Роуты перенесены из `core/api/app.py` МЕХАНИЧЕСКИ: пути, методы, тела функций,
порядок ответов и логика не менялись. Декораторы сохраняют полный путь
(`/api/...`), поэтому `router` создаётся БЕЗ prefix — пути совпадают 1:1.

Состав: `/api/events*` (6 роутов, без SSE), `/api/tasks*` (7),
`GET /api/focus`, `GET /api/timeline` — итого 15 роутов
(таблица `reviews/P7_refactor.md` §3, домен `tasks`).

`GET /api/events/stream` (SSE) здесь НЕТ и НЕ должен появляться: по §3 отчёта
шага 7.0 он уезжает в `system.py` на шаге 7.6 (живой канал для всего сайта,
а не календарь). Пока он живёт в `core/api/app.py` и регистрируется
ПЕРВЫМ из всех `/api/*` — это даже лучше для порядка: литерал `stream`
не может проиграть параметрическому `/api/events/{event_id}`.

Инвариант регистрации (см. `core/api/routers/__init__.py`): `register(app)`
вызывается из `app.py` ПОСЛЕ `include_router(_crm_router)` и ДО статики и
catch-all SPA. Порядок роутов внутри модуля = порядок в `app.py` на шаге 7.3:
сначала блок календаря, потом задачи, потом `/api/focus`, потом `/api/timeline`.

Свои хелперы ушли сюда вместе с роутами (единственные пользователи были в
этом домене, в `_shared.py` их НЕ выносим): `_task_as_event` (1 вызов —
`GET /api/events` c `tasks_too=True`) и `_event_as_task` (1 вызов —
`GET /api/tasks` c `events_too=True`).

`core/crm/router.py` (prefix `/api/crm`) НЕ тронут: пути CRM другие,
дублирования нет.

Локальные импорты внутри тел роутов сохранены как есть (в проекте это осознанный
приём: быстрый старт, обход циклов) — у них ровно на одна точка больше,
т.к. модуль лежит на уровне `core/api/routers/`: `from ...services import aims`
(2, в `PUT /api/tasks/{task_id}` и `GET /api/focus`) и
`from ...services import timeline` (1, в `GET /api/timeline`).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from ...db import Aim, Event, Milestone, Task, session
from ...services import calendar, orders, tasks
from .._shared import _ev_out
from ..schemas import EventDoneIn, EventIn, SkipIn, TaskIn, TaskPatch

router = APIRouter()


def register(app) -> None:
    app.include_router(router)


# ---------------- календарь ----------------
# ФАЗА 7 шаг 7.0: _ev_out (общий формат события для дашборда и /api/events) живёт в core/api/_shared.py


def _task_as_event(t: Task) -> dict:
    """Задача с дедлайном в календаре: тот же формат, что событие, + kind='task'. Записи в БД не дублируются —
    отметил в календаре → закрылась задача, перенёс задачу → сдвинулась в календаре."""
    all_day = t.due.hour == 23 and t.due.minute == 59
    # задача с конкретным временем занимает в календаре полчаса — видно, куда её подвинуть; «до конца дня» — без длительности
    end = t.due if all_day else t.due + timedelta(minutes=30)
    return {"id": -t.id, "task_id": t.id, "kind": "task", "title": t.title, "start": t.due, "end": end, "duration_min": 0 if all_day else 30,
            "location": None, "notes": None, "repeat": "", "repeat_label": "", "repeat_anchor": t.due, "done": t.done,
            "priority": t.priority, "all_day": all_day}


@router.get("/api/events")
def events(start: Optional[datetime] = None, end: Optional[datetime] = None, tasks_too: bool = False):
    out = [dict(_ev_out(e), kind="event") for e in calendar.list_events(start, end, limit=1000)]
    if tasks_too:
        with session() as s:
            q = select(Task).where(Task.due != None)  # noqa: E711
            if start:
                q = q.where(Task.due >= start)
            if end:
                q = q.where(Task.due <= end)
            for t in s.exec(q.limit(1000)).all():
                if not t.done or (t.done_at and start and t.done_at >= start):
                    out.append(_task_as_event(t))
        # дедлайны заказов — тоже в календаре (kind='order'), закрытые не показываем
        for o in orders.list_orders():
            if o["deadline"] and o["status"] in ("new", "work", "review") and (not start or o["deadline"] >= start) and (not end or o["deadline"] <= end):
                out.append({"id": -100000 - o["id"], "order_id": o["id"], "kind": "order", "status": o["status"], "title": f"Сдать: {o['title']}" + (f" · {o['client']}" if o["client"] else ""),
                            "start": o["deadline"], "end": o["deadline"], "duration_min": 0, "location": None, "notes": None, "repeat": "", "repeat_label": "",
                            "repeat_anchor": o["deadline"], "done": False, "priority": 2 if (o["days_left"] or 0) <= 2 else 1,
                            "all_day": o["deadline"].hour == 23 and o["deadline"].minute == 59})
    return out


@router.post("/api/events")
def create_event(e: EventIn):
    return _ev_out(calendar.add_event(e.title, e.start, e.duration_min, e.location, e.notes, e.remind_minutes, "web",
                                      repeat=e.repeat, repeat_days=e.repeat_days, repeat_until=e.repeat_until,
                                      task_id=e.task_id, order_id=e.order_id))


@router.put("/api/events/{event_id}")
def update_event(event_id: int, e: EventIn):
    ev = calendar.update_event(event_id, title=e.title, start=e.start, duration_min=e.duration_min, location=e.location, notes=e.notes,
                               remind_minutes=e.remind_minutes, repeat=e.repeat, repeat_days=e.repeat_days, repeat_until=e.repeat_until,
                               task_id=e.task_id, order_id=e.order_id)
    if not ev:
        raise HTTPException(404)
    return _ev_out(ev)


@router.post("/api/events/{event_id}/done")
def done_event(event_id: int, p: EventDoneIn):
    """Галочка на событии — как на задаче. Одна запись: видна и в календаре, и в «Делах», и в Google (✓ в названии).

    Отрицательный id — проекция: `-id` = задача, `-(100000 + id)` = дедлайн заказа. В ответе `linked` —
    что ещё закрылось вместе с этим событием: одна галочка отражается и в задачах, и в заказах."""
    linked: list[str] = []

    # дедлайн заказа: «сдал» / обратно «снова в работе»
    if event_id <= -100000:
        order_id = -(event_id + 100000)
        o = orders.get_order(order_id)
        if not o:
            raise HTTPException(404)
        if p.done and o.status not in ("paid", "cancelled"):
            orders.update_order(order_id, status="done")
            linked.append(f"заказ «{o.title}» — сдан")
        elif not p.done and o.status == "done":
            orders.update_order(order_id, status="work")
            linked.append(f"заказ «{o.title}» — снова в работе")
        return {"ok": True, "linked": linked}

    # задача из списка, показанная в календаре
    if event_id < 0:
        t = tasks.update_task(-event_id, done=bool(p.done))   # с координацией: закрывается и привязанная встреча
        if not t:
            raise HTTPException(404)
        return {"ok": True, "linked": linked}

    ev = calendar.set_done(event_id, p.done, p.date)
    if not ev:
        raise HTTPException(404)

    # каскад по привязкам встречи
    if ev.task_id:
        with session() as s:
            t = s.get(Task, ev.task_id)
            if t:
                t.done = bool(p.done)
                t.done_at = datetime.now() if p.done else None
                s.add(t)
                s.commit()
                linked.append(f"задача «{t.title}»")
    if ev.order_id:
        o = orders.get_order(ev.order_id)
        if o:
            if p.done and o.status not in ("paid", "cancelled"):
                orders.update_order(ev.order_id, status="done")
                linked.append(f"заказ «{o.title}»")
            elif not p.done and o.status == "done":
                orders.update_order(ev.order_id, status="work")
                linked.append(f"заказ «{o.title}» — снова в работе")

    d = _ev_out(ev)
    if ev.repeat and p.date:
        d["done"] = calendar.is_done(ev, p.date)
    return {"ok": True, "linked": linked, **d}


@router.post("/api/events/{event_id}/skip")
def skip_event(event_id: int, p: SkipIn):
    """Пропустить один повтор («в эту среду тренировки не будет»)."""
    ev = calendar.skip_occurrence(event_id, p.date)
    if not ev:
        raise HTTPException(404)
    return _ev_out(ev)


@router.delete("/api/events/{event_id}")
def remove_event(event_id: int):
    if not calendar.delete_event(event_id):
        raise HTTPException(404)
    return {"ok": True}


# ---------------- задачи ----------------
def _event_as_task(e: Event) -> dict:
    """Событие календаря в списке дел: тот же формат, что задача, + kind='event'. Отметил в делах → сделано и в календаре."""
    return {"id": -e.id, "event_id": e.id, "kind": "event", "title": e.title, "done": calendar.is_done(e), "priority": 2, "due": e.start,
            "end": e.end, "project": None, "source": e.source, "created_at": e.created_at, "done_at": e.done_at if not e.repeat else None,
            "repeat": e.repeat, "location": e.location}


@router.get("/api/tasks")
def get_tasks(all: bool = False, events_too: bool = False):
    out = [t.model_dump() for t in tasks.list_tasks(include_done=all, limit=500)]
    if events_too:
        # «сегодня по календарю»: события сегодняшнего дня (и вчерашние несделанные — чтобы не потерялись)
        d0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        for e in calendar.list_events(d0 - timedelta(days=1), d0 + timedelta(days=1), limit=200):
            if e.start < d0 and calendar.is_done(e):
                continue
            out.append(_event_as_task(e))
    return out


@router.get("/api/tasks/{task_id}")
def get_task(task_id: int):
    with session() as s:
        t = s.get(Task, task_id)
    if not t:
        raise HTTPException(404)
    return t


@router.post("/api/tasks")
def create_task(t: TaskIn):
    return tasks.add_task(t.title, t.due, t.priority, t.project, "web")


@router.put("/api/tasks/{task_id}")
def patch_task(task_id: int, p: TaskPatch):
    fields = p.model_dump(exclude_none=True)
    fields.pop("clear_due", None)
    if p.clear_due:
        fields["due"] = None
    if fields.get("milestone_id") or fields.get("aim_id"):
        # чужой/несуществующий id — 404, а не молчаливая запись в базу
        from ...services import aims
        with session() as s:
            if fields.get("milestone_id") and not s.get(Milestone, fields["milestone_id"]):
                raise HTTPException(404, "веха не найдена")
            if fields.get("aim_id") and not s.get(Aim, fields["aim_id"]):
                raise HTTPException(404, "цель не найдена")
        if fields.get("milestone_id"):
            aims.link_task(task_id, milestone=fields.pop("milestone_id"))
            fields.pop("aim_id", None)
    t = tasks.update_task(task_id, **fields)
    if not t:
        raise HTTPException(404)
    return t


@router.post("/api/tasks/{task_id}/undone")
def undone_task(task_id: int):
    # через сервис, а не напрямую: сработает координация со встречей (вернём и её)
    t = tasks.update_task(task_id, done=False)
    if not t:
        raise HTTPException(404)
    return t


@router.post("/api/tasks/{task_id}/done")
def done_task(task_id: int):
    t = tasks.complete_task(task_id)
    if not t:
        raise HTTPException(404)
    return t


@router.delete("/api/tasks/{task_id}")
def remove_task(task_id: int):
    if not tasks.delete_task(task_id):
        raise HTTPException(404)
    return {"ok": True}


@router.get("/api/focus")
def get_focus():
    """Фокус дня: 1–3 шага к целям + что мешает. Пусто, если целей нет — карточка на «Сегодня» тогда не рисуется."""
    from ...services import aims
    f = aims.focus()
    for it in f["items"]:
        if it.get("due"):
            it["due"] = it["due"].isoformat()
    return f


@router.get("/api/timeline")
def get_timeline(day: str | None = None, q: str | None = None):
    from ...services import timeline
    try:
        d = datetime.fromisoformat(day) if day else None
    except ValueError:
        raise HTTPException(422, "day: дата в формате ГГГГ-ММ-ДД")
    items = timeline.build(d, q)
    return [{**i, "at": i["at"].isoformat(), "end": i["end"].isoformat() if i.get("end") else None} for i in items]
