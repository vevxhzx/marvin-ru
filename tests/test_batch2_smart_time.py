"""Батч 2: умное время — TDD.

Спецификация:
- одиночная цифра днём = PM («встреча сегодня в 4» → 16:00);
- «вечером» → 19:00, «утром» → 9:00, «днём» → 13:00, «ночью» → 23:00;
- ночь 0–5 без маркера — всегда уточнять (голое «в 3» → clarify, записи нет);
- задача vs событие: глагол действия → задача, встреча/событие/явное время → календарь,
  непонятное — вопрос «календарь или задача», «напомни» без времени — спросить когда.
"""
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402

from core import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlalchemy import event
    from sqlmodel import create_engine
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


def test_meeting_single_digit_is_pm():
    """«встреча сегодня в 4» → событие в 16:00, а не в 04:00."""
    from core.brain import agent
    from core.services import calendar
    r = agent.rules("встреча сегодня в 4", "b2-1")
    assert r is not None and "add_event" in r.actions, (r.actions if r else None, r.text if r else None)
    ev = calendar.find_event("встреча")
    assert ev is not None, "событие не создалось"
    assert ev.start.hour == 16, ev.start


def test_remind_evening_is_19():
    """«напомни вечером про стирку» → событие в 19:00."""
    from core.brain import agent
    from core.services import calendar
    r = agent.rules("напомни вечером про стирку", "b2-2")
    assert r is not None and "add_event" in r.actions, (r.actions if r else None, r.text if r else None)
    ev = calendar.find_event("стирку")
    assert ev is not None, "событие не создалось"
    assert ev.start.hour == 19, ev.start


def test_bare_night_hour_asks():
    """Голое «в 3» (0–5 без маркера) → clarify «ночью или днём», записи нет."""
    from core.brain import agent
    from core.brain.dates import ambiguous_night_hour
    from core.services import calendar, tasks
    assert ambiguous_night_hour("в 3") == 3
    r = agent.rules("в 3", "b2-3")
    assert r is not None and "clarify" in r.actions, (r.actions if r else None, r.text if r else None)
    assert calendar.list_events(limit=50) == []
    assert tasks.list_tasks() == []


def test_action_verb_is_task():
    """«позвонить маме в 5» → задача с дедлайном 17:00, а не событие в календаре."""
    from core.brain import agent
    from core.services import calendar, tasks
    r = agent.rules("позвонить маме в 5", "b2-4")
    assert r is not None and "add_task" in r.actions, (r.actions if r else None, r.text if r else None)
    assert "add_event" not in r.actions
    ts = tasks.list_tasks()
    assert len(ts) == 1, [t.title for t in ts]
    assert "позвонить" in ts[0].title.lower() and "мам" in ts[0].title.lower(), ts[0].title
    assert ts[0].due is not None and ts[0].due.hour == 17, ts[0].due
    assert calendar.list_events(limit=50) == []


def test_bare_remind_asks_when():
    """«напомни» без времени → clarify «когда»; «напомни маме позвонить» — тоже."""
    from core.brain import agent
    r = agent.rules("напомни", "b2-5")
    assert r is not None and "clarify" in r.actions, (r.actions if r else None, r.text if r else None)
    assert "когда" in r.text.lower(), r.text
    r2 = agent.rules("напомни маме позвонить", "b2-5b")
    assert r2 is not None and "clarify" in r2.actions, (r2.actions, r2.text)
    assert "когда" in r2.text.lower(), r2.text
