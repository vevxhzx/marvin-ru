"""Fast-path времени/даты: вопрос про часы отвечает правило, без LLM.

Позитив: «который час», «але какое сейчас время» и т.п. → одна строка
с HH:MM + день недели/дата. Негатив: «напомни в 15:00» / «встреча в 15:00»
(команда со временем, а не вопрос про время) правилом времени не трогаем.
"""
import os
import re

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402

from core import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlmodel import create_engine
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    from sqlalchemy import event
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
WD_RE = re.compile(r"понедельник|вторник|сред[ауы]|четверг|пятниц[ауы]|суббот[ауы]|воскресень[ея]")


def _assert_time_shape(text: str):
    assert TIME_RE.search(text), text
    assert WD_RE.search(text.lower()), text
    assert "\n" not in text.strip(), text  # одна строка, без простыни


POSITIVE = [
    "который час",
    "Который час?",
    "сколько времени",
    "але какое сейчас время",
    "какое сейчас время",
    "сейчас понедельник, какое у тебя время",
    "какое сегодня число",
    "какая сегодня дата",
    "время сейчас",
    "какой сегодня день",
]


@pytest.mark.parametrize("q", POSITIVE)
def test_time_q_answers(q):
    from core.brain import quick
    r = quick.time_q(q)
    assert r is not None, q
    assert r[1] == ["time"]
    _assert_time_shape(r[0])


NEGATIVE = [
    "напомни в 15:00",
    "напомни мне позвонить в 15:00",
    "встреча в 15:00",
    "встреча в среду в 15:00 с Ваней",
    "потратил 700 на такси",
]


@pytest.mark.parametrize("q", NEGATIVE)
def test_time_q_ignores_reminders_and_events(q):
    from core.brain import quick
    assert quick.time_q(q) is None, q


def test_rules_time_is_fast_path_without_llm():
    from core.brain import agent
    r = agent.rules("але какое сейчас время", "test")
    assert r is not None
    assert r.via == "rules" and r.actions == ["time"]
    _assert_time_shape(r.text)


def test_rules_reminder_still_goes_to_calendar_path():
    from core.brain import agent
    r = agent.rules("напомни в 15:00 позвонить маме", "test")
    assert r is None or "time" not in (r.actions or [])


def test_quick_run_time_first():
    from core.brain import quick
    r = quick.run("который час", "test")
    assert r is not None and r[1] == ["time"]
    _assert_time_shape(r[0])
    assert quick.run("встреча в 15:00", "test") is None or quick.run("встреча в 15:00", "test")[1] != ["time"]
