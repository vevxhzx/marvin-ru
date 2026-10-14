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
    assert f"напомню в {expect}" in r.text.lower(), r.text


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
    # сразу после snooze — максимум один hour-before пинг (если срок в пределах часа),
    # дальше тишина: никакого дубля утреннего stage
    first = [tk for tk, _ in tasks.due_task_reminders() if tk.id == t.id]
    assert len(first) <= 1, [ (tk.due, tk.remind_stage) for tk, _ in tasks.due_task_reminders() ]
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
    from core.services import finance
    kub = finance.find_account("Кубышка")
    finance.update_account(kub.id, is_main=True)   # детерминировано: сид на CI зовёт мейн иначе
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


# ------------------------------------------------- 7. пять решений + тихая болтовня
def test_overwritten_question_is_announced(monkeypatch):
    """Q1 «календарь?» затирается Q2 «когда?» — в Q2 одна строка, что прошлый снят."""
    _offline(monkeypatch)
    ch = "slot-disp"
    assert "clarify" in _handle("в пятницу молоко", ch).actions
    r = _handle("напомни маме позвонить", ch)
    assert "clarify" in r.actions, (r.actions, r.text)
    low = r.text.lower()
    assert "прошлый вопрос" in low and "пятницу" in low, r.text


def test_pay_ask_survives_unrelated_chatter(monkeypatch, fresh_db):
    """pay_ask: чужое сообщение слот не снимает (peek), ответ — работает как раньше."""
    import json
    from core.brain import agent as _agent
    from core.brain.rules.orders import pay_ask_rule
    ch = "pay-peek"
    _agent._pending_set(ch, "pay_ask|" + json.dumps(
        {"amount": 10000, "q": "ролик", "oid": None, "date": None}, ensure_ascii=False))
    assert pay_ask_rule("пополни с кубышки", "пополни с кубышки", ch) is None
    assert _agent._pending_get(ch) is not None, "чужое сообщение сняло pay_ask"
    r = pay_ask_rule("доход", "доход", ch)
    assert r is not None and "add_income" in r.actions, (r.text if r else None)


def test_pay_ask_answer_flow_still_writes(monkeypatch, fresh_db):
    """«пришёл аванс 10к за ролик» → «доход» → запись дохода (consume при ответе)."""
    _offline(monkeypatch)
    ch = "pay-flow"
    assert "clarify" in _handle("пришёл аванс 10к за ролик", ch).actions
    r = _handle("доход", ch)
    assert "add_income" in r.actions, (r.actions, r.text)


def test_no_cancels_newest_transfer_question(monkeypatch):
    """«нет» при двух вопросах гасит свежий (перевод), календарный живёт дальше."""
    _offline(monkeypatch)
    _money_fixture()
    ch = "no-newest"
    assert "clarify" in _handle("в пятницу молоко", ch).actions
    assert "clarify" in _handle("пополни с кубышки", ch).actions
    r = _handle("нет", ch)
    assert "не записываю" in r.text.lower(), (r.actions, r.text)
    assert _tx_count() == 0
    r2 = _handle("календарь", ch)
    assert "add_event" in r2.actions, (r2.actions, r2.text)


def test_correction_takes_last_date():
    """«в пятницу, нет, в субботу» → суббота, заголовок чистый."""
    wed = datetime(2026, 10, 14, 12, 0)
    dt, rest = parse_datetime("встреча в пятницу, нет, в субботу", wed)
    assert dt == datetime(2026, 10, 17, 10, 0), (dt, rest)
    assert rest == "встреча", rest


def test_correction_keeps_first_time():
    """«в пятницу в 15, нет, в субботу» → суббота в 15:00."""
    wed = datetime(2026, 10, 14, 12, 0)
    dt, rest = parse_datetime("в пятницу в 15, нет, в субботу", wed)
    assert dt == datetime(2026, 10, 17, 15, 0), (dt, rest)


def test_no_marker_first_date_wins():
    """Без маркера исправления — как раньше: первая дата, без сюрпризов."""
    wed = datetime(2026, 10, 14, 12, 0)
    dt, _ = parse_datetime("напомни в пятницу про субботу", wed)
    assert dt == datetime(2026, 10, 16, 10, 0), dt
    assert parse_datetime("позвони маме, нет, напиши маме", wed)[0] is None


