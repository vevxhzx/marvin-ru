"""Задачи."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import select

from ..db import icontains, Task, log_action, now, remember, session


def add_task(title: str, due: datetime | None = None, priority: int = 2,
             project: str | None = None, source: str = "tg") -> Task:
    with session() as s:
        # дубль открытой задачи с тем же названием — не плодим
        for d in s.exec(select(Task).where(Task.done == False)).all():  # noqa: E712
            if d.title.strip().lower() == title.strip().lower():
                if due and not d.due:
                    d.due = due; s.add(d); s.commit()
                return d
        t = Task(title=title, due=due, priority=priority, project=project, source=source)
        s.add(t)
        s.commit()
        s.refresh(t)
        remember(s, "task", f"Задача: «{title}»" + (f" до {due.strftime('%d.%m %H:%M')}" if due else ""), "task", t.id, source)
        log_action(s, "add_task", "task", t.id, title, source)
        s.commit()
        return t


def find_task(query: str | int) -> Task | None:
    with session() as s:
        if isinstance(query, int) or str(query).isdigit():
            return s.get(Task, int(query))
        from .calendar import stems
        for q in stems(query):
            t = s.exec(select(Task).where(Task.done == False, icontains(Task.title, q)).order_by(Task.created_at.desc())).first()  # noqa: E712
            if t:
                return t
        from .match import best
        return best(s.exec(select(Task).where(Task.done == False).order_by(Task.created_at.desc())).all(), str(query), min_score=0.66)  # noqa: E712


def update_task(task_id: int, **fields) -> Task | None:
    with session() as s:
        t = s.get(Task, task_id)
        if not t:
            return None
        if fields.get("title") is not None:
            t.title = fields["title"].strip() or t.title
        if "due" in fields:
            d = fields["due"]
            t.due = (d if isinstance(d, datetime) else datetime.fromisoformat(str(d))) if d else None
            t.remind_stage = 0
        if fields.get("priority") is not None:
            t.priority = int(fields["priority"])
        if "project" in fields:
            t.project = (fields["project"] or "").strip() or None
        if fields.get("done") is not None:
            t.done = bool(fields["done"]); t.done_at = now() if t.done else None
        s.add(t)
        remember(s, "task", f"Изменена задача: «{t.title}»" + (f" до {t.due:%d.%m %H:%M}" if t.due else ""), "task", t.id)
        s.commit(); s.refresh(t)
        return t


def due_task_reminders() -> list[tuple[Task, str]]:
    """Напоминания по дедлайнам: утром в день дедлайна (stage 1) и за час до него (stage 2)."""
    nw = now()
    out: list[tuple[Task, str]] = []
    with session() as s:
        for t in s.exec(select(Task).where(Task.done == False, Task.due != None)).all():  # noqa: E711,E712
            if t.due < nw - timedelta(hours=2):
                continue
            same_day = t.due.date() == nw.date()
            if t.remind_stage < 1 and same_day and nw.hour >= 9:
                # если до дедлайна уже меньше часа — второе напоминание («остался час») не нужно
                t.remind_stage = 2 if t.due - nw <= timedelta(hours=1) else 1; s.add(t)
                out.append((t, f"📌 Сегодня дедлайн: «{t.title}» — до {t.due:%H:%M}. Сэр, само себя оно не сделает."))
            elif t.remind_stage < 2 and timedelta(0) <= t.due - nw <= timedelta(hours=1):
                t.remind_stage = 2; s.add(t)
                mins = int((t.due - nw).total_seconds() // 60)
                out.append((t, f"⏳ «{t.title}» — остался {'час' if mins > 50 else f'{mins} мин'} (до {t.due:%H:%M})."))
        s.commit()
    return out


def list_tasks(include_done: bool = False, limit: int = 50) -> list[Task]:
    with session() as s:
        q = select(Task)
        if not include_done:
            q = q.where(Task.done == False)  # noqa: E712
        else:
            q = q.where((Task.project != "archive") | (Task.project == None))  # noqa: E711  архив «Чистого листа» не показываем
        return list(s.exec(q.order_by(Task.done, Task.priority, Task.due, Task.created_at).limit(limit)))


def complete_task(query: str | int) -> Task | None:
    """Закрыть задачу по id или по части названия."""
    with session() as s:
        if isinstance(query, int) or str(query).isdigit():
            t = s.get(Task, int(query))
        else:
            t = s.exec(select(Task).where(Task.done == False, icontains(Task.title, query))).first()  # noqa: E712
            if not t:
                t = find_task(query)
                t = s.get(Task, t.id) if t else None
        if not t:
            return None
        t.done = True
        t.done_at = now()
        s.add(t)
        remember(s, "task", f"Выполнено: «{t.title}»", "task", t.id)
        s.commit()
        s.refresh(t)
        return t


def delete_task(task_id: int) -> bool:
    with session() as s:
        t = s.get(Task, task_id)
        if not t:
            return False
        s.delete(t)
        s.commit()
        return True
