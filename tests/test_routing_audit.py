"""Аудит маршрутизации и бюджета контекста (17.09): каждая фраза идёт туда, куда должна, и локальная модель не получает
промпт больше окна. Без сети: модели не вызываются, проверяются только решения."""
import json
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402

from core import db  # noqa: E402
from core.brain import agent, llm, persona, sorter  # noqa: E402
from core.tools import registry  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlalchemy import event
    from sqlmodel import create_engine
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


def _route(t: str) -> str:
    if sorter.looks_like_batch(t):
        return "batch"
    if agent._disputed(t):
        return "judge"
    r = agent.rules(t, "test")
    if r is not None:
        return "rule:" + ",".join(r.actions)
    return "local" if agent.is_personal(t) else "cloud"


# ---------------------------------------------------------------- траты-шаблоны, которые уходили в модель на 50 с
def test_short_expense_with_event_like_category_word():
    for t in ("510 доставка еды", "доставка еды 510", "кино 600", "обед 450", "врач 2500", "запиши 510 доставка еды"):
        assert _route(t) == "rule:add_expense", t
    # а с временем — по-прежнему событие
    for t in ("обед в 14", "врач завтра в 10", "доставка в 18"):
        assert _route(t) == "rule:add_event", t


def test_vent_prefix_before_command_is_ignored():
    assert _route("ты еблан? запиши 510 доставка еды") == "rule:add_expense"
    assert _route("блин, запиши 700 такси") == "rule:add_expense"
    assert _route("ну ладно, добавь задачу позвонить маме") == "rule:add_task"
    # а «ты кто» / «ты знаешь Ваню?» — не команда, префикс не трогаем
    assert _route("ты кто") in ("cloud", "local")


# ---------------------------------------------------------------- разговор → облако, даже с цифрами
def test_conversation_goes_to_cloud():
    for t in ("как дела", "как думаешь, брать ли айфон 17", "сколько будет 15% от 3400",
              "слушай а что если я возьму кредит на 300 тысяч на камеру",
              "вот думаю что взять на завтрак через 10 минут закажу самокат как думаешь что может быть"):
        assert _route(t) == "cloud", t


def test_personal_stays_local():
    for t in ("хлеб, молоко, яйца", "разбери: доход 80к, аренда 30к, кредит 12к, хватит ли"):
        assert _route(t) == "local", t


# ---------------------------------------------------------------- рассказ о дне — не «календарь или задача?» и не судья
def test_story_with_date_is_not_clarify_or_judge():
    assert _route("Вовчик устал сегодня, 3 монтажа подряд") == "local"
    assert _route("сегодня 3 монтажа сдал, устал как собака") in ("local", "rule:add_note")   # прошедшее → заметка-память тоже ок
    assert _route("в пятницу что-то непонятное") == "rule:clarify"   # без глагола прошедшего — по-прежнему спрашиваем
    assert _route("заказ для Пятёрочки 25к до пятницы") == "local"     # заказ с суммой — add_order моделью, не задача


# ---------------------------------------------------------------- инструменты по смыслу фразы
def test_tools_schema_is_sliced_by_topic():
    all_tools = registry.tools_schema(with_cloud=True)
    assert len(all_tools) == 46   # +board_note, board_show (0.11)
    core = registry.tools_schema(with_cloud=True, text="кот опять сожрал провод")
    assert 15 <= len(core) <= 22 and all(t["function"]["name"] in registry.CORE_TOOLS + (registry.CLOUD_TOOL,) for t in core)
    money = {t["function"]["name"] for t in registry.tools_schema(with_cloud=True, text="сколько я должен Сберу")}
    assert "list_debts" in money and "pay_debt" in money
    free = {t["function"]["name"] for t in registry.tools_schema(with_cloud=True, text="заказ для Пятёрочки 25к до пятницы")}
    assert "person_card" in free and "add_order" not in free          # фриланс выключен → заказов нет, люди есть
    from core.services import pulse
    pulse.save_freelance_settings({"enabled": True})
    free = {t["function"]["name"] for t in registry.tools_schema(with_cloud=True, text="заказ для Пятёрочки 25к до пятницы")}
    assert "add_order" in free and "pomodoro" in free                  # фриланс включён → полный набор
    name = {t["function"]["name"] for t in registry.tools_schema(with_cloud=True, text="встреча с Леной в 15")}
    assert "person_card" in name
    # базовые всегда на месте
    for group in (core, ):
        names = {t["function"]["name"] for t in group}
        assert {"add_event", "add_task", "add_expense", "add_note", "search_notes", "undo_last"} <= names
    # набор без облачного инструмента
    assert all(t["function"]["name"] != registry.CLOUD_TOOL for t in registry.tools_schema(with_cloud=False, text="кот"))