def test_same_day_past_writes_with_honest_tail(monkeypatch):
    """Внутридневное прошлое пишется (голден), но в ответе честно: огонь не сработает."""
    import core.brain.agent as _agent
    import core.brain.dates as _dates
    from core.services import calendar
    _offline(monkeypatch)
    holder = {"now": datetime(2026, 10, 13, 14, 0)}

    class _DT(datetime):
        @classmethod
        def now(cls, tz=None):
            return holder["now"]

    monkeypatch.setattr(_agent, "datetime", _DT)
    monkeypatch.setattr(_dates, "datetime", _DT)
    r = _handle("напомни сегодня в 13:00 позвонить", "past-day")
    assert "add_event" in r.actions, (r.actions, r.text)
    assert "уже прошло" in r.text.lower(), r.text
    # Окно задаём явно: list_events() по умолчанию начинает с РЕАЛЬНОГО сегодняшнего дня,
    # а событие легло на 12-е (вчерашнее относительно закреплённых 13.10 14:00). Тест с
    # умолчанием ждал ровно до полуночи 13→14 октября, после чего отваливался сам по себе.
    _from = datetime(2026, 10, 1)
    assert len(calendar.list_events(_from, _from + timedelta(days=60), limit=50)) == 1


VENT = ("всё пойдет, чет пустовато себя ощущаю\n"
        "чуть тревожно от скорых изменений всяких\n"
        "чувствую что стал худшей версией себя если так выразится\n"
        "чет потолстел пузо отрастил, сижу дома постоянно\n"
        "забыл как общаться нахер, еле разговариваю\n"
        "слова глотаю чисто сыч домашний\n"
        "хз брат как дела, потихоньку")


def test_venting_monologue_is_not_a_batch():
    """Личный рассказ с переносами строк — не список: сортировщик не разбирает."""
    from core.brain import sorter
    assert sorter.looks_like_batch(VENT) is False
    assert sorter.looks_like_batch("хлеб 120, молоко 90, яйца 150") is True
    assert sorter.looks_like_batch("купить молоко\nпозвонить маме\nоплатить аренду") is True


def test_vent_end_to_end_no_memory_dump(monkeypatch):
    """Вент в чате: без «Разобрал, получилось N» и без пачки записей."""
    from core.services import calendar, tasks
    _offline(monkeypatch)
    r = _handle(VENT, "vent")
    assert "разобрал" not in r.text.lower(), r.text
    assert "add_event" not in r.actions and "add_task" not in r.actions, (r.actions, r.text)
    assert calendar.list_events(limit=50) == [] and tasks.list_tasks() == []


# ------------------------------------------------- 6. остаток матрицы сценариев
def test_garbage_input_never_crashes_nor_writes(monkeypatch):
    """Пустой/мусорный ввод: без исключений и без записей (ответить может как угодно)."""
    from core.services import calendar, tasks
    _offline(monkeypatch)
    for i, g in enumerate(("", "   ", "ываываыва", "!" * 250)):
        r = _handle(g, f"garbage-{i}")
        assert isinstance(r.text, str) and r.text, (g, r)
    assert calendar.list_events(limit=50) == []
    assert tasks.list_tasks() == []
    with db.session() as s:
        assert s.exec(db.select(db.Transaction)).all() == []


def test_bare_remind_asks_not_writes(monkeypatch):
    _offline(monkeypatch)
    from core.services import calendar
    r = _handle("напомни", "bare")
    assert "clarify" in r.actions, (r.actions, r.text)
    assert calendar.list_events(limit=50) == []


def test_two_different_events_same_time_both_fire():
    """Два разных события на одно время — оба напоминают (дедуп только по тому же названию)."""
    from core.services import calendar
    now = datetime.now().replace(second=0, microsecond=0)
    calendar.add_event("Созвон А", now + timedelta(minutes=10), remind_minutes=30, source="test")
    calendar.add_event("Созвон Б", now + timedelta(minutes=10), remind_minutes=30, source="test")
    assert sorted(e.title for e in calendar.due_reminders()) == ["Созвон А", "Созвон Б"]


def test_weekly_repeat_creates_one_rule(monkeypatch):
    """«каждый пн ср пт в 19» — одно правило weekly, первое вхождение — пн/ср/пт 19:00."""
    _offline(monkeypatch)
    r = _handle("тренировка каждый пн ср пт в 19", "rep")
    assert "add_event" in r.actions, (r.actions, r.text)
    with db.session() as s:
        rows = s.exec(db.select(db.Event)).all()
    assert len(rows) == 1, [(e.title, e.start) for e in rows]
    ev = rows[0]
    assert ev.repeat == "weekly" and ev.repeat_days == "0,2,4", (ev.repeat, ev.repeat_days)
    assert ev.start.weekday() in (0, 2, 4) and (ev.start.hour, ev.start.minute) == (19, 0)


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


