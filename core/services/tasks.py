"""Задачи."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import select

from ..db import diff_text, icontains, Task, log_action, now, remember, session


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
        before = {"title": t.title, "due": t.due, "priority": t.priority, "project": t.project, "done": t.done,
                  "blocked_by": t.blocked_by, "aim_id": t.aim_id, "milestone_id": t.milestone_id}
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
        if "blocked_by" in fields:
            t.blocked_by = (fields["blocked_by"] or "").strip()[:200]
        if "aim_id" in fields:
            t.aim_id = fields["aim_id"] or None
        if "milestone_id" in fields:
            t.milestone_id = fields["milestone_id"] or None
        s.add(t)
        after = {"title": t.title, "due": t.due, "priority": t.priority, "project": t.project, "done": t.done,
                 "blocked_by": t.blocked_by, "aim_id": t.aim_id, "milestone_id": t.milestone_id}
        changes = diff_text({k: v for k, v in before.items() if k in ("title", "due", "priority", "project", "done")},
                            {k: v for k, v in after.items() if k in ("title", "due", "priority", "project", "done")},
                            {"title": "название", "due": "срок", "priority": "приоритет", "project": "проект", "done": "сделано"})
        extra = []
        if before["blocked_by"] != after["blocked_by"]:
            extra.append(f"блок: {after['blocked_by']}" if after["blocked_by"] else "блок снят")
        if (before["aim_id"], before["milestone_id"]) != (after["aim_id"], after["milestone_id"]):
            extra.append("привязка к цели" if after["aim_id"] else "отвязана от цели")
        changes = ", ".join([c for c in [changes] if c] + extra)
        if changes:   # пустой PUT (ничего не поменялось) в ленту не пишем
            remember(s, "task", f"Изменена задача «{t.title}»: {changes}", "task", t.id)
        s.commit(); s.refresh(t)
    if fields.get("done") and not before["done"]:
        _after_done(t)
    return t


def due_task_reminders() -> list[tuple[Task, str]]:
    """Напоминания по дедлайнам со временем: утром в день дедлайна (stage 1) и за час до него (stage 2).
    Задачи «на весь день» (23:59) сюда не попадают: их и так показывает утренний дайджест, а вечером спрашивает обзор —
    иначе в 9:00 прилетает по отдельному «до 23:59» на каждую (так и было)."""
    from ..brain.dates import is_all_day
    nw = now()
    out: list[tuple[Task, str]] = []
    with session() as s:
        for t in s.exec(select(Task).where(Task.done == False, Task.due != None)).all():  # noqa: E711,E712
            if t.due < nw - timedelta(hours=2) or is_all_day(t.due):
                continue
            same_day = t.due.date() == nw.date()
            if t.remind_stage < 1 and same_day and nw.hour >= 9:
                # если до дедлайна уже меньше часа — второе напоминание («остался час») не нужно
                t.remind_stage = 2 if t.due - nw <= timedelta(hours=1) else 1; s.add(t)
                out.append((t, f"📌 Сегодня до {t.due:%H:%M} — «{t.title}»."))
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
    _after_done(t)
    return t


LAST_PROGRESS: dict = {}   # task_id → результат aims.on_task_done (что продвинулось) — агент дописывает это в ответ


def progress_tail(task_id: int) -> str:
    """Хвост к «сделано»: куда это продвинуло цель. Пусто, если задача ни к чему не привязана."""
    r = LAST_PROGRESS.pop(task_id, None)
    if not r:
        return ""
    if r.get("aim_ready"):
        return f" Это была последняя веха по «{r['aim']}» — цель достигнута или ставим следующую?"
    if r.get("milestone_closed"):
        nxt = r.get("next") or []
        return f" Веха «{r['milestone']}» закрыта." + (f" Дальше: «{nxt[0]['title']}»." if nxt else " Следующую веху пока не ставил.")
    nxt = [n for n in (r.get("next") or []) if n.get("task_id") != task_id]
    return f" Шаг к «{r['aim']}»." + (f" Следующий: «{nxt[0]['title']}»." if nxt else "")


def _after_done(t: Task) -> None:
    """Закрытая задача — событие и движение цели (0.10). Ошибки здесь не должны мешать самому закрытию."""
    try:
        from . import events
        events.emit("task_done", key=f"task:{t.id}", title=t.title, quiet=True, journal=False)   # в журнале уже есть «Выполнено»
        if t.aim_id or t.milestone_id:
            from . import aims
            r = aims.on_task_done(t)
            if r:
                LAST_PROGRESS.clear(); LAST_PROGRESS[t.id] = r
    except Exception as e:  # pragma: no cover
        import logging
        logging.getLogger("marvin.tasks").warning("after task done: %s", e)


def delete_task(task_id: int) -> bool:
    with session() as s:
        t = s.get(Task, task_id)
        if not t:
            return False
        s.delete(t)
        s.commit()
        return True


def evening_review() -> list[Task]:
    """Что не закрыто к вечеру: дедлайн был сегодня или раньше (просрочено), задача открыта.
    Только для вечернего вопроса «перенести на завтра?» — ничего не меняет."""
    nw = now()
    end_today = nw.replace(hour=23, minute=59, second=59)
    with session() as s:
        rows = s.exec(select(Task).where(Task.done == False, Task.due != None, Task.due <= end_today)  # noqa: E711,E712
                      .order_by(Task.priority, Task.due)).all()
        return list(rows)


def postpone_to_tomorrow(task_id: int, hour: int = 10) -> Task | None:
    """Кнопка «📅 Завтра»: задача со временем → завтра в hour:00; задача «на день» (23:59) остаётся задачей на день, только завтра."""
    from ..brain.dates import is_all_day
    t = find_task(task_id)
    if t is None:
        return None
    tmr = now() + timedelta(days=1)
    tmr = tmr.replace(hour=23, minute=59, second=0, microsecond=0) if is_all_day(t.due) else tmr.replace(hour=hour, minute=0, second=0, microsecond=0)
    return update_task(task_id, due=tmr)
