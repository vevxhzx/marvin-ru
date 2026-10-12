# -*- coding: utf-8 -*-
"""audit-wave4: роутеры не ходят в БД напрямую (mind/tasks).

Фиксирующие тесты: поведение эндпоинтов 1:1 + запрет прямых select в роутерах
(только перенесённые места, не всё скопом).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path


def _routers_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "core" / "api" / "routers"


def test_mind_router_has_no_direct_chatmessage_select():
    src = (_routers_dir() / "mind.py").read_text(encoding="utf-8")
    assert "select(ChatMessage)" not in src, "mind.py ходит в БД за ChatMessage напрямую"


def test_mind_router_has_no_direct_fact_select():
    src = (_routers_dir() / "mind.py").read_text(encoding="utf-8")
    assert "select(Fact)" not in src, "mind.py ходит в БД за Fact напрямую"


def test_tasks_router_has_no_direct_task_due_select():
    src = (_routers_dir() / "tasks.py").read_text(encoding="utf-8")
    assert "select(Task)" not in src, "tasks.py ходит в БД за Task напрямую"


def test_chat_history_roundtrip(_client):
    from core import db
    now = datetime.now()
    with db.session() as s:
        s.add(db.ChatMessage(role="user", text="привет", channel="web", created_at=now - timedelta(minutes=2)))
        s.add(db.ChatMessage(role="assistant", text="здравствуй", channel="web", created_at=now - timedelta(minutes=1)))
        s.commit()
    r = _client.get("/api/chat/history", params={"limit": 40})
    assert r.status_code == 200, r.text
    items = r.json()
    assert isinstance(items, list) and len(items) >= 2
    texts = [m["text"] for m in items]
    assert "привет" in texts and "здравствуй" in texts
    assert texts.index("привет") < texts.index("здравствуй"), "порядок — старые раньше"
    assert set(items[0]) >= {"id", "role", "text", "channel", "at"}


def test_events_tasks_too_filters_by_range(_client):
    from core.services import tasks as tasks_svc
    now = datetime.now().replace(second=0, microsecond=0)
    inside = (now + timedelta(days=1)).replace(hour=12, minute=0)
    outside = (now + timedelta(days=10)).replace(hour=12, minute=0)
    t_in = tasks_svc.add_task("волна4-внутри", inside, source="test")
    t_out = tasks_svc.add_task("волна4-снаружи", outside, source="test")
    t_nodue = tasks_svc.add_task("волна4-без-срока", None, source="test")
    r = _client.get("/api/events", params={
        "start": (now).isoformat(),
        "end": (now + timedelta(days=2)).isoformat(),
        "tasks_too": True,
    })
    assert r.status_code == 200, r.text
    rows = [e for e in r.json() if e.get("kind") == "task"]
    ids = {e["task_id"] for e in rows}
    assert t_in.id in ids, "задача внутри окна потерялась"
    assert t_out.id not in ids, "задача вне окна просочилась"
    assert t_nodue.id not in ids, "задача без срока просочилась"


def test_service_helpers_exist():
    from core.services import brain_notes, tasks as tasks_svc
    from core.services import memory as mem
    assert callable(getattr(brain_notes, "recent_chat", None)), "brain_notes.recent_chat нет"
    assert callable(getattr(tasks_svc, "list_tasks_with_due", None)), "tasks.list_tasks_with_due нет"
    assert callable(getattr(mem, "get_fact_by_source_ref", None)), "memory.get_fact_by_source_ref нет"


def test_remember_dedup_via_service(_client):
    from core.services import memory as mem
    nid = _client.post("/api/notes", json={"text": "волна4 дедуп заметки"}).json()["id"]
    first = _client.post(f"/api/notes/{nid}/remember")
    assert first.status_code == 200, first.text
    via_svc = mem.get_fact_by_source_ref(f"note:{nid}")
    assert via_svc is not None and via_svc.id == first.json()["id"]
    second = _client.post(f"/api/notes/{nid}/remember")
    assert second.json()["id"] == first.json()["id"], "дедуп сломался после переноса"
