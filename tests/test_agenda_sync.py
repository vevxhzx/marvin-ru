"""Этап А: задачи ⇄ календарь одна сущность, ночные часы «в 4», имя ассистента в интерфейсе (identity)."""
import os
from datetime import datetime, timedelta

import pytest

os.environ["ASSISTANT_TEST"] = "1"

from core import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlmodel import create_engine
    from sqlalchemy import event
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


def _client():
    from fastapi.testclient import TestClient
    from core.api.app import app
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 5555))


def _j(r):
    assert r.status_code < 400, (r.status_code, r.text)
    return r.json()


def test_event_done_is_shared_between_calendar_tasks_and_chat():
    """Галочка на событии: видна в /api/events, в /api/tasks?events_too, в «сегодня» дашборда; о сделанном не напоминаем."""
    from core.services import calendar
    c = _client()
    start = datetime.now().replace(second=0, microsecond=0) + timedelta(hours=2)
    ev = _j(c.post("/api/events", json={"title": "Встреча с мопсом", "start": start.isoformat(), "duration_min": 60}))
    assert ev["done"] is False
    # в «Делах» событие сегодняшнего дня — отдельной строкой kind=event
    rows = _j(c.get("/api/tasks?events_too=true"))
    row = next(r for r in rows if r.get("kind") == "event" and r["event_id"] == ev["id"])
    assert row["done"] is False and row["title"] == "Встреча с мопсом"
    # отметил в делах → сделано в календаре
    d = _j(c.post(f"/api/events/{ev['id']}/done", json={"done": True}))
    assert d["done"] is True
    evs = _j(c.get("/api/events"))
    assert next(e for e in evs if e["id"] == ev["id"])["done"] is True
    assert next(r for r in _j(c.get("/api/tasks?events_too=true")) if r.get("event_id") == ev["id"])["done"] is True
    # сделанное не напоминает
    assert all(e.id != ev["id"] for e in calendar.due_reminders())
    # обратно
    assert _j(c.post(f"/api/events/{ev['id']}/done", json={"done": False}))["done"] is False
    # Google получает ✓ в названии
    from core.services import gcal
    calendar.set_done(ev["id"], True)
    with db.session() as s:
        body = gcal._body(s.get(db.Event, ev["id"]))
    assert body["summary"].startswith("✓ ")


def test_repeat_event_done_only_this_occurrence():
    from core.services import calendar
    today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    ev = calendar.add_event("Тренировка", today - timedelta(days=7), repeat="daily", source="test")
    calendar.set_done(ev.id, True, today)
    occ = calendar.list_events(today - timedelta(days=1), today + timedelta(days=2), limit=10)
    flags = {e.start.date().isoformat(): calendar.is_done(e, e.start) for e in occ}
    assert flags[today.date().isoformat()] is True
    assert flags[(today + timedelta(days=1)).date().isoformat()] is False
    assert flags[(today - timedelta(days=1)).date().isoformat()] is False
    c = _client()
    lst = _j(c.get(f"/api/events?start={(today - timedelta(days=1)).isoformat()}&end={(today + timedelta(days=2)).isoformat()}"))
    assert [e["done"] for e in lst if e["title"] == "Тренировка"].count(True) == 1


def test_task_with_time_gets_half_hour_slot_and_chat_done_closes_event():
    from core.brain import agent
    from core.services import calendar, tasks
    c = _client()
    due = datetime.now().replace(hour=18, minute=0, second=0, microsecond=0) + timedelta(days=1)
    tasks.add_task("Забрать посылку", due, source="test")
    tasks.add_task("Оплатить свет", due.replace(hour=23, minute=59), source="test")
    lst = _j(c.get(f"/api/events?start={(due - timedelta(days=1)).isoformat()}&end={(due + timedelta(days=1)).isoformat()}&tasks_too=true"))
    t1 = next(e for e in lst if e["title"] == "Забрать посылку")
    t2 = next(e for e in lst if e["title"] == "Оплатить свет")
    assert t1["duration_min"] == 30 and datetime.fromisoformat(t1["end"]) - datetime.fromisoformat(t1["start"]) == timedelta(minutes=30)
    assert t2["all_day"] is True and t2["duration_min"] == 0
    # «готово: массаж» без такой задачи — закрывает сегодняшнее событие, а не заводит задачу «Сделал массаж»
    ev = calendar.add_event("Массаж", datetime.now() + timedelta(hours=1), source="test")
    r = agent.rules("сделал массаж", "test")
    assert r and "complete_event" in r.actions and calendar.is_done(calendar.find_event("Массаж"))
    r = agent.rules("готово: полёт на луну", "test")
    assert r and not r.actions and "Не нашёл" in r.text
    assert not any(t.title.lower().startswith("сделал") for t in tasks.list_tasks())


