# -*- coding: utf-8 -*-
"""Умные кнопки под уточнениями: нажал = как будто написал. TDD: сначала красные."""
import asyncio
import os
from datetime import datetime, timedelta

os.environ.setdefault("ASSISTANT_TEST", "1")



def _offline(monkeypatch):
    from core.brain import llm

    async def _no_false(*a, **k):
        return False

    async def _no_none(*a, **k):
        return None

    async def _no_empty(*a, **k):
        return ""

    monkeypatch.setattr(llm, "ollama_available", _no_false)
    monkeypatch.setattr(llm, "embed_available", _no_false)
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(llm, "ollama_chat", _no_none)
    monkeypatch.setattr(llm, "cloud_chat", _no_none)
    monkeypatch.setattr(llm, "small_chat", _no_empty)


def _h(text, ch="tg"):
    from core.brain import agent
    return asyncio.run(agent.handle(text, ch))


def _fit(buttons):
    for _label, payload in buttons or []:
        assert len(("ans:" + payload).encode("utf-8")) <= 64, payload


def test_reply_buttons_default_none():
    from core.brain.agent import Reply
    assert Reply("x").buttons is None


def test_judge_buttons_match_options(fresh_db):
    from core.brain.agent import _judge_question
    r = _judge_question("сайт 15000", "tg", ("expense", "income", "order"))
    assert [p for _l, p in r.buttons] == ["трата", "доход", "заказ"]
    _fit(r.buttons)
    # каждый payload проходит как ответ судье
    import re
    rx = re.compile(r"^\s*(?:это\s+)?(трата|расход|доход|долг|заказ|проект|задача|дело|событие|встреча|календарь|заметка|мысль|мозг)\s*[.!]*\s*$", re.I)
    for _l, p in r.buttons:
        assert rx.match(p), p


def test_pay_ask_buttons_no_order(fresh_db, monkeypatch):
    _offline(monkeypatch)
    # имя есть, но заказа нет — только доход/нет
    r = _h("пришёл аванс 10000 за ролик", "tg")
    assert "clarify" in r.actions
    assert [p for _l, p in r.buttons] == ["доход", "нет"]
    _fit(r.buttons)
    # имени нет вообще — полный набор
    r = _h("пришёл аванс 10000", "tg")
    assert "clarify" in r.actions
    assert [p for _l, p in r.buttons] == ["заказ", "доход", "нет"]
    _fit(r.buttons)


def test_pay_ask_buttons_with_candidate(fresh_db, monkeypatch):
    from core.services import orders
    _offline(monkeypatch)
    orders.add_order("Ролик", price=25_000)
    r = _h("пришёл аванс 10000 за ролик", "tg")
    assert "clarify" in r.actions
    labels = [label for label, _p in r.buttons]
    assert any("Ролик" in label for label in labels)
    assert [p for _l, p in r.buttons] == ["заказ", "доход", "нет"]
    _fit(r.buttons)
    # нажатие «заказ» при кандидате пишет оплату
    r2 = _h("заказ", "tg")
    assert "order_payment" in r2.actions


def test_undo_buttons(fresh_db, monkeypatch):
    _offline(monkeypatch)
    _h("потратил 700 на такси", "tg")
    r = _h("отмени", "tg")
    assert "clarify" in r.actions
    assert [p for _l, p in r.buttons] == ["да", "нет"]
    _fit(r.buttons)


def test_night_buttons(fresh_db, monkeypatch):
    _offline(monkeypatch)
    r = _h("в 3", "tg")
    assert "clarify" in r.actions
    assert [p for _l, p in r.buttons] == ["ночью", "днём"]
    _fit(r.buttons)


def test_cal_task_buttons(fresh_db, monkeypatch):
    _offline(monkeypatch)
    r = _h("отчёт 25 сентября", "tg")
    assert "clarify" in r.actions
    assert [p for _l, p in r.buttons] == ["календарь", "задача"]
    _fit(r.buttons)


def test_done_future_buttons(fresh_db, monkeypatch):
    from core.services import calendar
    _offline(monkeypatch)
    tmr = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    calendar.add_event("Проба", tmr.replace(hour=12), source="tg")
    r = _h("сделал проба", "tg")
    assert "clarify" in r.actions
    assert [p for _l, p in r.buttons] == ["да", "нет"]
    _fit(r.buttons)


def test_pc_power_buttons(fresh_db, monkeypatch):
    _offline(monkeypatch)
    r = _h("выключи компьютер", "tg")
    assert "clarify" in r.actions
    assert [p for _l, p in r.buttons] == ["да", "нет"]
    _fit(r.buttons)


def test_sorter_preview_buttons(fresh_db, monkeypatch):
    from core.brain import sorter
    monkeypatch.setattr(sorter, "confirm_enabled", lambda: True)

    async def _items(text):
        return [{"kind": "task", "title": "Купить хлеб"}], "rules"
    monkeypatch.setattr(sorter, "_ask_llm", _items)
    r = asyncio.run(sorter.sort("купить хлеб", "tg"))
    assert [p for _l, p in r.buttons] == ["да", "нет"]
    _fit(r.buttons)


def test_kb_builder():
    from core.brain.agent import Reply
    from core.telegram.bot import _answer_kb
    assert _answer_kb(Reply("x")) is None
    assert _answer_kb(Reply("x", buttons=[])) is None
    kb = _answer_kb(Reply("x?", ["clarify"], buttons=[("Трата", "трата"), ("Доход", "доход")]))
    btns = [b for row in kb.inline_keyboard for b in row]
    assert [(b.text, b.callback_data) for b in btns] == [("Трата", "ans:трата"), ("Доход", "ans:доход")]
    # красиво: два вопроса рядом, а не столбиком
    assert len(kb.inline_keyboard) == 1 and len(kb.inline_keyboard[0]) == 2


def test_kb_three_buttons_two_rows():
    from core.telegram.bot import _answer_kb
    kb = _answer_kb([("А", "а"), ("Б", "б"), ("В", "в")])
    assert [len(row) for row in kb.inline_keyboard] == [2, 1]


def test_remind_buttons(fresh_db, monkeypatch):
    _offline(monkeypatch)
    r = _h("напомни позвонить маме", "tg")
    assert "clarify" in r.actions
    assert [p for _l, p in r.buttons] == ["через час", "завтра в 10", "вечером", "нет"]
    _fit(r.buttons)
    # нажатие «через час» реально ставит напоминание
    r2 = _h("через час", "tg")
    assert "add_event" in r2.actions


def test_people_duplicates_buttons(fresh_db, monkeypatch):
    from core.services import people
    _offline(monkeypatch)
    people.add_person("Ваня Иванов", "friend", notes="первый")
    people.add_person("Ваня Петров", "client", notes="второй")
    r = _h("что по Ване", "tg")
    assert "clarify" in r.actions
    assert r.buttons and len(r.buttons) >= 2
    _fit(r.buttons)


def test_bulk_buttons(fresh_db, monkeypatch):
    _offline(monkeypatch)
    from core.services import tasks
    tasks.add_task("Мусор", None, source="tg")
    r = _h("удали все задачи", "tg")
    if "clarify" in r.actions:
        assert [p for _l, p in r.buttons] == ["да", "нет"]
        _fit(r.buttons)
