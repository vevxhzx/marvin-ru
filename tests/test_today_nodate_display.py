"""Сегодня без времени: задача «на сегодня» хранится как 23:59, а показывается как «сегодня» без времени."""
import os
from datetime import datetime, timedelta

os.environ.setdefault("ASSISTANT_TEST", "1")

from core import db  # noqa: E402


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlalchemy import event
    from sqlmodel import create_engine
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


def _today_2359():
    return datetime.now().replace(hour=23, minute=59, second=0, microsecond=0)


def test_add_task_today_shows_today_not_2359():
    from core.tools import registry
    txt = registry.run_tool("add_task", {"title": "Купить хлеб сегодня тест", "due": "сегодня"}, "test")
    assert "сегодня" in txt.lower()
    assert "23:59" not in txt


def test_list_tasks_all_day_no_time():
    from core.services import tasks
    from core.tools import registry
    tasks.add_task("Дело на сегодня без времени", _today_2359(), source="test")
    txt = registry.run_tool("list_tasks", {}, "test")
    assert "Дело на сегодня без времени" in txt
    assert "23:59" not in txt
    # просто «сегодня», а не «сегодня в 23:59»
    assert "сегодня" in txt.lower()
    assert "в 23:59" not in txt


def test_agenda_all_day_no_time():
    from core.services import tasks
    from core.tools import registry
    tasks.add_task("Повестка на сегодня", _today_2359(), source="test")
    txt = registry.run_tool("agenda", {"date": "сегодня"}, "test")
    assert "Повестка на сегодня" in txt
    assert "23:59" not in txt


def test_briefing_all_day_no_time():
    from core.services import tasks
    from core.tools import registry
    tasks.add_task("Брифинг дело сегодня", _today_2359(), source="test")
    txt = registry.run_tool("today_briefing", {}, "test")
    assert "Брифинг дело сегодня" in txt
    assert "23:59" not in txt


def test_evening_all_day_no_time():
    from core.services import cards, tasks
    tasks.add_task("Вечернее дело сегодня", _today_2359(), source="test")
    txt = cards.evening_text()
    assert "23:59" not in txt


def test_fmt_task_due_helper():
    from core.services.calendar import fmt_task_due
    assert "23:59" not in fmt_task_due(_today_2359())
    assert "сегодня" in fmt_task_due(_today_2359()).lower()


def test_timed_task_keeps_time():
    from core.services import tasks
    from core.tools import registry
    due = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
    if due <= datetime.now():
        due += timedelta(days=1)
    tasks.add_task("Созвон в три", due, source="test")
    txt = registry.run_tool("list_tasks", {}, "test")
    assert "15:00" in txt


def test_event_with_time_unchanged():
    from core.services import calendar
    start = datetime.now().replace(hour=15, minute=0, second=0, microsecond=0)
    if start <= datetime.now():
        start += timedelta(days=1)
    ev = calendar.add_event("Встреча в три", start, source="test")
    assert (ev.start.hour, ev.start.minute) == (15, 0)
    assert "15:00" in calendar.fmt_dt(ev.start)