def test_night_hours_are_not_taken_literally():
    """«купить корм в 4» — задача на 16:00 с подсказкой, а не событие в 04:00; «в 4 утра» — как сказано.
    LLM-инструменты и разбор списков с 01–06 без «утра/ночи» сдвигаются на день."""
    from core.brain import agent
    from core.brain.dates import ambiguous_night_hour, fix_night_hour
    from core.services import calendar, tasks
    r = agent.rules("купить корм в 4", "test")
    assert r and r.actions == ["add_task"] and "16:00" in r.text and "в 4 утра" in r.text
    assert calendar.find_event("корм") is None
    t = next(t for t in tasks.list_tasks() if t.title == "Купить корм")
    assert t.due.hour == 16
    r = agent.rules("купить корм в 4 утра", "test")
    assert r and r.actions == ["add_task"] and "утра" not in r.text.split("Дедлайн")[-1]
    assert ambiguous_night_hour("купить корм в 4") == 4 and ambiguous_night_hour("купить корм в 4:30") is None
    assert ambiguous_night_hour("выезд в 6 вечера") is None and ambiguous_night_hour("купить корм на 4 дня") is None
    base = datetime(2026, 9, 17, 4, 0)
    assert fix_night_hour(base, "купить корм 2026-09-17T04:00").hour == 16
    assert fix_night_hour(base, "будильник 2026-09-17T04:00").hour == 4
    assert fix_night_hour(base, "рейс в Сочи 04:00").hour == 4
    assert fix_night_hour(base.replace(hour=10), "созвон").hour == 10
    from core.tools import registry
    registry.run_tool("add_task", {"title": "Позвонить маме", "due": "2027-01-10T05:00"}, "test")
    assert next(t for t in tasks.list_tasks(limit=50) if t.title == "Позвонить маме").due.hour == 17
    registry.run_tool("add_event", {"title": "Такси в аэропорт", "start": "2027-01-10T05:00"}, "test")
    assert calendar.find_event("Такси в аэропорт").start.hour == 5


def test_display_name_in_health_and_manifest():
    from core import identity
    c = _client()
    h = _j(c.get("/api/health"))
    assert h["name"] == identity.title()
    assert _j(c.get("/manifest.json"))["short_name"] == identity.title()


def test_task_with_day_only_is_all_day_not_ten_am():
    """«сходить к нотариусу сегодня» — задача на весь день (23:59), а не «к 10:00»; «завтра в 15» — как сказано.
    Через инструмент модели: «2026-09-16» / «сегодня» без времени — тоже на день; с временем — точный дедлайн."""
    from core.brain import agent
    from core.brain.dates import parse_datetime_ex, task_due
    from core.services import tasks
    from core.tools import registry
    dt, rest, ts = parse_datetime_ex("сходить к нотариусу сегодня")
    assert dt and not ts and rest.strip() == "сходить к нотариусу"
    assert task_due(dt, ts).hour == 23 and task_due(dt, ts).minute == 59
    dt, _, ts = parse_datetime_ex("сделать ролик завтра в 15")
    assert ts and task_due(dt, ts).hour == 15
    dt, _, ts = parse_datetime_ex("позвонить через 2 часа")
    assert ts and task_due(dt, ts) == dt
    dt, _, ts = parse_datetime_ex("сдать отчёт через 3 дня")
    assert not ts and task_due(dt, ts).hour == 23

    r = agent.rules("задача: сходить к нотариусу сегодня", "test")
    assert r and r.actions == ["add_task"] and "На сегодня" in r.text and "10:00" not in r.text
    t = next(t for t in tasks.list_tasks() if t.title.startswith("Сходить к нотариусу"))
    assert (t.due.hour, t.due.minute) == (23, 59) and t.due.date() == datetime.now().date()
    r = agent.rules("сделать ролик завтра в 9", "test")
    assert r and "Дедлайн завтра в 09:00" in r.text

    registry.run_tool("add_task", {"title": "Купить лампочки", "due": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")}, "test")
    assert (next(t for t in tasks.list_tasks(limit=50) if t.title == "Купить лампочки").due.hour) == 23
    registry.run_tool("add_task", {"title": "Написать Лене", "due": "сегодня"}, "test")
    assert (next(t for t in tasks.list_tasks(limit=50) if t.title == "Написать Лене").due.hour) == 23
    registry.run_tool("add_task", {"title": "Созвон с Пашей", "due": (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%dT11:30")}, "test")
    assert (next(t for t in tasks.list_tasks(limit=50) if t.title == "Созвон с Пашей").due.hour) == 11
    # напоминаний «остался час» по задаче на день не приходит
    tasks.add_task("Разобрать почту", datetime.now().replace(hour=23, minute=59, second=0, microsecond=0), source="test")
    assert all("Разобрать почту" not in text or "остался" not in text for _, text in tasks.due_task_reminders())


def test_edit_in_place_endpoints_task_and_link():
    """Правка без ассистента: GET одной задачи (для формы из календаря/главной), PUT задачи с «на день» ↔ «ко времени» ↔
    без срока, PUT ссылки (заголовок/комментарий/теги, адрес не меняется)."""
    import asyncio
    from core.services import brain_notes
    c = _client()
    t = _j(c.post("/api/tasks", json={"title": "Нотариус", "due": "2027-03-10T23:59"}))
    got = _j(c.get(f"/api/tasks/{t['id']}"))
    assert got["title"] == "Нотариус" and got["due"].startswith("2027-03-10T23:59")
    assert c.get("/api/tasks/999999").status_code == 404
    up = _j(c.put(f"/api/tasks/{t['id']}", json={"title": "Нотариус, взять 750р", "due": "2027-03-11T09:30", "priority": 1}))
    assert up["due"].startswith("2027-03-11T09:30") and up["priority"] == 1 and up["remind_stage"] == 0
    up = _j(c.put(f"/api/tasks/{t['id']}", json={"clear_due": True}))
    assert up["due"] is None
    async def _mk():
        return await brain_notes.add_link("https://example.com/x", "старый коммент", ["a"], source="test")
    l = asyncio.run(_mk())
    r = _j(c.put(f"/api/links/{l.id}", json={"title": "Пример", "comment": "  ", "tags": ["#дизайн", "ref", " "]}))
    assert r["title"] == "Пример" and r["comment"] is None and r["tags"] == "дизайн,ref" and r["url"] == "https://example.com/x"
    assert c.put("/api/links/999999", json={"title": "x"}).status_code == 404