# ------------------------------------------------- 9. ответы с довеском (аудит #4) + мелочи (#8)
def _events():
    with db.session() as s:
        return s.exec(db.select(db.Event)).all()


def test_clarify_answer_with_tail_still_matches(monkeypatch):
    """«календарь, и напомни за час» — хвост съеден, событие в календаре (а не утечка дальше)."""
    _offline(monkeypatch)
    ch = "tail1"
    r1 = _handle("поставь напоминание что в 16-10 ресаются лимиты в клод для написания курса", ch)
    assert "clarify" in r1.actions, (r1.actions, r1.text)
    r2 = _handle("календарь, и напомни за час", ch)
    assert "add_event" in r2.actions, (r2.actions, r2.text)
    evs = _events()
    assert len(evs) == 1 and "лимиты" in evs[0].title.lower(), [(e.title, e.start) for e in evs]
    assert "напомни" not in evs[0].title.lower() and "час" not in evs[0].title.lower(), evs[0].title


def test_clarify_prefix_does_not_swallow_real_commands(monkeypatch):
    """Префикс-матч только с явным хвостом-связкой: «задача: купить молоко» не гасит слот и не режется."""
    from core.brain.agent import CLARIFY_RX, _CLARIFY_TAIL_RX
    for s in ("задача: купить молоко", "задача, купить молоко", "напоминание на завтра", "нет, в календарь"):
        assert not CLARIFY_RX.match(s) and not _CLARIFY_TAIL_RX.match(s), s
    assert _CLARIFY_TAIL_RX.match("календарь, и напомни за час")
    assert _CLARIFY_TAIL_RX.match("задача и поставь на пятницу")


def test_remind_answer_with_tail_keeps_clean_title(monkeypatch):
    """«завтра в 10, и это очень важно» как ответ на «когда?» — заголовок без хвоста."""
    _offline(monkeypatch)
    ch = "tail2"
    assert "clarify" in _handle("напомни маме позвонить", ch).actions
    r = _handle("завтра в 10, и это очень важно", ch)
    assert "add_event" in r.actions, (r.actions, r.text)
    evs = _events()
    assert len(evs) == 1 and "важно" not in evs[0].title.lower(), [(e.title, e.start) for e in evs]
    assert "позвонить" in evs[0].title.lower(), evs[0].title


def test_remind_empty_what_time_only_answer_asks_what(monkeypatch):
    """«напомни» → «завтра в 10» (без дела, или только хвост) — не пишем событие с мусорным заголовком."""
    _offline(monkeypatch)
    for i, ans in enumerate(("завтра в 10", "завтра в 10, и это очень важно")):
        ch = f"empty{i}"
        assert "clarify" in _handle("напомни", ch).actions
        r = _handle(ans, ch)
        assert "add_event" not in r.actions and "clarify" in r.actions, (ans, r.actions, r.text)
        assert _events() == [], [(e.title, e.start) for e in _events()]


def test_remind_empty_what_answer_with_task_still_works(monkeypatch):
    _offline(monkeypatch)
    ch = "empty-ok"
    assert "clarify" in _handle("напомни", ch).actions
    r = _handle("завтра в 10 позвонить маме", ch)
    assert "add_event" in r.actions, (r.actions, r.text)
    assert _events()[0].title == "Позвонить маме", _events()[0].title


def test_repeat_title_uses_shared_cleaner(monkeypatch):
    """Повторяющееся: «что надо не забыть» срезается тем же _clean_event_title, что и обычное событие."""
    _offline(monkeypatch)
    r = _handle("напомни что надо не забыть позвонить маме каждый пн в 19", "rep-clean")
    assert "add_event" in r.actions, (r.actions, r.text)
    ev = _events()[0]
    assert ev.repeat == "weekly" and ev.title == "Позвонить маме", (ev.title, ev.repeat)


def test_transfer_answer_with_tail_cuts_account_name(monkeypatch):
    """«1039 на т-банк и побыстрее» / «…на т-банк, пожалуйста» — счёт «т-банк», а не «т-банк и побыстрее»."""
    _offline(monkeypatch)
    for i, ans in enumerate(("1039 на т-банк и побыстрее", "1039 на т-банк, пожалуйста")):
        _money_fixture()
        ch = f"tr-tail{i}"
        assert "clarify" in _handle("пополни с кубышки", ch).actions
        b0 = _balance("Т-Банк")
        r = _handle(ans, ch)
        assert "add_transfer" in r.actions, (ans, r.actions, r.text)
        assert _balance("Т-Банк") == pytest.approx(b0 + 1039)
    from core.services import finance
    names = [a.name.lower() for a in finance.list_accounts()] if hasattr(finance, "list_accounts") else []
    assert not any("побыстрее" in n or "пожалуйста" in n for n in names), names