def test_local_prompt_fits_default_window():
    """Характер (компактный) + правила + все схемы core-инструментов + история 6×600 < 8192 без ужатия."""
    sp = persona.system_prompt(compact=True)
    tools = json.dumps(registry.tools_schema(with_cloud=True, text="кот опять сожрал провод"), ensure_ascii=False)
    est = (len(sp) + 2200 + len(tools) + 6 * 600) // 3 + 200 + 512
    assert est < llm.OLLAMA_NUM_CTX, est


def test_fit_budget_drops_history_not_system(monkeypatch):
    monkeypatch.setattr(llm, "OLLAMA_NUM_CTX", 2048)
    msgs = [{"role": "system", "content": "S" * 1500}]
    for i in range(6):
        msgs.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"h{i} " * 200})
    msgs.append({"role": "user", "content": "ЧТО ТЫ ЗНАЕШЬ О ХОЗЯИНЕ:\n— кот Чиназес\nтекущая реплика\n(сейчас четверг)"})
    out = agent._fit_budget(msgs, [], "test")
    assert out[0]["content"].startswith("S")                      # системный промпт не тронут
    assert out[-1]["content"].endswith("(сейчас четверг)")       # текущая реплика на месте
    assert len(out) < 8                                          # история ужата
    est = sum(len(m["content"]) for m in out) // 3 + 200
    assert est <= 2048 - 512 - 250 or len(out) == 2


def test_history_excludes_current_message():
    import uuid
    msg = "текущая реплика " + uuid.uuid4().hex   # база тестов переживает прогоны — текст должен быть уникальным
    agent._log_chat("user", "старая реплика", "test")
    agent._log_chat("assistant", "старый ответ", "test")
    agent._log_chat("user", msg, "test")
    h = agent._history("test", current=msg)
    assert [x["text"] for x in h] == ["старая реплика", "старый ответ"]


def test_background_jobs_yield_to_user():
    llm.mark_user_active()
    assert llm.user_recent()
    assert not llm.user_recent(seconds=0)


def test_memory_block_tells_model_not_to_joke_about_facts():
    import inspect
    from core.services import memory
    src = inspect.getsource(memory.context)
    assert "НЕ упоминай" in src


# ---------------------------------------------------------------- 17.09 вечер: «…» вместо ответа, когда Ollama спит
def test_data_question_answered_by_tool_when_no_models(monkeypatch):
    """Ollama спит, облако говорит «личное» → раньше уходило «…». Теперь вопрос о данных отвечает инструмент напрямую."""
    import asyncio
    async def no_ollama(force=False):
        return False
    monkeypatch.setattr(llm, "ollama_available", no_ollama)
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    r = asyncio.run(agent.handle("какие задачи на сегодня?", "test"))
    assert "list_tasks" in r.actions and r.text.strip() not in ("", "…")


def test_cloud_says_local_but_no_local_gives_honest_reply(monkeypatch):
    import asyncio
    async def no_ollama(force=False):
        return False
    async def cloud_local(text, channel, explicit=True):
        return agent.Reply("", [], "local_needed")
    async def diag():
        return "Нет соединения с Ollama"
    monkeypatch.setattr(llm, "ollama_available", no_ollama)
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)
    monkeypatch.setattr(llm, "ollama_diagnose", diag)
    monkeypatch.setattr(agent, "via_gemini", cloud_local)
    r = asyncio.run(agent.handle("кот опять сожрал провод, запомни это про Чиназеса", "test"))
    assert r.via == "none" and "локальный мозг" in r.text and "…" != r.text.strip()


def test_remind_closer_to_day_of_month():
    """«напомни ближе к 30 числу сентября что надо не забыть вычесть жкх» → событие 30.09, название без мусора."""
    from datetime import datetime
    from core.brain.dates import parse_datetime
    dt, rest = parse_datetime("напомни ближе к 30 числу сентября что надо не забыть вычесть жкх из залога!", datetime(2026, 9, 17, 12, 0))
    assert dt and (dt.month, dt.day) == (9, 30)
    assert "ближе к" not in rest
    r = agent.rules("напомни ближе к 30 числу сентября что надо не забыть вычесть жкх из залога!", "test")
    assert r and "add_event" in r.actions and "Вычесть жкх" in r.text
    dt2, _ = parse_datetime("к 5 числу октября сдать отчёт", datetime(2026, 9, 17, 12, 0))
    assert dt2 and (dt2.month, dt2.day) == (10, 5)
