"""Сортировщик: одно сообщение → задачи, встречи, люди, клиенты, заказы, оплаты, долги, цели, ссылки, «сделал».
Модель подменяется готовым JSON — проверяем раздачу по сервисам, отчёт, откат пачки и режим «показать перед записью»."""
import asyncio
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


def _mock(monkeypatch, items, via="gemini"):
    from core.brain import llm, sorter

    async def fake(_text):
        return items, via

    async def no_ollama(force=False):
        return False
    monkeypatch.setattr(sorter, "_ask_llm", fake)
    monkeypatch.setattr(llm, "ollama_available", no_ollama)
    monkeypatch.setattr(llm, "MODE", "cloud")


def test_looks_like_batch_thresholds():
    from core.brain import sorter
    # 2 пункта с переносом строки и явным типом — уже список
    assert sorter.looks_like_batch("клиент Ромашка\nзаказ логотип для Ромашки 15к до пятницы")
    assert sorter.looks_like_batch("1. купить ванну 2. позвонить маме")
    assert sorter.looks_like_batch("человек Лена — сестра; Ваня должен мне 5000; завтра в 10 зубной")
    # одна команда, вопрос, анализ, одиночная ссылка — нет
    assert not sorter.looks_like_batch("заказ: ролик для Пятёрочки, 25к, до пятницы")
    assert not sorter.looks_like_batch("сколько я потратил на еду, такси и кино?")
    assert not sorter.looks_like_batch("разбери ситуацию: долг 5000, зарплата 40000, аренда 30000")
    assert not sorter.looks_like_batch("https://example.com/article про дизайн, прочитать потом")


def test_mixed_message_lands_everywhere(monkeypatch):
    from core.brain import agent
    from core.services import brain_notes, calendar, finance, goals, orders, people, tasks
    tasks.add_task("Сделать отчёт")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    friday = (datetime.now() + timedelta(days=(4 - datetime.now().weekday()) % 7 or 7)).strftime("%Y-%m-%d")
    past = (datetime.now() - timedelta(days=25)).strftime("%Y-%m-%d")
    _mock(monkeypatch, [
        {"kind": "client", "title": "Ромашка"},
        {"kind": "company", "title": "ООО Вектор", "note": "типография"},
        {"kind": "order", "title": "Логотип", "who": "Ромашка", "amount": "15к", "when": friday, "hours": 8},
        {"kind": "order", "title": "Старый ролик", "who": "Ромашка", "amount": 13500, "status": "paid"},
        {"kind": "order_payment", "title": "Логотип", "amount": 5000, "when": past},
        {"kind": "person", "title": "Лена", "note": "сестра"},
        {"kind": "note", "title": "Ваня должен мне 5000"},
        {"kind": "debt", "title": "Долг Пете", "amount": 3000, "note": "Петя"},
        {"kind": "goal", "title": "Подушка", "amount": 300000},
        {"kind": "task", "title": "Купить ванну"},
        {"kind": "event", "title": "Зубной", "when": f"{tomorrow}T10:00"},
        {"kind": "done", "title": "отчёт"},
        {"kind": "expense", "title": "Хлеб", "amount": 120},
        {"kind": "recurring", "title": "Подписка Яндекс", "amount": 300, "day": 5},
    ])
    text = "клиент Ромашка\nкомпания ООО Вектор — типография\nзаказ логотип для Ромашки 15к до пятницы, 8 часов\nстарый ролик для Ромашки 13500 уже оплачен\nпришло 5000 за логотип\nчеловек Лена — сестра\nВаня должен мне 5000\nдолжен Пете 3000\nцель подушка 300к\nкупить ванну\nзавтра в 10 зубной\nсделал отчёт\nхлеб 120\nподписка Яндекс 300 каждый месяц 5-го"
    r = asyncio.run(agent.handle(text, "t-mix"))
    assert r is not None and "Разобрал" in r.text, r and r.text
    for label in ("Клиенты (1)", "Компании (1)", "Заказы (2)", "Оплаты по заказам (1)", "Люди (1)", "В память (1)", "Долги (1)", "Цели (1)", "Задачи (1)", "В календарь (1)", "Закрыто (1)", "Траты (1)", "Регулярные (1)"):
        assert label in r.text, (label, r.text)
    # люди
    assert people.find_person("Ромашка").kind == "client"
    assert people.find_person("Вектор").kind == "company"
    assert people.find_person("Лена").kind == "family" and "сестра" in (people.find_person("Лена").notes or "")
    # заказы
    allo = {o["title"]: o for o in orders.list_orders(include_closed=True)}
    assert allo["Логотип"]["price"] == 15000 and allo["Логотип"]["estimate_h"] == 8 and allo["Логотип"]["client"] == "Ромашка"
    assert allo["Логотип"]["paid"] == 5000 and allo["Логотип"]["left"] == 10000
    assert allo["Старый ролик"]["status"] == "paid" and allo["Старый ролик"]["left"] == 0
    pays = orders.payments_for(allo["Логотип"]["id"])
    assert pays and pays[0].date.date() == datetime.strptime(past, "%Y-%m-%d").date()   # задним числом
    # деньги
    assert [d.title for d in finance.list_debts()] == ["Долг Пете"]
    assert goals.list_goals()[0]["target"] == 300000
    assert any(r_.title == "Подписка Яндекс" and r_.day == 5 for r_ in finance.list_recurring())
    # задачи, события, заметки
    open_titles = [t.title for t in tasks.list_tasks()]
    assert "Купить ванну" in open_titles and "Сделать отчёт" not in open_titles
    assert brain_notes.list_notes(10)[0].text == "Ваня должен мне 5000"
    day = datetime.now() + timedelta(days=1)
    assert [e.title for e in calendar.list_events(day.replace(hour=0, minute=0), day.replace(hour=23, minute=59))] == ["Зубной"]

    # откат всей пачки
    r = asyncio.run(agent.handle("отмени", "t-mix"))
    assert "всю пачку" in r.text
    assert not orders.list_orders(include_closed=True) and not finance.list_debts() and not goals.list_goals()
    assert "Купить ванну" not in [t.title for t in tasks.list_tasks()]


