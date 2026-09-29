"""Контракт инструмента: результат проверяется по базе, а не по строке, которую вернул инструмент.

Сценарии уровня «фраза → агент → инструменты → проверенный результат»:
 1. успех;
 2. инструмент упал (исключение);
 3. упала модель после успешной записи;
 4. инструмент «отработал», но в базу ничего не положил — и модель врёт «записал»;
 5. многошаговая задача (несколько инструментов подряд), часть провалилась;
 6. действие, которое нельзя выполнять без подтверждения хозяина.
"""
import asyncio
import os

import pytest

os.environ["ASSISTANT_TEST"] = "1"

from core import db  # noqa: E402
from core.tools import registry  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlmodel import create_engine
    from sqlalchemy import event
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    from core.services import trace
    trace._cur.set(None)
    yield
    trace._cur.set(None)


def _brain(monkeypatch, script):
    """script(n, messages) -> dict ответа модели. n — номер вызова, начиная с 1."""
    from core.brain import agent, llm
    calls = {"n": 0}

    async def fake_chat(messages, tools=None, **kw):
        calls["n"] += 1
        return script(calls["n"], messages)

    async def _up(force=False):
        return True

    monkeypatch.setattr(llm, "ollama_chat", fake_chat)
    monkeypatch.setattr(llm, "ollama_available", _up)
    monkeypatch.setattr(llm, "MODE", "hybrid")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(llm, "GEMINI_AUTO", False)
    monkeypatch.setattr(agent, "_history", lambda *a, **k: [])

    async def no_ctx(_t):
        return ""
    monkeypatch.setattr(agent.memory, "context", no_ctx)
    return calls


def _tc(name, **args):
    return {"content": "", "tool_calls": [{"name": name, "arguments": args}]}


def _say(text):
    return {"content": text, "tool_calls": []}


# ---------------------------------------------------------------- 1. успех
def test_successful_call_is_verified_against_the_database(monkeypatch):
    from core.brain import agent
    _brain(monkeypatch, lambda n, m: _tc("add_expense", amount=700, note="такси") if n == 1 else _say("Минус 700 на такси, записал."))
    r = asyncio.run(agent.via_ollama("потратил 700 на такси", "web"))
    assert r.actions == ["add_expense"]
    assert "⚠️" not in r.text
    from core.services import finance
    assert finance.summary(1)["spent"] == 700


def test_call_returns_what_was_written():
    res = registry.call("add_task", {"title": "Смонтировать ролик"}, "web")
    assert res.ok and res.verified is True
    assert res.ref_table == "task" and res.ref_id
    assert res.risk == "write"
    assert res.for_model() == res.text


# ---------------------------------------------------------------- 2. инструмент упал
def test_tool_exception_is_a_failure_not_a_string(monkeypatch):
    from core.services import tasks

    def boom(*a, **k):
        raise RuntimeError("диск переполнен")
    monkeypatch.setattr(tasks, "add_task", boom)
    res = registry.call("add_task", {"title": "Что-нибудь"}, "web")
    assert res.ok is False
    assert "диск переполнен" in res.error
    assert "ЗАПРЕЩЕНО" in res.for_model()          # модель получает недвусмысленный запрет врать
    assert res.retryable is False                   # запись не повторяем автоматически — иначе дубль


def test_agent_does_not_say_done_when_tool_crashed(monkeypatch):
    from core.brain import agent
    from core.services import tasks

    def boom(*a, **k):
        raise RuntimeError("база недоступна")
    monkeypatch.setattr(tasks, "add_task", boom)
    _brain(monkeypatch, lambda n, m: _tc("add_task", title="Полить цветы") if n == 1 else _say("Готово, задача добавлена."))
    r = asyncio.run(agent.via_ollama("задача: полить цветы", "web"))
    assert r.actions == []
    assert "Не записал" in r.text
    assert "добавлена" not in r.text


