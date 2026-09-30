"""Новые функции v0.13 (доработка): привычки, «что я упускаю», подсказка по заказам, снимок месяца."""
import os
from datetime import datetime, timedelta

os.environ.setdefault("JARVIS_TEST", "1")


# ---------------------------------------------------------------- привычки (умное откладывание)
def test_habits_best_hour_and_next(monkeypatch):
    from core.services import habits
    monkeypatch.setattr(habits, "active_hours", lambda days=90: [(20, 30), (21, 10), (9, 2)])
    assert habits.best_hour() == 20
    now = datetime(2026, 9, 30, 10, 0)
    nxt = habits.next_habit(now)
    assert (nxt.hour, nxt.day) == (20, 30)          # сегодня вечером
    late = datetime(2026, 9, 30, 22, 0)
    assert habits.next_habit(late) > late            # уже поздно → следующее время в будущем


def test_habits_silent_with_little_data(monkeypatch):
    from core.services import habits
    monkeypatch.setattr(habits, "active_hours", lambda days=90: [(20, 2)])
    assert habits.hint() is None
    assert habits.best_hour(default=7) == 7


# ---------------------------------------------------------------- «что я упускаю»
def test_missed_collects_gaps(monkeypatch):
    from core.services import missed as M

    class T:
        def __init__(self, i, title, due, created):
            self.id, self.title, self.due, self.done, self.created_at = i, title, due, False, created

    monkeypatch.setattr(M.orders, "list_orders", lambda **k: [
        {"id": 1, "title": "ролик", "client": "Пятёрочка", "left": 5000,
         "deadline": (datetime.now() - timedelta(days=2)).isoformat(), "overdue": True},
        {"id": 2, "title": "свежий", "client": "X", "left": 5000,
         "deadline": (datetime.now() + timedelta(days=5)).isoformat(), "overdue": False, "past_due": False},
    ])
    monkeypatch.setattr(M.finance, "list_debts", lambda: [])
    monkeypatch.setattr(M.tasks, "list_tasks", lambda **k: [
        T(1, "без срока", None, datetime.now() - timedelta(days=10)),
        T(2, "со сроком", datetime.now(), datetime.now()),
    ])
    monkeypatch.setattr(M.goals, "list_goals", lambda **k: [])
    m = M.missed()
    assert m["count"] == 2                       # 1 просроченная оплата + 1 дело без срока
    assert m["unpaid"][0]["title"] == "ролик"
    assert "упускаете" in M.missed_text().lower()


# ---------------------------------------------------------------- подсказка цены по прошлым заказам
def test_orders_suggestion_from_history(tmp_path, monkeypatch):
    from sqlmodel import create_engine
    from sqlalchemy import event
    from core import db

    eng = create_engine(f"sqlite:///{tmp_path / 'o.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()

    from core.services import orders
    orders.add_order("Монтаж ролика для Пятёрочки", 25000)
    orders.add_order("Монтаж ролика для Магнита", 30000)
    s = orders.suggestion("монтаж ролика")
    assert s["count"] >= 2 and s["price"] == 27500
    assert orders.suggestion("совсем не про это")["count"] == 0
