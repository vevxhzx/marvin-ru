"""Топ-фразы хозяина на временной БД: где бот гадает мимо spec.

Spec (утверждён):
- деньги неоднозначные («отдал Ване», «перевёл без счетов», «пришёл аванс»)
  → уточняющий вопрос, не запись;
- ночь 0–5 без маркера → уточнение;
- «отмени» → уточнение что именно;
- «в 4» днём → PM; «вечером» → 19:00;
- непонятное дата/время → «календарь или задача?».

По 3–5 фраз на группы: траты, переводы, долги, задачи, встречи, «напомни»,
заметки, «что сегодня/на неделе», «сколько денег», голосовые расшифровки.
Вызов — agent.handle(text, channel) через asyncio.run на fresh_db,
ассерты — на Reply.actions и текст-маркеры («?»/clarify/название инструмента).
"""
import asyncio
import os
from datetime import datetime, timedelta

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


def _offline(monkeypatch):
    """Выключить LLM полностью: поведение только правил (детерминировано)."""
    from core.brain import llm
    from core.services import judge as _judge

    async def _no_false(*a, **k):
        return False

    async def _no_none(*a, **k):
        return None

    async def _no_empty(*a, **k):
        return ""

    monkeypatch.setattr(_judge, "enabled", lambda: True)
    monkeypatch.setattr(llm, "ollama_available", _no_false)
    monkeypatch.setattr(llm, "embed_available", _no_false)
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(llm, "ollama_chat", _no_none)
    monkeypatch.setattr(llm, "cloud_chat", _no_none)
    monkeypatch.setattr(llm, "small_chat", _no_empty)


def _handle(text, ch):
    from core.brain import agent
    return asyncio.run(agent.handle(text, ch))


def _no_money_written():
    with db.session() as s:
        assert s.exec(db.select(db.Transaction)).all() == []
        assert s.exec(db.select(db.Debt)).all() == []


# ---------------------------------------------------------------- траты
@pytest.mark.parametrize("phrase", [
    "потратил 700 на такси",
    "купил кофе 350",
    "обед 450",
    "заплатил 2000 за интернет",
])
def test_spend_writes_expense(monkeypatch, phrase):
    _offline(monkeypatch)
    r = _handle(phrase, f"spend-{hash(phrase) % 9999}")
    assert "add_expense" in r.actions, (phrase, r.actions, r.text)
    with db.session() as s:
        tx = s.exec(db.select(db.Transaction)).all()
        assert len(tx) == 1 and tx[0].kind == "expense", [(t.kind, t.amount) for t in tx]


# ---------------------------------------------------------------- переводы
def test_transfer_bare_asks_accounts(monkeypatch):
    _offline(monkeypatch)
    r = _handle("перевёл 5000", "tr-bare")
    assert "clarify" in r.actions, (r.actions, r.text)
    low = r.text.lower()
    assert "какой" in low and "сч" in low, r.text
    _no_money_written()


def test_transfer_explicit_accounts_writes(monkeypatch):
    _offline(monkeypatch)
    r = _handle("перевёл 5000 со сбера на наличные", "tr-exp")
    assert "add_transfer" in r.actions, (r.actions, r.text)


def test_transfer_cash_withdraw_writes(monkeypatch):
    _offline(monkeypatch)
    r = _handle("снял 3000 наличных", "tr-cash")
    assert "add_transfer" in r.actions, (r.actions, r.text)


def test_transfer_to_person_asks_not_writes(monkeypatch):
    """«перевёл Ване 2000» — перевод человеку без счетов: спор (трата/долг/доход),
    а не молчаливая трата. Было: add_expense (TRANSFER_RX гасил спор)."""
    _offline(monkeypatch)
    r = _handle("перевёл Ване 2000", "tr-person")
    assert "clarify" in r.actions, (r.actions, r.text)
    low = r.text.lower()
    assert "трата" in low and "долг" in low, r.text
    _no_money_written()


def test_transfer_amount_then_person_asks(monkeypatch):
    """«перевёл 5000 маме» — имя после суммы, счетов нет: тоже вопрос, не запись."""
    _offline(monkeypatch)
    r = _handle("перевёл 5000 маме", "tr-person2")
    assert "clarify" in r.actions, (r.actions, r.text)
    _no_money_written()


