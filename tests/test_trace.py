"""Журнал работы: пишется на каждый ход, ловит падения инструментов, помечает исправления хозяина,
собирается в отчёт, чистится по сроку и не хранит секреты."""
import asyncio
import os

import pytest

os.environ["ASSISTANT_TEST"] = "1"

from core import db  # noqa: E402
from core.services import trace  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlmodel import create_engine
    from sqlalchemy import event
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    trace._cur.set(None)
    yield
    trace._cur.set(None)


def _offline(monkeypatch):
    """Ни Ollama, ни облака — фразы обрабатываются только правилами (детерминированно)."""
    from core.brain import llm
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(llm, "GEMINI_AUTO", False)

    async def avail(force=False):
        return False
    monkeypatch.setattr(llm, "ollama_available", avail)

    async def no_embed():
        return False
    monkeypatch.setattr(llm, "embed_available", no_embed)


# ---------------------------------------------------------------- запись
def test_run_is_recorded_for_every_phrase(monkeypatch):
    _offline(monkeypatch)
    from core.brain import agent
    r = asyncio.run(agent.handle("потратил 700 на такси", "web"))
    assert r.via == "rules"
    items = trace.recent()
    assert len(items) == 1
    row = items[0]
    assert row["route"] == "rules"
    assert row["channel"] == "web"
    assert "такси" in row["text"]
    assert row["ok"] is True
    assert row["ms"] >= 0
    assert "add_expense" in row["actions"]


def test_unanswered_phrase_is_marked_not_ok(monkeypatch):
    """Ни правил, ни модели — ответ «не понял». В журнале это провал, а не успех."""
    _offline(monkeypatch)
    from core.brain import agent
    r = asyncio.run(agent.handle("объясни теорему Гёделя простыми словами", "web"))
    assert r.via == "none"
    assert trace.recent()[0]["ok"] is False


def test_handle_crash_is_recorded_with_error(monkeypatch):
    _offline(monkeypatch)
    from core.brain import agent

    async def boom(text, channel):
        raise RuntimeError("что-то лопнуло")
    monkeypatch.setattr(agent, "_handle", boom)
    r = asyncio.run(agent.handle("привет", "tg"))
    assert r.via == "none"
    row = trace.recent()[0]
    assert row["ok"] is False
    assert "лопнуло" in row["error"]


# ---------------------------------------------------------------- инструменты
def test_tool_failure_is_visible_in_journal():
    """Падение инструмента модель видит как текст и может его замолчать — журнал запоминает честно."""
    from core.tools import registry
    trace.start("сколько я потратил", "web")
    out = registry.run_tool("нет_такого_инструмента", {}, "web")
    assert "Неизвестный инструмент" in out
    trace.finish("ollama", [])
    assert trace.recent()[0]["tools"] == ["нет_такого_инструмента!"]
    assert trace.tool_stats()[0]["fail"] == 1


def test_successful_tool_is_recorded_without_bang():
    from core.tools import registry
    trace.start("задача: купить молоко", "web")
    registry.run_tool("add_task", {"title": "Купить молоко"}, "web")
    trace.finish("ollama", ["add_task"])
    assert trace.recent()[0]["tools"] == ["add_task"]


def test_tool_call_outside_a_run_is_harmless():
    """Инструмент вызван из планировщика или из API, без разговорного хода — журнал молчит и не падает."""
    from core.tools import registry
    registry.run_tool("add_task", {"title": "Из планировщика"}, "system")
    assert trace.recent() == []


# ---------------------------------------------------------------- исправления
def test_undo_marks_previous_run_as_corrected(monkeypatch):
    _offline(monkeypatch)
    from core.brain import agent
    asyncio.run(agent.handle("потратил 700 на такси", "web"))
    assert trace.recent()[0]["corrected"] is False
    asyncio.run(agent.handle("отмени", "web"))
    corrected = [r for r in trace.recent() if r["corrected"]]
    assert len(corrected) == 1
    assert "такси" in corrected[0]["text"]


def test_lesson_marks_correction_but_mute_does_not(monkeypatch):
    _offline(monkeypatch)
    from core.brain import agent
    from core.services import judge
    asyncio.run(agent.handle("сайт 15000", "web"))
    judge.add_lesson("сайт 15000", "order", wrong="expense")
    assert sum(1 for r in trace.recent() if r["corrected"]) == 1

    asyncio.run(agent.handle("оплата Пятёрочки", "web"))
    judge.add_lesson("оплата Пятёрочки", "mute")   # «не надо про это» — просьба молчать, не ошибка
    assert sum(1 for r in trace.recent() if r["corrected"]) == 1


def test_lesson_marks_the_run_it_belongs_to_not_a_neighbour(monkeypatch):
    """Баг, найденный живым прогоном: урок про «сайт 15000» помечал исправленным ход про «потратил на еду»,
    потому что спорная фраза ничего не записала и поиск откатывался на предыдущую невинную строку."""
    _offline(monkeypatch)
    from core.brain import agent
    from core.services import judge
    asyncio.run(agent.handle("потратил 1200 на еду", "tg"))
    asyncio.run(agent.handle("сайт 15000", "tg"))
    judge.add_lesson("сайт 15000", "order", wrong="expense")
    corrected = [r for r in trace.recent() if r["corrected"]]
    assert len(corrected) == 1
    assert "сайт" in corrected[0]["text"]