# ---------------------------------------------------------------- 3. упала модель
def test_model_crash_after_successful_write_keeps_the_result(monkeypatch):
    """Регрессия на существующее поведение: инструмент записал, модель умерла на финальной фразе —
    ответ всё равно должен быть, иначе человек повторит команду и получит дубль."""
    from core.brain import agent

    def script(n, m):
        if n == 1:
            return _tc("add_expense", amount=700, note="такси")
        raise RuntimeError("Ollama: connection reset")
    _brain(monkeypatch, script)
    r = asyncio.run(agent.via_ollama("потратил 700 на такси", "web"))
    assert r is not None and r.actions == ["add_expense"]
    assert "700" in r.text


def test_model_crash_before_any_write_returns_none(monkeypatch):
    from core.brain import agent

    def script(n, m):
        raise RuntimeError("Ollama лежит")
    _brain(monkeypatch, script)
    assert asyncio.run(agent.via_ollama("потратил 700 на такси", "web")) is None


# ---------------------------------------------------------------- 4. инструмент «ответил», но не записал
def test_soft_failure_is_caught_by_readback():
    """add_event с непонятой датой возвращает вежливую строку и НЕ пишет в базу.
    Раньше это было неотличимо от успеха — теперь ловится чтением ActionLog."""
    res = registry.call("add_event", {"title": "Встреча", "start": "когда-нибудь потом"}, "web")
    assert res.ok is False
    assert res.verified is False
    assert res.retryable is True                    # аргумент плохой — модель может поправиться
    assert "Не понял дату" in res.error


def test_agent_replaces_a_lying_answer_with_the_truth(monkeypatch):
    from core.brain import agent
    from sqlmodel import select
    _brain(monkeypatch, lambda n, m: _tc("add_event", title="Встреча с Димой", start="как-нибудь")
           if n == 1 else _say("Записал встречу с Димой, сэр."))
    r = asyncio.run(agent.via_ollama("встреча с Димой как-нибудь", "web"))
    assert r.actions == []
    assert "Не записал" in r.text and "дату" in r.text
    with db.session() as s:                          # и в базе действительно пусто
        assert s.exec(select(db.Event)).first() is None


def test_failed_tool_does_not_trigger_the_old_guess_and_write(monkeypatch):
    """Старый путь «модель соврала → запишем сами по регексу» не должен срабатывать поверх упавшего инструмента:
    иначе на неразобранную дату мы молча заведём заметку, которую никто не просил."""
    from core.brain import agent
    from sqlmodel import select
    _brain(monkeypatch, lambda n, m: _tc("add_event", title="Встреча", start="ага")
           if n == 1 else _say("Сохранил, сэр."))
    asyncio.run(agent.via_ollama("встреча ага", "web"))
    with db.session() as s:
        assert s.exec(select(db.Note)).first() is None
        assert s.exec(select(db.Task)).first() is None


# ---------------------------------------------------------------- 5. несколько шагов, часть провалилась
def test_multi_step_task_reports_partial_success_honestly(monkeypatch):
    from core.brain import agent

    def script(n, m):
        if n == 1:
            return _tc("add_expense", amount=1200, note="еда")
        if n == 2:
            return _tc("add_event", title="Зубной", start="потом когда-то")
        return _say("Всё записал, сэр.")
    _brain(monkeypatch, script)
    r = asyncio.run(agent.via_ollama("потратил 1200 на еду и зубной потом когда-то", "web"))
    assert r.actions == ["add_expense"]              # только то, что реально легло
    assert "⚠️ Но не всё" in r.text
    assert "дату" in r.text
    from core.services import finance
    assert finance.summary(1)["spent"] == 1200     # успешная часть не откатывается


def test_multi_step_all_successful_has_no_warning(monkeypatch):
    from core.brain import agent

    def script(n, m):
        if n == 1:
            return _tc("add_expense", amount=1200, note="еда")
        if n == 2:
            return _tc("add_task", title="Записаться к зубному")
        return _say("Готово, сэр.")
    _brain(monkeypatch, script)
    r = asyncio.run(agent.via_ollama("потратил 1200 на еду, записаться к зубному", "web"))
    assert r.actions == ["add_expense", "add_task"]
    assert "⚠️" not in r.text