def test_system_prompt_has_tool_honesty_guard():
    """Аудит #7: промпт запрещает заявлять о записях/отменах, которых не делал (деньги и записи — только инструментами)."""
    from core.brain.persona import system_prompt
    for compact in (False, True):
        p = system_prompt(compact)
        assert "ТОЛЬКО через инструменты" in p, compact
        assert "не заявляй" in p, compact

# ---------------------------------------------------------------- 6. Обещание «напомню» без инструмента
# Прод 14.10: «чуть позже напомни...» → модель ответила «Напомню тебе через час»,
# а в базе ничего не появилось (run: route=ollama, tools='', actions='').
# Обещание должно материализоваться в событие + кнопку отмены, а не висеть текстом.
PROMISE_TEXT = "все кайф спасибо, чуть позже напомни чтобы я данные актуализировал по финансам"
PROMISE_ANSWER = ("**Финансы: время обновить данные**\n\nНапомню тебе через час: открой инструменты "
                  "и актуализируй данные по финансам.\n\nМяу. Через 60 минут — обновляем цифры.")


def _promise_brain(monkeypatch, answer=PROMISE_ANSWER):
    """Модель отвечает обещанием и не зовёт инструменты — как было в проде."""
    _offline(monkeypatch)
    from core.brain import llm

    async def fake_chat(messages, tools=None, **kw):
        return {"content": answer, "tool_calls": []}

    async def _yes_true(*a, **k):
        return True

    # Герметичность: via_ollama gated на local_available() — без этого тест требовал
    # живой LM Studio/Ollama на машине (на CI их нет, и путь уходил в «мозг не запущен»).
    monkeypatch.setattr(llm, "local_available", _yes_true)
    monkeypatch.setattr(llm, "ollama_chat", fake_chat)


def test_saved_rx_catches_remind_promise():
    from core.brain.agent import _claims_saved
    assert _claims_saved("Напомню тебе через час")
    assert _claims_saved("напомнить — сделаю")


def test_remind_offset_minutes():
    from core.brain.agent import _remind_offset_minutes
    assert _remind_offset_minutes("Напомню тебе через час", "") == 60
    assert _remind_offset_minutes("Через 60 минут — обновляем", "") == 60
    assert _remind_offset_minutes("напомню через 15 минут", "") == 15
    assert _remind_offset_minutes("напомню через 2 часа", "") == 120
    assert _remind_offset_minutes("напомню", "напомни завтра") is None


def test_remind_promise_without_tool_creates_event(monkeypatch):
    _promise_brain(monkeypatch)
    from core.services import calendar
    before = datetime.now()
    r = _handle(PROMISE_TEXT, "rem-promise")
    assert "add_event" in r.actions, (r.actions, r.text)
    evs = calendar.list_events(before, before + timedelta(days=2), limit=50)
    assert len(evs) == 1, [e.title for e in evs]
    ev = evs[0]
    assert 50 * 60 <= (ev.start - before).total_seconds() <= 70 * 60, ev.start
    assert ev.remind_minutes == 0, "пинг ровно в срок, а не за 30 минут до"
    assert "через час" in r.text, "теплое обещание модели оставляем, а не затираем"
    assert r.buttons == [("❌ Отменить", "отмени")], r.buttons


def test_remind_cancel_button_undoes_event(monkeypatch):
    _promise_brain(monkeypatch)
    from core.services import calendar
    before = datetime.now()
    r = _handle(PROMISE_TEXT, "rem-cancel")
    assert "add_event" in r.actions
    assert len(calendar.list_events(before, before + timedelta(days=2), limit=50)) == 1
    r2 = _handle("отмени", "rem-cancel")
    if "undo" not in r2.actions:
        r3 = _handle("да", "rem-cancel")
        assert "undo" in r3.actions, (r2.text, r3.text)
    assert calendar.list_events(before, before + timedelta(days=2), limit=50) == []


def test_remind_refusal_is_left_alone(monkeypatch):
    """Модель отказалась («не напомню») — уважаем отказ, ничего не пишем.
    Текст — мимо правил (не начинается с «напомни»): нужен именно путь модели."""
    _promise_brain(monkeypatch, answer="Не напомню завтра, сам следи за временем.")
    from core.services import calendar
    before = datetime.now()
    r = _handle("слушай, чуть позже напомни мне про отчет, а то точно забуду", "rem-refuse")
    assert calendar.list_events(before, before + timedelta(days=2), limit=50) == []
    assert "add_event" not in r.actions
