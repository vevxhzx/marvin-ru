# -*- coding: utf-8 -*-
"""Аудит напоминаний/переводов по скринам хозяина (окт-2026).

Корни, а не симптомы:
1. «в 16-10» парсилось как 16:00, а «-10» утекало в заголовок (dates понимал только :/.).
2. Ответ «календарь» на уточнение писал заголовок как есть — «Поставь напоминание что…».
3. Snooze задачи («Вечером») сбрасывал remind_stage → дубль-напоминание через 5 минут;
   snooze события перевооружал advance-напоминание → ранний повторный пинг.
4. «пополни с кубышки» (повелительное, без суммы) не знал ни один шаблон → галлюцинация модели.
5. Подтверждение «Напомню заранее» не говорило когда; прошлое («вчера в 10») писалось молча.
"""
import asyncio
import os
from datetime import datetime, timedelta

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402

from tests.test_core import fresh_db  # noqa: F401,F403  (временная БД на весь файл)

from core import db  # noqa: E402
from core.brain.dates import parse_datetime  # noqa: E402

NOW = datetime(2026, 10, 13, 11, 57)  # вторник, как на скрине


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


def _handle(text, ch="audit"):
    from core.brain.agent import handle
    return asyncio.run(handle(text, ch))


# ---------------------------------------------------------------- 1. тире-время
def test_dash_time_with_preposition():
    dt, rest = parse_datetime("напомни в 16-10 позвонить", NOW)
    assert dt == datetime(2026, 10, 13, 16, 10), (dt, rest)
    assert "-10" not in rest and "16-10" not in rest, rest


def test_dash_time_morning_rolls_to_tomorrow():
    # 11:57, «к 9-30» — время прошло → завтра, но минуты целы и в заголовке чисто
    dt, rest = parse_datetime("к 9-30 встреча", NOW)
    assert dt == datetime(2026, 10, 14, 9, 30), (dt, rest)
    assert "-30" not in rest, rest


def test_bare_dash_is_not_time():
    # без предлога «16-10» не время (может быть датой/артикулом) — не гадаем
    dt, rest = parse_datetime("встреча 16-10", NOW)
    assert dt is None, (dt, rest)


def test_relative_keeps_no_daypart_in_title():
    # «через полчаса после обеда» — полчаса от now, «после обеда» съедено как контекст
    dt, rest = parse_datetime("напомни через полчаса после обеда позвонить", NOW)
    assert dt == NOW.replace(second=0, microsecond=0) + timedelta(minutes=30), (dt, rest)
    assert "обед" not in rest, rest


# ------------------------------------------------- 2. чистый заголовок + точное время
def test_clarify_answer_has_clean_title_and_dash_time(monkeypatch):
    """Скрин 1: «поставь напоминание что в 16-10 …» → вопрос → «календарь» →
    событие в 16:10 с заголовком без командных слов."""
    from core.services import calendar
    _offline(monkeypatch)
    ch = "shot1"
    r1 = _handle("поставь напоминание что в 16-10 ресаются лимиты в клод для написания курса", ch)
    assert "clarify" in r1.actions, (r1.actions, r1.text)
    r2 = _handle("календарь", ch)
    assert "add_event" in r2.actions, (r2.actions, r2.text)
    evs = calendar.list_events(limit=50)
    assert len(evs) == 1, [(e.title, e.start) for e in evs]
    ev = evs[0]
    assert (ev.start.hour, ev.start.minute) == (16, 10), (ev.title, ev.start)
    low = ev.title.lower()
    for junk in ("поставь", "напоминание", "-10", "16-10"):
        assert junk not in low, ev.title
    assert "лимиты" in low, ev.title


def test_short_dash_goes_direct_with_clean_title(monkeypatch):
    """Та же фраза покороче — прямой путь (без вопроса), но заголовок и время те же."""
    from core.services import calendar
    _offline(monkeypatch)
    r = _handle("поставь напоминание что в 16-10 ресаются лимиты", "shot1b")
    assert "add_event" in r.actions, (r.actions, r.text)
    ev = calendar.list_events(limit=50)[0]
    assert (ev.start.hour, ev.start.minute) == (16, 10), (ev.title, ev.start)
    low = ev.title.lower()
    for junk in ("поставь", "напоминание", "-10", "16-10"):
        assert junk not in low, ev.title