def test_failure_corrected_by_retry_is_not_reported(monkeypatch):
    """Модель ошиблась с датой, инструмент отказал, модель прислала ISO и всё записалось.
    Человеку не за что извиняться — предупреждения быть не должно."""
    from core.brain import agent

    def script(n, m):
        if n == 1:
            return _tc("add_event", title="Зубной", start="ну как-нибудь")
        if n == 2:
            return _tc("add_event", title="Зубной", start="2026-10-02T10:00")
        return _say("Записал, сэр.")
    _brain(monkeypatch, script)
    r = asyncio.run(agent.via_ollama("зубной", "web"))
    assert r.actions == ["add_event"]
    assert "⚠️" not in r.text and "Не записал" not in r.text


def test_read_tool_failure_does_not_wipe_the_answer(monkeypatch):
    """Упал только читающий инструмент — ответ модели мог быть полезным, затирать его нельзя."""
    from core.brain import agent
    from core.services import finance

    def boom(*a, **k):
        raise RuntimeError("база занята")
    monkeypatch.setattr(finance, "summary", boom)
    _brain(monkeypatch, lambda n, m: _tc("finance_summary", days=30) if n == 1 else _say("Похоже, за месяц вы уложились в бюджет."))
    r = asyncio.run(agent.via_ollama("как у меня с деньгами", "web"))
    assert "уложились в бюджет" in r.text
    assert "цифры могут быть неполными" in r.text


# ---------------------------------------------------------------- 6. нужно подтверждение
def test_destructive_tool_asks_before_doing(monkeypatch):
    """«Удали событие» — необратимо. Раньше подтверждения требовали только крупные суммы."""
    from core.brain import agent
    from core.services import calendar
    from datetime import datetime, timedelta
    calendar.add_event("Созвон с Димой", datetime.now() + timedelta(days=1))
    _brain(monkeypatch, lambda n, m: _tc("delete_event", query="Созвон") if n == 1 else _say("Удалил."))
    r = asyncio.run(agent.via_ollama("удали созвон", "web"))
    assert "clarify" in r.actions
    assert "Точно удалить" in r.text
    assert calendar.find_event("Созвон") is not None   # ничего ещё не удалено


def test_destructive_tool_runs_after_yes(monkeypatch):
    from core.brain import agent
    from core.services import calendar
    from datetime import datetime, timedelta
    calendar.add_event("Созвон с Димой", datetime.now() + timedelta(days=1))
    _brain(monkeypatch, lambda n, m: _tc("delete_event", query="Созвон") if n == 1 else _say("Удалил."))
    asyncio.run(agent.via_ollama("удали созвон", "web"))
    r = agent._resolve_confirm("да", "web")
    assert r is not None
    assert calendar.find_event("Созвон") is None


def test_big_amount_still_asks(monkeypatch):
    """Регрессия: подтверждение по сумме работает как раньше."""
    from core.brain import agent
    _brain(monkeypatch, lambda n, m: _tc("add_expense", amount=150000, note="ноутбук") if n == 1 else _say("Записал."))
    r = asyncio.run(agent.via_ollama("потратил 150000 на ноутбук", "web"))
    assert "clarify" in r.actions
    from core.services import finance
    assert finance.summary(1)["spent"] == 0


# ---------------------------------------------------------------- зацикливание и безопасность
def test_model_looping_on_a_failing_tool_terminates_honestly(monkeypatch):
    """Модель упрямо повторяет один и тот же провальный вызов. Ход обязан закончиться, ничего не записав,
    и не должен отчитаться об успехе."""
    from core.brain import agent
    from sqlmodel import select
    calls = _brain(monkeypatch, lambda n, m: _tc("add_event", title="Встреча", start="никогда"))
    r = asyncio.run(agent.via_ollama("встреча никогда", "web"))
    assert calls["n"] <= 6                       # цикл ограничен, а не крутится бесконечно
    assert r.actions == []
    assert "Не записал" in r.text or "не" in r.text.lower()
    with db.session() as s:
        assert s.exec(select(db.Event)).first() is None