# ---------------------------------------------------------------- долги
@pytest.mark.parametrize("phrase", ["отдал Ване 2000", "дал маме 5к"])
def test_debt_ambiguous_asks(monkeypatch, phrase):
    _offline(monkeypatch)
    r = _handle(phrase, f"debt-a-{hash(phrase) % 9999}")
    assert "clarify" in r.actions, (phrase, r.actions, r.text)
    assert any(w in r.text.lower() for w in ("трата", "долг", "доход")), r.text
    _no_money_written()


def test_debt_explicit_writes(monkeypatch):
    _offline(monkeypatch)
    r = _handle("долг Сберу 120к плачу 8к 25-го", "debt-exp")
    assert "add_debt" in r.actions, (r.actions, r.text)
    with db.session() as s:
        ds = s.exec(db.select(db.Debt)).all()
        assert len(ds) == 1 and ds[0].remaining == 120_000


def test_debt_owe_writes(monkeypatch):
    _offline(monkeypatch)
    r = _handle("должен Ване 5000", "debt-owe")
    assert "add_debt" in r.actions, (r.actions, r.text)


def test_income_bare_asks_order_or_income(monkeypatch):
    _offline(monkeypatch)
    r = _handle("получил 15000", "debt-inc")
    assert "clarify" in r.actions, (r.actions, r.text)
    low = r.text.lower()
    assert "заказ" in low and "доход" in low, r.text
    _no_money_written()


# ---------------------------------------------------------------- задачи
def test_task_action_verb_pm(monkeypatch):
    """«позвонить маме в 5» → задача 17:00, не событие и не вопрос."""
    from core.services import calendar, tasks
    _offline(monkeypatch)
    r = _handle("позвонить маме в 5", "task-pm")
    assert "add_task" in r.actions and "add_event" not in r.actions, (r.actions, r.text)
    ts = tasks.list_tasks()
    assert len(ts) == 1 and ts[0].due is not None and ts[0].due.hour == 17, [(t.title, t.due) for t in ts]
    assert calendar.list_events(limit=50) == []


@pytest.mark.parametrize("phrase", ["купить молоко", "задача: починить полку", "надо починить полку"])
def test_task_plain_writes(monkeypatch, phrase):
    from core.services import tasks
    _offline(monkeypatch)
    r = _handle(phrase, f"task-{hash(phrase) % 9999}")
    assert "add_task" in r.actions, (phrase, r.actions, r.text)
    assert len(tasks.list_tasks()) == 1


def test_task_with_date_writes(monkeypatch):
    from core.services import tasks
    _offline(monkeypatch)
    r = _handle("надо купить молоко завтра в 10", "task-date")
    assert "add_task" in r.actions, (r.actions, r.text)
    ts = tasks.list_tasks()
    assert len(ts) == 1 and ts[0].due is not None
    assert ts[0].due.date() == (datetime.now() + timedelta(days=1)).date() and ts[0].due.hour == 10


# ---------------------------------------------------------------- встречи
def test_event_single_digit_is_pm(monkeypatch):
    """«встреча сегодня в 4» → 16:00 (spec: «в 4» днём → PM)."""
    from core.brain import agent  # noqa: F401
    from core.services import calendar
    _offline(monkeypatch)
    r = _handle("встреча сегодня в 4", "ev-pm")
    assert "add_event" in r.actions, (r.actions, r.text)
    ev = calendar.find_event("встреча")
    assert ev is not None and ev.start.hour == 16, (ev.start if ev else None)


def test_event_tomorrow_morning(monkeypatch):
    from core.services import calendar
    _offline(monkeypatch)
    r = _handle("встреча завтра в 10", "ev-tom")
    assert "add_event" in r.actions, (r.actions, r.text)
    ev = calendar.find_event("встреча")
    assert ev is not None and ev.start.hour == 10, (ev.start if ev else None)
    assert ev.start.date() == (datetime.now() + timedelta(days=1)).date(), ev.start


def test_event_evening_is_19(monkeypatch):
    """«вечером встреча с Ваней» → 19:00 (spec: «вечером» → 19:00)."""
    from core.services import calendar
    _offline(monkeypatch)
    r = _handle("вечером встреча с Ваней", "ev-eve")
    assert "add_event" in r.actions, (r.actions, r.text)
    ev = calendar.find_event("Ваней")
    assert ev is not None and ev.start.hour == 19, (ev.start if ev else None)