def test_event_ack_states_exact_remind_time(monkeypatch):
    """«Напомню заранее» → «Напомню в 16:00» (событие 16:10, advance 10 мин)."""
    from core.services import calendar
    _offline(monkeypatch)
    r = _handle("напомни в 16:10 позвонить маме", "ack-time")
    assert "add_event" in r.actions, (r.actions, r.text)
    assert "заранее" not in r.text.lower(), r.text
    ev = calendar.list_events(limit=50)[0]
    expect = (ev.start - timedelta(minutes=10)).strftime("%H:%M")
    assert f"Напомню в {expect}" in r.text, r.text


# ------------------------------------------------- 3. snooze без дублей
def _noon(monkeypatch, module):
    """Заморозить время модуля на сегодня 12:00 (утренний пинг уже положен)."""
    fixed = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(module, "now", lambda: fixed)
    return fixed


def test_task_snooze_does_not_refire(monkeypatch):
    """Скрин 3: утренний пинг по задаче → snooze «вечером» → тишина до hour-before."""
    from core.services import tasks
    noon = _noon(monkeypatch, tasks)
    t = tasks.add_task("Решить вопрос (snooze-тест)", noon.replace(hour=19, minute=0))
    fired = [tk for tk, _ in tasks.due_task_reminders() if tk.id == t.id]
    assert len(fired) == 1, "утренний stage1 обязан сработать"
    # то, что делает кнопка «Вечером» после фикса: новый срок + утренний stage помечен
    tasks.update_task(t.id, due=noon.replace(hour=19, minute=0), remind_stage=1)
    again = [tk for tk, _ in tasks.due_task_reminders() if tk.id == t.id]
    assert again == [], "дубль через 5 минут (как на скрине в 9:20)"
    tasks.delete_task(t.id)


def test_task_manual_reschedule_still_rearms(monkeypatch):
    """Ручной перенос («перенеси на …») — НЕ snooze: напоминания заводятся заново."""
    from core.services import tasks
    noon = _noon(monkeypatch, tasks)
    t = tasks.add_task("Перенос (rearm-тест)", noon.replace(hour=19, minute=0))
    assert [tk for tk, _ in tasks.due_task_reminders() if tk.id == t.id]
    tasks.update_task(t.id, due=noon.replace(hour=20, minute=0))
    assert [tk for tk, _ in tasks.due_task_reminders() if tk.id == t.id], \
        "ручной перенос обязан перевзвести утренний пинг"
    tasks.delete_task(t.id)


def test_task_snooze_button_end_to_end(monkeypatch):
    """Та же история скрина 3, но через настоящий cb_reminder (кнопка task:{id}:evening)."""
    from core.services import tasks
    from core.telegram import bot as tb

    t = tasks.add_task("Решить вопрос (кнопка)", datetime.now() + timedelta(hours=3))

    class _Chat:
        id = 1

    class _Msg:
        chat = _Chat()
        message_id = 1
        html_text = "напоминание"
        text = "напоминание"

        async def edit_text(self, *a, **k):
            return None

    class _CQ:
        data = f"task:{t.id}:evening"
        message = _Msg()

        async def answer(self, *a, **k):
            return None

    asyncio.run(tb.cb_reminder(_CQ()))
    with db.session() as s:
        cur = s.get(db.Task, t.id)
        assert cur.remind_stage == 1, "snooze обязан пометить утренний stage, а не сбрасывать в 0"
        due = cur.due
    # сразу после snooze поллинг молчит…
    assert [tk for tk, _ in tasks.due_task_reminders() if tk.id == t.id] == []
    # …а за час до нового срока — один пинг «ОСТАЛОСЬ»
    real_now = datetime.now()
    if due - real_now > timedelta(hours=1, minutes=5):
        monkeypatch.setattr(tasks, "now", lambda: (due - timedelta(minutes=30)).replace(second=0, microsecond=0))
        late = [txt for tk, txt in tasks.due_task_reminders() if tk.id == t.id]
        assert len(late) == 1 and "ОСТАЛОСЬ" in late[0], late
        assert [tk for tk, _ in tasks.due_task_reminders() if tk.id == t.id] == []
    tasks.delete_task(t.id)