def test_duplicate_guard_does_not_claim_success_for_a_failed_call(monkeypatch):
    """Страж дублей раньше отвечал «уже выполнено» и на провалившийся вызов — модель верила и врала дальше."""
    from core.brain import agent
    seen = []

    def script(n, m):
        if m and m[-1].get("role") == "tool":
            seen.append(m[-1]["content"])
        if n <= 2:
            return _tc("add_task", title="")      # пустой title → инструмент откажет
        return _say("Готово.")
    _brain(monkeypatch, script)
    r = asyncio.run(agent.via_ollama("задача", "web"))
    assert not any("Уже выполнено выше" in s for s in seen)
    assert r.actions == []


def test_note_content_cannot_make_assistant_delete_without_confirmation(monkeypatch):
    """Инъекция через сохранённый текст: даже если модель решит вызвать удаление, без «да» ничего не удалится."""
    from core.brain import agent
    from core.services import calendar
    from datetime import datetime, timedelta
    calendar.add_event("Важный созвон", datetime.now() + timedelta(days=2))
    _brain(monkeypatch, lambda n, m: _tc("delete_event", query="Важный") if n == 1 else _say("Удалил всё."))
    r = asyncio.run(agent.via_ollama("прочитай заметку", "web"))
    assert "clarify" in r.actions
    assert calendar.find_event("Важный") is not None


# ---------------------------------------------------------------- entity-editing инструменты (2-й проход)
def test_set_budget_on_unknown_category_is_a_failure():
    res = registry.call("set_budget", {"category": "Такой категории нет", "amount": 5000}, "web")
    assert res.ok is False and res.verified is False


def test_set_budget_success_is_verified_by_readback():
    from core.services import finance
    finance.category_by_word  # noqa: B018 — категория «Еда» есть по умолчанию
    res = registry.call("set_budget", {"category": "еда", "amount": 15000}, "web")
    assert res.ok and res.verified is True


def test_set_budget_idempotent_call_is_not_a_false_failure():
    """Тот самый случай, из-за которого я изначально не рискнул трогать эти инструменты: лимит и так уже такой."""
    registry.call("set_budget", {"category": "еда", "amount": 15000}, "web")
    res = registry.call("set_budget", {"category": "еда", "amount": 15000}, "web")
    assert res.ok and res.verified is True


def test_edit_note_on_missing_note_is_a_failure():
    res = registry.call("edit_note", {"query": "заметки с таким текстом нет", "append": "х"}, "web")
    assert res.ok is False and res.verified is False


def test_edit_note_append_is_verified():
    from core.services import brain_notes
    brain_notes.add_note("Идея для рилса про монтаж")
    res = registry.call("edit_note", {"query": "рилса", "append": "снять на телефон"}, "web")
    assert res.ok and res.verified is True


def test_move_event_on_missing_event_is_a_failure():
    res = registry.call("move_event", {"query": "такого события нет", "start": "2026-10-01T10:00"}, "web")
    assert res.ok is False and res.verified is False


def test_move_event_success_is_verified():
    from core.services import calendar
    from datetime import datetime, timedelta
    calendar.add_event("Созвон с Димой", datetime.now() + timedelta(days=1))
    res = registry.call("move_event", {"query": "Созвон", "start": "2026-10-05T18:00"}, "web")
    assert res.ok and res.verified is True
    assert calendar.find_event("Созвон").start.isoformat().startswith("2026-10-05T18:00")


def test_move_event_unparseable_time_is_caught_instead_of_silent_noop(monkeypatch):
    """Баг, найденный при проектировании этой проверки: move_event молча оставлял старое время
    (update_event трактует start=None как «не менять»), а текст всё равно был «Готово»."""
    from core.services import calendar
    from datetime import datetime, timedelta
    orig = datetime.now() + timedelta(days=1)
    calendar.add_event("Созвон с Димой", orig)
    res = registry.call("move_event", {"query": "Созвон", "start": "качественно и по любви"}, "web")
    assert res.ok is False and res.verified is False
    assert calendar.find_event("Созвон").start.replace(microsecond=0) == orig.replace(microsecond=0)


