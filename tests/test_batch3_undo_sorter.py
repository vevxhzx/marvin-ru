"""Батч 3: отмена и списки — TDD.

1) «отмени» после траты → clarify с названием, а не молчаливый откат.
2) undo в вебе не откатывает ТГ (или честно говорит).
3) пачка из 3 где 1 плохой → 2 записаны + 1 в «не понял», без отката всей пачки.

Должны падать на текущем коде (silent undo, cross-channel, silent/task-fallback).
"""
import asyncio
import os

import pytest

os.environ.setdefault("ASSISTANT_TEST", "1")

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


def _handle(text, ch):
    from core.brain import agent
    return asyncio.run(agent.handle(text, ch))


def test_undo_asks_what_not_silent(monkeypatch):
    """«отмени» после траты → clarify с названием, записи нет до «да»."""
    from core import db as _db
    ch = "b3-undo1"
    r1 = _handle("потратил 700 такси", ch)
    assert "add_expense" in r1.actions, (r1.actions, r1.text)
    with _db.session() as s:
        before = s.exec(_db.select(_db.Transaction)).all()
        assert len(before) == 1

    r = _handle("отмени", ch)
    # главное: не молчаливый откат, а уточнение ЧТО именно
    assert "clarify" in r.actions, (r.actions, r.text)
    assert "undo" not in r.actions, (r.actions, r.text)
    low = r.text.lower()
    assert "700" in low or "такси" in low or "трат" in low, r.text
    assert "да" in low and "нет" in low, r.text
    # до «да» запись цела
    with _db.session() as s:
        assert len(s.exec(_db.select(_db.Transaction)).all()) == 1

    # «да» — откатывает, «нет» — оставляет (проверяем ветку «да»)
    r2 = _handle("да", ch)
    assert "undo" in r2.actions, (r2.actions, r2.text)
    with _db.session() as s:
        assert s.exec(_db.select(_db.Transaction)).all() == []


def test_undo_web_does_not_rollback_tg():
    """undo в вебе не откатывает ТГ (или честно говорит про другой канал)."""
    from core import db as _db
    r1 = _handle("потратил 700 такси", "tg")
    assert "add_expense" in r1.actions, (r1.actions, r1.text)

    r = _handle("отмени", "web")
    with _db.session() as s:
        still = s.exec(_db.select(_db.Transaction)).all()
        assert len(still) == 1, "web-отмена снесла TG-запись — изоляция каналов сломана"
    # честно: либо «нечего», либо «другой канал», но НЕ «отменил»
    low = r.text.lower()
    assert ("нечего" in low or "друг" in low or "clarify" in r.actions), (r.actions, r.text)
    assert "отменил" not in low, (r.actions, r.text)


def test_batch_partial_failure_keeps_good(monkeypatch):
    """Пачка из 3 где 1 плохой → 2 записаны + 1 в «не понял», без отката всей пачки."""
    from core.brain import sorter
    from core.services import tasks

    async def fake(_text):
        return [
            {"kind": "task", "title": "Купить молоко"},
            {"kind": "foobar_unknown_kind", "title": "Какая-то фигня"},
            {"kind": "task", "title": "Позвонить маме"},
        ], "gemini"

    monkeypatch.setattr(sorter, "_ask_llm", fake)

    ch = "b3-batch"
    text = "купить молоко; позвонить маме; какая-то фигня"
    assert sorter.looks_like_batch(text), text
    r = _handle(text, ch)
    assert r is not None, "сортер ничего не вернул"
    low = r.text.lower()
    # 2 хорошие записаны
    titles = [t.title for t in tasks.list_tasks()]
    assert "Купить молоко" in titles, (titles, r.text)
    assert "Позвонить маме" in titles, (titles, r.text)
    # плохая — в «не понял», а не третьей задачей и не тихо потеряна
    assert "какая-то фигня" not in titles, (titles, r.text)
    assert ("не понял" in low or "не записал" in low), r.text
    assert "фигня" in low or "foobar" in low, r.text