def test_confirm_mode_shows_draft_then_writes(monkeypatch):
    from core import config
    from core.brain import agent
    from core.services import tasks
    monkeypatch.setattr(config.cfg.brain, "sorter", config._Node({"where": "cloud", "confirm": True}), raising=False)
    _mock(monkeypatch, [{"kind": "task", "title": "Купить ванну"}, {"kind": "task", "title": "Позвонить маме"}])
    r = asyncio.run(agent.handle("1. купить ванну 2. позвонить маме", "t-conf"))
    assert "как я это понял" in r.text and "Записать?" in r.text
    assert not tasks.list_tasks()
    r = asyncio.run(agent.handle("да", "t-conf"))
    assert "Разобрал" in r.text and len(tasks.list_tasks()) == 2


def test_confirm_mode_no_cancels(monkeypatch):
    from core import config
    from core.brain import agent
    from core.services import tasks
    monkeypatch.setattr(config.cfg.brain, "sorter", config._Node({"where": "cloud", "confirm": True}), raising=False)
    _mock(monkeypatch, [{"kind": "task", "title": "Купить ванну"}, {"kind": "task", "title": "Позвонить маме"}])
    asyncio.run(agent.handle("1. купить ванну 2. позвонить маме", "t-no"))
    r = asyncio.run(agent.handle("нет", "t-no"))
    assert "ничего не записал" in r.text and not tasks.list_tasks()


def test_unknown_order_payment_is_reported_not_lost(monkeypatch):
    from core.brain import agent
    _mock(monkeypatch, [{"kind": "task", "title": "Купить ванну"}, {"kind": "order_payment", "title": "Сайт", "amount": 5000}])
    r = asyncio.run(agent.handle("купить ванну; пришло 5000 за сайт", "t-pay"))
    assert "Не записал" in r.text and "не нашёл такой заказ" in r.text and "Задачи (1)" in r.text


def test_amount_parsing():
    from core.brain.sorter import _amount
    assert _amount("15к") == 15000 and _amount("1.5к") == 1500 and _amount("200 тыс") == 200000
    assert _amount(120) == 120 and _amount("0") is None and _amount(None) is None