def test_move_event_survives_a_rename(monkeypatch):
    """Переименовали и подвинули одним вызовом — проверка ищет цель по id, снятому до вызова, а не по старому query."""
    from core.services import calendar
    from datetime import datetime, timedelta
    calendar.add_event("Созвон с Димой", datetime.now() + timedelta(days=1))
    res = registry.call("move_event", {"query": "Созвон", "title": "Планёрка", "start": "2026-10-05T18:00"}, "web")
    assert res.ok and res.verified is True


def test_update_order_on_missing_order_is_a_failure():
    res = registry.call("update_order", {"query": "такого заказа нет", "status": "done"}, "web")
    assert res.ok is False and res.verified is False


def test_update_order_status_is_verified():
    from core.services import orders
    o = orders.add_order("Ролик для Headway", client="Headway", price=15000)
    res = registry.call("update_order", {"query": "Headway", "status": "review"}, "web")
    assert res.ok and res.verified is True
    assert orders.get_order(o.id).status == "review"


def test_add_person_is_now_verified_and_not_a_silent_gap():
    """add_person создаёт Client, но никогда не писал в ActionLog — раньше это было слепой зоной и для журнала,
    и для верификации; теперь проверяется напрямую через find_person."""
    res = registry.call("add_person", {"name": "Анна Смирнова"}, "web")
    assert res.ok and res.verified is True
    from core.services import people
    assert people.find_person("Анна Смирнова") is not None


def test_add_person_is_idempotency_safe():
    registry.call("add_person", {"name": "Анна Смирнова"}, "web")
    res = registry.call("add_person", {"name": "Анна Смирнова"}, "web")   # тот же человек второй раз
    assert res.ok and res.verified is True


def test_set_balance_and_pomodoro_are_intentionally_unverified():
    """Документируем, а не молчим: почему эти два инструмента не в AFTER_CHECK."""
    assert "set_balance" not in registry.AFTER_CHECK
    assert "pomodoro" not in registry.AFTER_CHECK
    res = registry.call("set_balance", {"account": "Основной", "balance": 12345}, "web")
    assert res.ok and res.verified is None   # нечего сверять — но и не ложный провал


# ---------------------------------------------------------------- проверка не-создающих инструментов
def test_complete_task_is_verified_by_reading_it_back():
    from core.services import tasks
    t = tasks.add_task("Смонтировать ролик")
    res = registry.call("complete_task", {"query": "ролик"}, "web")
    assert res.ok and res.verified is True
    assert tasks.find_task(t.id).done is True


def test_complete_task_on_missing_task_is_a_failure():
    res = registry.call("complete_task", {"query": "такой задачи нет"}, "web")
    assert res.ok is False and res.verified is False


# ---------------------------------------------------------------- обратная совместимость и журнал
def test_run_tool_still_returns_plain_text():
    assert "Задача" in registry.run_tool("add_task", {"title": "Купить молоко"}, "web")
    assert "Неизвестный инструмент" in registry.run_tool("нет_такого", {}, "web")
    assert "Не понял дату" in registry.run_tool("add_event", {"title": "X", "start": "абвгд"}, "web")


def test_journal_records_soft_failure_as_failure():
    from core.services import trace
    trace.start("встреча когда-нибудь", "web")
    registry.call("add_event", {"title": "Встреча", "start": "когда-нибудь"}, "web")
    trace.finish("ollama", [])
    assert trace.recent()[0]["tools"] == ["add_event!"]
    assert trace.tool_stats()[0]["fail"] == 1


def test_risk_levels():
    assert registry.risk_of("list_tasks") == "read"
    assert registry.risk_of("add_task") == "write"
    assert registry.risk_of("add_expense") == "money"
    assert registry.risk_of("delete_event") == "destructive"