def test_event_snooze_fires_once_at_new_time(monkeypatch):
    """Snooze события: один пинг ровно в новое время, без раннего повтора."""
    from core.services import calendar

    holder = {}

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return holder["now"]

    holder["now"] = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(calendar, "datetime", _DT)
    ev = calendar.add_event("Созвон (snooze-тест)", holder["now"] + timedelta(minutes=10),
                            remind_minutes=30, source="test")
    assert [e.id for e in calendar.due_reminders()] == [ev.id]
    # то, что делает кнопка snooze после фикса: новый старт + разовый пинг ровно тогда
    calendar.update_event(ev.id, start=holder["now"] + timedelta(minutes=25), remind_minutes=0)
    assert calendar.due_reminders() == [], "ранний повтор (advance от нового старта)"
    holder["now"] = holder["now"] + timedelta(minutes=26)
    fired = calendar.due_reminders()
    assert [e.id for e in fired] == [ev.id], "ровно один пинг в новое время"
    assert calendar.due_reminders() == []


# ------------------------------------------------- 4. пополнение без суммы
def _money_fixture():
    from core.services import finance
    for name, bal in (("Кубышка", 10000), ("Т-Банк", -740)):
        a = finance.find_account(name)
        if a is None:
            finance.add_account(name, "bank", bal)
        else:
            finance.set_balance(a.name, bal)


def _tx_count():
    with db.session() as s:
        return len(s.exec(db.select(db.Transaction)).all())


def _balance(name):
    from core.services import finance
    return finance.find_account(name).balance

def test_topup_without_amount_asks(monkeypatch):
    """Скрин 2: «пополни с кубышки» → вопрос про сумму/цель, записей нет (не галлюцинация)."""
    _offline(monkeypatch)
    _money_fixture()
    r = _handle("пополни с кубышки", "kub")
    assert "clarify" in r.actions, (r.actions, r.text)
    assert "?" in r.text, r.text
    assert _tx_count() == 0


def test_topup_answer_completes_transfer(monkeypatch):
    _offline(monkeypatch)
    _money_fixture()
    ch = "kub2"
    r1 = _handle("пополни с кубышки", ch)
    assert "clarify" in r1.actions, (r1.actions, r1.text)
    r2 = _handle("1039 на т-банк", ch)
    assert "add_transfer" in r2.actions, (r2.actions, r2.text)
    assert _balance("Кубышка") == pytest.approx(10000 - 1039)
    assert _balance("Т-Банк") == pytest.approx(-740 + 1039)


def test_topup_card_alias_means_main_account(monkeypatch):
    """«на карту» — алиас основного счёта (find_account): с Кубышки (main) на карту
    без уточнения — честный отказ, а не перевод в никуда."""
    _offline(monkeypatch)
    _money_fixture()
    ch = "kub4"
    assert "clarify" in _handle("пополни с кубышки", ch).actions
    r = _handle("1039 на карту", ch)
    assert _tx_count() == 0, (r.actions, r.text)
    assert "тот же счёт" in r.text, r.text


def test_topup_amount_only_asks_target_no_guessing(monkeypatch):
    """Сумма без цели — переспрашиваем цель, не выдумываем (цель из контекста не угадываем)."""
    _offline(monkeypatch)
    _money_fixture()
    ch = "kub3"
    assert "clarify" in _handle("пополни с кубышки", ch).actions
    r = _handle("1039", ch)
    assert "clarify" in r.actions, (r.actions, r.text)
    assert _tx_count() == 0


# ------------------------------------------------- 5. прошлое не пишем молча
def test_past_datetime_is_not_written_silently(monkeypatch):
    """Явно прошедшее время без слов прошлого («напомни 01.01 в 10:00…») —
    не мёртвое событие без огня, а честный ответ «уже прошло» + записей нет."""
    from core.services import calendar, tasks
    _offline(monkeypatch)
    r = _handle("напомни 01.01 в 10:00 позвонить маме", "past")
    assert "add_event" not in r.actions and "add_task" not in r.actions, (r.actions, r.text)
    assert calendar.list_events(limit=50) == []
    assert tasks.list_tasks() == []
    assert "прошло" in r.text.lower(), r.text
    r2 = _handle("задача 01.01 в 10:00 годовой отчёт", "past2")
    assert "add_task" not in r2.actions, (r2.actions, r2.text)
    assert tasks.list_tasks() == []
    assert "прошло" in r2.text.lower(), r2.text