def test_lesson_for_unknown_phrase_marks_nothing(monkeypatch):
    """Не нашли ход по фразе — лучше недосчитать исправление, чем повесить ошибку на чужую строку."""
    _offline(monkeypatch)
    from core.brain import agent
    from core.services import judge
    asyncio.run(agent.handle("потратил 1200 на еду", "tg"))
    judge.add_lesson("фраза, которой в журнале нет", "order")
    assert [r for r in trace.recent() if r["corrected"]] == []


# ---------------------------------------------------------------- отчёт и статистика
def test_report_counts_and_text(monkeypatch):
    _offline(monkeypatch)
    from core.brain import agent
    for phrase in ("потратил 700 на такси", "задача: сдать отчёт", "потратил 300 на кофе"):
        asyncio.run(agent.handle(phrase, "web"))
    asyncio.run(agent.handle("объясни квантовую механику", "web"))   # никто не ответит → провал

    rep = trace.report(7)
    assert rep["n"] == 4
    assert rep["failed"] == 1
    assert rep["routes"]["rules"]["n"] == 3
    assert rep["routes"]["none"]["n"] == 1

    txt = trace.report_text(7)
    assert "4 обращений" in txt
    assert "Не справился: 1" in txt


def test_route_stats_measure_time_per_route():
    for route, ms in (("ollama", 200), ("ollama", 400), ("gemini", 50)):
        trace.start("тест", "web")
        trace.finish(route, [])
        with db.session() as s:
            row = s.exec(db.select(db.Run).order_by(db.Run.id.desc())).first()
            row.ms = ms
            s.add(row); s.commit()
    st = trace.route_stats(14)
    assert st["ollama"]["n"] == 2
    assert st["ollama"]["ms_avg"] == 300
    assert st["gemini"]["ms_avg"] == 50


def test_weekly_block_is_silent_on_a_calm_week(monkeypatch):
    _offline(monkeypatch)
    from core.brain import agent
    for i in range(6):
        asyncio.run(agent.handle(f"потратил {100 + i} на кофе", "web"))
    assert trace.weekly_block() == []   # всё прошло гладко — докладывать не о чем

    asyncio.run(agent.handle("потратил 700 на такси", "web"))
    asyncio.run(agent.handle("отмени", "web"))
    assert trace.weekly_block()         # появилось исправление — доклад есть


def test_self_report_command_answers_from_journal(monkeypatch):
    _offline(monkeypatch)
    from core.brain import agent
    asyncio.run(agent.handle("потратил 700 на такси", "web"))
    r = asyncio.run(agent.handle("как ты работал", "web"))
    assert r.actions == ["self_report"]
    assert "обращений" in r.text


# ---------------------------------------------------------------- приватность и уборка
def test_secrets_are_not_stored_in_journal(monkeypatch):
    _offline(monkeypatch)
    from core.brain import agent
    asyncio.run(agent.handle("запомни пароль от вайфая qwerty12345", "web"))
    assert "qwerty12345" not in trace.recent()[0]["text"]


def test_long_text_is_truncated(monkeypatch):
    _offline(monkeypatch)
    from core.brain import agent
    asyncio.run(agent.handle("мысль: " + "а" * 1000, "web"))
    assert len(trace.recent()[0]["text"]) <= trace.TEXT_MAX


def test_disabled_trace_writes_nothing(monkeypatch):
    monkeypatch.setattr(trace, "enabled", lambda: False)
    _offline(monkeypatch)
    from core.brain import agent
    asyncio.run(agent.handle("потратил 700 на такси", "web"))
    assert trace.recent() == []


def test_cleanup_removes_old_rows():
    from datetime import datetime, timedelta
    trace.start("старое", "web"); trace.finish("rules", [])
    trace.start("свежее", "web"); trace.finish("rules", [])
    with db.session() as s:
        old = s.exec(db.select(db.Run).order_by(db.Run.id)).first()
        old.created_at = datetime.now() - timedelta(days=90)
        s.add(old); s.commit()
    assert trace.cleanup(60) == 1
    left = trace.recent()
    assert len(left) == 1 and left[0]["text"] == "свежее"


def test_api_endpoints(monkeypatch):
    _offline(monkeypatch)
    from fastapi.testclient import TestClient
    from core.api.app import app
    from core.brain import agent
    asyncio.run(agent.handle("потратил 700 на такси", "web"))
    with TestClient(app) as c:
        items = c.get("/api/runs").json()["items"]
        assert items and items[0]["route"] == "rules"
        rep = c.get("/api/runs/report?days=7").json()
        assert rep["n"] == 1 and "обращений" in rep["text"]


def test_selfreport_phrases_with_period_word():
    """«как ты работал сегодня?» без предлога «за» — тоже вопрос о журнале, а «как ты работал с Леной» — нет."""
    from core.brain.agent import SELFREPORT_RX as R
    assert R.match("как ты работал?") and R.match("как ты работал сегодня?") and R.match("отчёт о себе за месяц")
    assert R.match("где ты тупил за неделю") and R.match("как ты работал за последнюю неделю")
    assert not R.match("как ты работал с Леной") and not R.match("как ты работал над сайтом?")