def test_event_dinner_seven_pm(monkeypatch):
    from core.services import calendar
    _offline(monkeypatch)
    r = _handle("ужин в 7 вечера", "ev-din")
    assert "add_event" in r.actions, (r.actions, r.text)
    ev = calendar.find_event("ужин")
    assert ev is not None and ev.start.hour == 19, (ev.start if ev else None)


# ---------------------------------------------------------------- «напомни»
def test_remind_evening_is_19(monkeypatch):
    from core.services import calendar
    _offline(monkeypatch)
    r = _handle("напомни вечером про стирку", "rem-eve")
    assert "add_event" in r.actions, (r.actions, r.text)
    ev = calendar.find_event("стирку")
    assert ev is not None and ev.start.hour == 19, (ev.start if ev else None)


def test_remind_bare_asks_when(monkeypatch):
    _offline(monkeypatch)
    r = _handle("напомни", "rem-bare")
    assert "clarify" in r.actions, (r.actions, r.text)
    assert "когда" in r.text.lower(), r.text


def test_remind_no_time_asks_when(monkeypatch):
    _offline(monkeypatch)
    r = _handle("напомни маме позвонить", "rem-notime")
    assert "clarify" in r.actions, (r.actions, r.text)
    assert "когда" in r.text.lower(), r.text


def test_remind_with_time_writes(monkeypatch):
    from core.services import calendar
    _offline(monkeypatch)
    r = _handle("напомни завтра в 10 позвонить маме", "rem-full")
    assert "add_event" in r.actions, (r.actions, r.text)
    ev = calendar.find_event("позвонить маме")
    assert ev is not None and ev.start.hour == 10, (ev.start if ev else None)


# ---------------------------------------------------------------- заметки
@pytest.mark.parametrize("phrase", [
    "мысль: идея для ролика про монтаж",
    "запиши: купить молоко",
    "идея для ролика",
])
def test_note_writes(monkeypatch, phrase):
    _offline(monkeypatch)
    r = _handle(phrase, f"note-{hash(phrase) % 9999}")
    assert "add_note" in r.actions, (phrase, r.actions, r.text)


# ---------------------------------------------------------------- «что сегодня/на неделе»
def test_briefing_today(monkeypatch):
    _offline(monkeypatch)
    r = _handle("что сегодня", "rep-today")
    assert "briefing" in r.actions, (r.actions, r.text)


def test_agenda_tomorrow(monkeypatch):
    _offline(monkeypatch)
    r = _handle("что завтра", "rep-tom")
    assert "agenda" in r.actions, (r.actions, r.text)


def test_list_week(monkeypatch):
    _offline(monkeypatch)
    r = _handle("что на неделе", "rep-week")
    assert "list_events" in r.actions, (r.actions, r.text)


def test_list_tasks(monkeypatch):
    _offline(monkeypatch)
    r = _handle("мои задачи", "rep-tasks")
    assert "list_tasks" in r.actions, (r.actions, r.text)


# ---------------------------------------------------------------- «сколько денег»
def test_money_total(monkeypatch):
    _offline(monkeypatch)
    r = _handle("сколько денег", "mon-total")
    assert "finance_summary" in r.actions, (r.actions, r.text)


def test_money_balance(monkeypatch):
    _offline(monkeypatch)
    r = _handle("баланс", "mon-bal")
    assert "finance_summary" in r.actions, (r.actions, r.text)


def test_money_spent_category(monkeypatch):
    _offline(monkeypatch)
    r = _handle("сколько потратил на еду за неделю", "mon-spent")
    assert "query_spent" in r.actions, (r.actions, r.text)


def test_money_earned(monkeypatch):
    _offline(monkeypatch)
    r = _handle("сколько я заработал в этом месяце", "mon-earn")
    assert "query_income" in r.actions, (r.actions, r.text)


# ---------------------------------------------------------------- голосовые расшифровки текстом
def test_voice_expense(monkeypatch):
    _offline(monkeypatch)
    r = _handle("Марвин, запиши трату 700 такси.", "vox-exp")
    assert "add_expense" in r.actions, (r.actions, r.text)


