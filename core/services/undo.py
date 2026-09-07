"""Откат последнего действия любого типа («отмена», «не то, удали»)."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import select

from ..db import ActionLog, Debt, Event, Link, Note, Recurring, Task, Transaction, session
from . import finance

_TABLES = {"event": Event, "task": Task, "transaction": Transaction, "debt": Debt, "recurring": Recurring, "note": Note, "link": Link}
_LABEL = {"add_event": "событие", "add_task": "задачу", "add_expense": "трату", "add_income": "доход", "pay_debt": "платёж по долгу",
          "add_debt": "долг", "add_recurring": "регулярный платёж", "add_note": "заметку", "add_link": "ссылку", "bulk_delete": "удаление"}


def last_action(channel: str | None = None, max_age_min: int = 24 * 60) -> ActionLog | None:
    with session() as s:
        q = select(ActionLog).where(ActionLog.undone == False, ActionLog.created_at >= datetime.now() - timedelta(minutes=max_age_min))  # noqa: E712
        return s.exec(q.order_by(ActionLog.id.desc())).first()


def undo_last(channel: str | None = None) -> str | None:
    """Откатывает последнее действие. Возвращает текст для пользователя или None, если отменять нечего."""
    a = last_action(channel)
    if not a:
        return None
    label = _LABEL.get(a.kind, a.kind)
    ok = False
    if a.ref_table == "trash":
        from . import bulk
        n = bulk.restore(a.ref_id)
        with session() as s:
            a2 = s.get(ActionLog, a.id)
            if a2:
                a2.undone = True; s.add(a2); s.commit()
        return f"Вернул из корзины {n} записей ({a.title}). Балансы на месте." if n else f"Корзина ({a.title}) уже пуста, сэр."
    if a.ref_table == "transaction":
        ok = finance.delete_transaction(a.ref_id)   # вернёт баланс/остаток долга
    else:
        model = _TABLES.get(a.ref_table)
        with session() as s:
            row = s.get(model, a.ref_id) if model else None
            if row is not None:
                if a.ref_table == "debt":
                    for r in s.exec(select(Recurring).where(Recurring.debt_id == row.id)).all():
                        s.delete(r)
                if a.ref_table == "event" and getattr(row, "google_id", None):
                    from .calendar import _gcal_remove
                    _gcal_remove(row.id, row.google_id)
                s.delete(row)
                ok = True
            s.commit()
    with session() as s:
        a2 = s.get(ActionLog, a.id)
        if a2:
            a2.undone = True
            s.add(a2); s.commit()
    if not ok:
        return f"Последнее действие ({label} «{a.title}») уже удалено, сэр."
    return f"Отменил {label} «{a.title}». Как будто и не было."