def test_voice_remind(monkeypatch):
    _offline(monkeypatch)
    r = _handle("Марвин, напомни завтра в 10 позвонить маме.", "vox-rem")
    assert "add_event" in r.actions, (r.actions, r.text)


def test_voice_task(monkeypatch):
    _offline(monkeypatch)
    r = _handle("Марвин, задача купить молоко.", "vox-task")
    assert "add_task" in r.actions, (r.actions, r.text)


def test_voice_event(monkeypatch):
    _offline(monkeypatch)
    r = _handle("Марвин, встреча завтра в 10 с Димой.", "vox-ev")
    assert "add_event" in r.actions, (r.actions, r.text)


# ---------------------------------------------------------------- spec: ночь / календарь-или-задача / аванс / отмена
@pytest.mark.parametrize("phrase", ["в 3", "в 4"])
def test_night_hour_bare_asks(monkeypatch, phrase):
    """Ночь 0–5 без маркера → уточнение, записи нет."""
    from core.services import calendar, tasks
    _offline(monkeypatch)
    r = _handle(phrase, f"night-{phrase[-1]}")
    assert "clarify" in r.actions, (phrase, r.actions, r.text)
    assert "?" in r.text, r.text
    assert calendar.list_events(limit=50) == []
    assert tasks.list_tasks() == []


def test_night_with_context_is_pm(monkeypatch):
    """Контекст есть («позвонить в 3», «встреча в 3») → PM без вопросов."""
    from core.services import tasks
    _offline(monkeypatch)
    r = _handle("позвонить в 3", "night-ctx")
    assert "add_task" in r.actions, (r.actions, r.text)
    ts = tasks.list_tasks()
    assert len(ts) == 1 and ts[0].due.hour == 15, [(t.title, t.due) for t in ts]


def test_unclear_datetime_asks_calendar_or_task(monkeypatch):
    """Непонятное дата/время → «календарь или задача?», записи нет."""
    from core.services import calendar, tasks
    _offline(monkeypatch)
    r = _handle("в пятницу молоко", "amb-dt")
    assert "clarify" in r.actions, (r.actions, r.text)
    low = r.text.lower()
    assert "календарь" in low and "задача" in low, r.text
    assert calendar.list_events(limit=50) == []
    assert tasks.list_tasks() == []


def test_advance_asks_order_or_income(monkeypatch):
    _offline(monkeypatch)
    r = _handle("пришёл аванс 10к за ролик", "adv")
    assert "clarify" in r.actions, (r.actions, r.text)
    low = r.text.lower()
    assert "заказ" in low and "доход" in low, r.text
    _no_money_written()


def test_transfer_answer_after_clarify_writes(monkeypatch):
    """Ответ «долг» после вопроса про «перевёл Ване» → запись долга, не трата."""
    _offline(monkeypatch)
    ch = "tr-ans"
    r1 = _handle("перевёл Ване 2000", ch)
    assert "clarify" in r1.actions, (r1.actions, r1.text)
    r2 = _handle("долг", ch)
    assert "add_debt" in r2.actions, (r2.actions, r2.text)
    with db.session() as s:
        ds = s.exec(db.select(db.Debt)).all()
        assert len(ds) == 1 and ds[0].remaining == 2000
        assert s.exec(db.select(db.Transaction)).all() == []


def test_undo_asks_what(monkeypatch):
    """«отмени» после траты → уточнение ЧТО (с названием + да/нет), не молчаливый откат."""
    _offline(monkeypatch)
    ch = "undo-seq"
    r1 = _handle("потратил 700 такси", ch)
    assert "add_expense" in r1.actions, (r1.actions, r1.text)
    r = _handle("отмени", ch)
    assert "clarify" in r.actions, (r.actions, r.text)
    assert "undo" not in r.actions, (r.actions, r.text)
    low = r.text.lower()
    assert "700" in low or "такси" in low or "трат" in low, r.text
    assert "да" in low and "нет" in low, r.text
    with db.session() as s:
        assert len(s.exec(db.select(db.Transaction)).all()) == 1
    r2 = _handle("да", ch)
    assert "undo" in r2.actions, (r2.actions, r2.text)
    with db.session() as s:
        assert s.exec(db.select(db.Transaction)).all() == []
