"""Быстрые тесты ядра: запускать  python -m pytest tests -q"""
import asyncio
import os
from datetime import datetime, timedelta

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402

from core import db  # noqa: E402
from core.brain.dates import parse_amount, parse_datetime  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlmodel import create_engine
    eng = create_engine(f"sqlite:///{tmp_path/'t.db'}", connect_args={"check_same_thread": False})
    db._pragmas.__wrapped__ if hasattr(db._pragmas, "__wrapped__") else None
    from sqlalchemy import event
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


NOW = datetime(2026, 9, 6, 14, 0)  # воскресенье


@pytest.mark.parametrize("text,expected,rest", [
    ("встреча в среду в 15:00 с Ваней", datetime(2026, 9, 9, 15, 0), "встреча с Ваней"),
    ("завтра в 10 стоматолог", datetime(2026, 9, 7, 10, 0), "стоматолог"),
    ("через 2 часа позвонить маме", datetime(2026, 9, 6, 16, 0), "позвонить маме"),
    ("25 сентября в 19 концерт", datetime(2026, 9, 25, 19, 0), "концерт"),
    ("сегодня вечером тренировка", datetime(2026, 9, 6, 19, 0), "тренировка"),
    ("встреча 12.09 в 11:30", datetime(2026, 9, 12, 11, 30), "встреча"),
    ("купить молоко", None, "купить молоко"),
    ("иду на др 12 числа", datetime(2026, 9, 12, 10, 0), "иду на др"),
    ("оплатить 3 числа", datetime(2026, 10, 3, 10, 0), "оплатить"),
])
def test_dates(text, expected, rest):
    dt, r = parse_datetime(text, NOW)
    assert dt == expected
    assert r == rest


@pytest.mark.parametrize("text,amount", [
    ("потратил 700 на такси", 700), ("1.5к кафе", 1500), ("зп 120 тыс", 120000), ("2 500 руб продукты", 2500),
])
def test_amounts(text, amount):
    assert parse_amount(text)[0] == amount


def run(text):
    from core.brain.agent import handle
    return asyncio.run(handle(text, "test"))


def test_expense_income_balance():
    from core.services import finance
    run("баланс т-банк 10000")
    run("потратил 700 на такси")
    run("зп 5000")
    s = finance.summary(1)
    assert s["total_balance"] == 14300
    assert s["by_category"] == {"Транспорт": 700}
    run("отмени последнюю")
    assert finance.summary(1)["total_balance"] == 9300


def test_event_and_reminder():
    from core.services import calendar
    r = run("встреча в среду в 15:00 с Ваней")
    assert "add_event" in r.actions
    evs = calendar.list_events()
    assert evs[0].title == "Встреча с Ваней" and evs[0].start.hour == 15


def test_event_phrase_cleanup():
    """«Поставь событие что я иду на др 12 числа» → название без служебных слов, дата — 12-е число."""
    from core.services import calendar
    r = run("Поставь событие что я иду на др 12 числа")
    assert "add_event" in r.actions
    ev = [e for e in calendar.list_events(limit=50) if "др" in e.title][0]
    assert ev.title == "Я иду на др" and ev.start.day == 12


def test_task_flow():
    from core.services import tasks
    run("надо купить молоко")
    assert tasks.list_tasks()[0].title == "Купить молоко"
    r = run("сделал молоко")
    assert "complete_task" in r.actions
    assert tasks.list_tasks() == []


def test_debt_forecast():
    from core.services import finance
    run("долг Сберу 120к плачу 8к 25-го")
    d = finance.list_debts()[0]
    f = finance.debt_forecast(d)
    assert d.remaining == 120000 and d.payment == 8000 and f["months"] == 15
    assert any(r.debt_id == d.id for r in finance.list_recurring())


def test_note_and_memory():
    from core.services import brain_notes
    run("мысль: сделать голос как у Пола Беттани")
    assert "Беттани" in brain_notes.list_notes()[0].text
    assert brain_notes.search_memory("беттани")


# ---------------- финансы: правила и целостность ----------------
def test_debt_rules():
    from core.services import finance
    F = finance.FinanceError
    d = finance.add_debt("Сбер", 100000, payment=5000, pay_day=10)
    with pytest.raises(F):                       # платёж больше остатка
        finance.pay_debt(d.id, 200000)
    with pytest.raises(F):                       # ноль/отрицательное
        finance.pay_debt(d.id, 0)
    with pytest.raises(F):                       # остаток больше суммы
        finance.add_debt("X", 1000, remaining=2000)
    with pytest.raises(F):                       # платёж больше долга
        finance.add_debt("Y", 1000, payment=2000)
    with pytest.raises(F):                       # день 0
        finance.add_debt("Z", 1000, pay_day=0)
    bal0 = finance.summary(1)["total_balance"]
    d = finance.pay_debt(d.id, 5000, source="web")
    assert d.remaining == 95000
    assert finance.summary(1)["total_balance"] == bal0 - 5000
    # платёж — одна операция, связанная с долгом; её удаление возвращает остаток и баланс
    tx = finance.debt_payments(d.id)[0]
    assert tx.amount == 5000 and tx.category == "Долги"
    finance.delete_transaction(tx.id)
    assert finance.find_debt(d.id).remaining == 100000
    assert finance.summary(1)["total_balance"] == bal0
    # закрытие: последний платёж ровно на остаток
    finance.update_debt(d.id, remaining=3000)
    d = finance.pay_debt(d.id, 3000)
    assert d.closed and d.remaining == 0
    assert not any(r.debt_id == d.id for r in finance.list_recurring())
    with pytest.raises(F):                       # платить по закрытому нельзя
        finance.pay_debt(d.id, 100)


def test_debt_update_sync():
    from core.services import finance
    d = finance.add_debt("Ипотека", 500000, payment=20000, pay_day=5)
    d = finance.update_debt(d.id, payment=25000, pay_day=15)
    r = next(r for r in finance.list_recurring() if r.debt_id == d.id)
    assert r.amount == 25000 and r.day == 15
    with pytest.raises(finance.FinanceError):
        finance.update_debt(d.id, remaining=600000)
    with pytest.raises(finance.FinanceError):
        finance.update_debt(d.id, pay_day=32)
    # правка регулярного тянет долг
    finance.update_recurring(r.id, amount=30000)
    assert finance.find_debt(d.id).payment == 30000
    assert finance.delete_debt(d.id)
    assert not any(r.debt_id == d.id for r in finance.list_recurring(active_only=False))


def test_transaction_update_and_accounts():
    from core.services import finance
    F = finance.FinanceError
    main = finance.main_account_name()
    finance.set_balance(main, 10000)
    t = finance.add_transaction(1000, "expense", note="такси")
    assert finance.summary(1)["total_balance"] == 9000
    finance.update_transaction(t.id, amount=1500)
    assert finance.summary(1)["total_balance"] == 8500
    finance.update_transaction(t.id, kind="income")
    assert finance.summary(1)["total_balance"] == 11500
    with pytest.raises(F):
        finance.add_transaction(0, "expense")
    with pytest.raises(F):
        finance.add_transaction(100, "transfer", account=main, to_account=main)
    with pytest.raises(F):
        finance.add_transaction(100, "expense", account="Несуществующий")
    a = finance.add_account("Сбер", "bank", 500)
    with pytest.raises(F):
        finance.add_account("Сбер")
    finance.add_transaction(200, "transfer", account=main, to_account="Сбер")
    accs = {x.name: x.balance for x in finance.list_accounts()}
    assert accs["Сбер"] == 700 and accs[main] == 11300
    with pytest.raises(F):                        # есть операции — удалить нельзя
        finance.delete_account(a.id)
    finance.update_account(a.id, name="Сбербанк")
    assert finance.list_transactions(1)[0].to_account == "Сбербанк"


def test_natural_language_routing():
    """«ужин в 7 вечера» → событие сегодня 19:00; «починить полку» → задача; «до пятницы» → дедлайн."""
    from core.services import calendar, tasks
    r = run("ужин в 7 вечера")
    assert "add_event" in r.actions
    ev = calendar.list_events(datetime.now().replace(hour=0), datetime.now() + timedelta(days=2))[-1]
    assert ev.title == "Ужин" and ev.start.hour == 19
    r = run("надо починить полку")
    assert "add_task" in r.actions and tasks.list_tasks()[-1].title == "Починить полку"
    r = run("починить полку")            # дубль не создаётся
    assert len([t for t in tasks.list_tasks() if t.title == "Починить полку"]) == 1
    r = run("сдать отчёт до пятницы")
    assert "add_task" in r.actions
    t = next(t for t in tasks.list_tasks() if t.title == "Сдать отчёт")
    assert t.due and t.due.weekday() == 4 and t.due.hour == 23
    r = run("завтра в 15 иван")
    assert "add_event" in r.actions


def test_recurring_and_edit_from_chat():
    from core.services import calendar
    r = run("йога каждый вт чт в 7 утра")
    assert "add_event" in r.actions and "вт, чт" in r.text
    ev = calendar.find_event("йога")
    assert ev.repeat == "weekly" and ev.repeat_days == "1,3"
    # в списке на 2 недели — 4 вхождения
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    occ = [e for e in calendar.list_events(start, start + timedelta(days=14), limit=500) if e.title == "Йога"]
    assert len(occ) == 4 and all(e.start.weekday() in (1, 3) for e in occ)
    r = run("перенеси йогу на 8")
    assert "update_event" in r.actions and calendar.find_event("йога").start.hour == 8
    r = run("переименуй йогу в утреннюю йогу")
    assert "update_event" in r.actions and calendar.find_event("утренн").title == "Утреннюю йогу"


def test_undo_any_action():
    from core.services import tasks
    run("задача протестировать откат")
    assert tasks.find_task("протестировать откат")
    r = run("не то, удали")
    assert "undo" in r.actions and tasks.find_task("протестировать откат") is None
    r = run("завтра в 9 планёрка")
    r = run("отмена")
    assert "undo" in r.actions and "Планёрка" in r.text


def test_delete_and_skip_from_chat():
    from core.services import calendar
    run("задача купить лампочки")
    r = run("удали задачу про лампочки")
    assert "delete_task" in r.actions
    run("тренировка каждый день в 19")
    r = run("сегодня тренировки не будет")
    assert "update_event" in r.actions
    ev = calendar.find_event("тренировка")
    assert datetime.now().date().isoformat() in ev.skip_dates
    r = run("удали тренировку")
    assert "delete_event" in r.actions and calendar.find_event("тренировка") is None


def test_budgets_and_safe_to_spend():
    from core.services import finance
    c = finance.add_category("Кофейни", "expense", "☕", "кофейня,starbucks", budget=3000)
    finance.add_transaction(2500, "expense", None, "starbucks", source="test")
    b = [x for x in finance.budgets() if x["name"] == "Кофейни"][0]
    assert b["spent"] == 2500 and b["status"] == "warn"
    safe = finance.safe_to_spend()
    assert safe["days_left"] >= 1 and "per_day" in safe
    finance.delete_category(c.id)


def test_task_deadline_reminders():
    from core.services import tasks
    t = tasks.add_task("Сдать отчёт (тест напоминаний)", datetime.now() + timedelta(minutes=30))
    rem = tasks.due_task_reminders()
    texts = [txt for tk, txt in rem if tk.id == t.id]
    assert texts and ("Сегодня дедлайн" in texts[0] or "остался" in texts[0])
    assert not [1 for tk, _ in tasks.due_task_reminders() if tk.id == t.id]  # повторно не шлём
    tasks.delete_task(t.id)


def test_pending_survives_restart():
    from core.brain import agent
    r = run("в пятницу что-то непонятное")
    assert "clarify" in r.actions
    assert agent._pending_get("test")  # хранится в БД, а не в памяти
    r = run("задача")
    assert "add_task" in r.actions


def test_cloud_vs_local_routing():
    from core.brain.agent import is_personal
    cloud = ["привет как дела", "что такое инфляция", "напиши поздравление другу", "расскажи анекдот", "спасибо", "почему небо голубое"]
    local = ["сколько у меня денег", "что у меня сегодня", "потратил 700 на такси", "добавь задачу купить хлеб", "завтра в 10 зубной",
             "покажи мои заметки", "мои долги", "какие у меня дела", "мысль: сделать ремонт"]
    assert all(not is_personal(t) for t in cloud), [t for t in cloud if is_personal(t)]
    assert all(is_personal(t) for t in local), [t for t in local if not is_personal(t)]


def test_tts_prepare():
    from core.voice import tts
    out = tts.prepare("Минус 700 ₽ · Еда. Встреча 10.09 в 15:30. Баланс Т-Банк: 85 000 ₽ 🧠 **ок** https://x.y/z")
    assert "семьсот рублей" in out and "десятое сентября" in out and "пятнадцать тридцать" in out
    assert "восемьдесят пять тысяч рублей" in out and "Ти-Банк" in out
    assert "http" not in out and "**" not in out and "🧠" not in out


def test_tts_html_escape_tg():
    from core.telegram.bot import _to_html
    assert _to_html("a < b & **c**") == "a &lt; b &amp; <b>c</b>"


def test_tg_text_is_routed_to_any_text():
    """Регрессия: декоратор @router.message(F.text) должен висеть на any_text, а не на соседней функции."""
    from core.telegram import bot as tg
    handlers = {h.callback.__name__ for h in tg.router.message.handlers}
    assert "any_text" in handlers
    assert "_keep_typing" not in handlers
    assert "voice_msg" in handlers and "anything_else" in handlers


def test_bulk_delete_is_confirmed_and_undoable():
    """«сотри все финансы за последние 2 дня» — не задача и не облако: вопрос → «да» → удалено → «отмена» вернула."""
    import asyncio
    from core.brain import agent
    from core.services import finance
    ch = "bulk-test"
    assert agent.is_personal("сотри все финансы за последние 2 дня")
    finance.add_transaction(123, "expense", None, "bulk тест", source="test")
    b0 = finance.summary(1)["total_balance"]
    r = asyncio.run(agent.handle("сотри все финансы за последние 2 дня", ch))
    assert r.actions == ["clarify"] and "Удалить" in r.text and "операц" in r.text
    r = asyncio.run(agent.handle("да", ch))
    assert r.actions == ["bulk_delete"]
    assert finance.summary(1)["total_balance"] != b0
    assert not [t for t in finance.list_transactions(3) if t.note == "bulk тест"]
    r = asyncio.run(agent.handle("отмена", ch))
    assert "Вернул" in r.text
    assert finance.summary(1)["total_balance"] == b0
    # «нет» — ничего не трогаем; точечное «удали задачу про …» не считается массовым
    from core.services import tasks
    tk = tasks.add_task("bulk задача", None, source="test")
    r = asyncio.run(agent.handle("удали задачи за неделю", ch))
    assert r.actions == ["clarify"]
    r = asyncio.run(agent.handle("нет", ch))
    assert "Отбой" in r.text and tasks.find_task(tk.id) is not None
    tasks.delete_task(tk.id)
    assert agent._bulk_rule("удали задачу про полку", ch) is None


# ---------- v0.7.0: ПК-команды, аналитика, импорт выписок ----------
def test_pc_parse():
    from core.services import pc
    assert pc.parse("открой ютуб").action == "open_url"
    assert pc.parse("найди файл договор").arg == "договор"
    assert pc.parse("пауза").arg == "pause"
    assert pc.parse("что на экране").action == "screen"
    assert pc.parse("статус костюма").action == "status"
    assert pc.parse("заблокируй компьютер").arg == "lock"
    # про данные ассистента — не ПК
    assert pc.parse("покажи задачи") is None
    assert pc.parse("открой календарь") is None
    assert pc.parse("найди встречу с ваней") is None


def test_pc_dispatch_offline():
    from core.services import pc
    pc.LAST_SEEN = 0
    assert "voice.bat" in pc.dispatch(pc.parse("открой ютуб"), "web")


def test_bank_import_csv_dedup():
    from core.services import bank_import as bi
    csv_tb = ("Дата операции;Статус;Сумма операции;Категория;Описание\n"
              "05.09.2026 18:22:10;OK;-1250,00;Супермаркеты;Пятёрочка\n"
              "03.09.2026 09:00:00;OK;-5000,00;Переводы;Перевод между своими счетами\n"
              "02.09.2026 10:00:00;FAILED;-900,00;Такси;Яндекс Такси\n"
              "01.09.2026 10:00:00;OK;80000,00;Зарплата;Зарплата ООО Ромашка\n").encode("cp1251")
    rows = bi.parse_csv(csv_tb)
    assert len(rows) == 3 and any(r.transfer for r in rows)
    r1 = bi.import_file("ops.csv", csv_tb)
    assert r1.added == 2 and r1.skipped_transfer == 1
    r2 = bi.import_file("ops.csv", csv_tb)
    assert r2.added == 0 and r2.skipped_dup == 2 and r2.skipped_transfer == 1


def test_insights_smoke():
    from core.services import insights
    f = insights.cash_forecast(30)
    assert len(f["points"]) == 31 and "text" not in f
    assert isinstance(insights.detect_subscriptions(), list)
    st = insights.streak()
    assert st["current"] >= 0 and st["best"] >= st["current"]
    assert isinstance(insights.upcoming_birthdays(30), list)


def test_birthdays_only_yearly():
    """Разовое «иду на др 12-го» — обычный план; праздником считается только ежегодное событие."""
    from core.services import calendar as cal, insights
    from datetime import datetime as _dt, timedelta as _td
    soon = _dt.now().replace(hour=12, minute=0, second=0, microsecond=0) + _td(days=2)
    cal.add_event("иду на др к Пете", soon, 60)
    assert insights.upcoming_birthdays(7) == []
    cal.add_event("др мамы", soon, 60, repeat="yearly")
    names = [b["who"] for b in insights.upcoming_birthdays(7)]
    assert names == ["мамы"]


def test_answer_cache_key():
    from core.brain.agent import _cache_key
    assert _cache_key("что такое инфляция", "web")
    assert _cache_key("какая сегодня погода", "web") is None
    assert _cache_key("привет", "web") is None


# ---------------------------------------------------------------- v0.8.0: быстрые правила, нечёткий поиск, Google-очередь
@pytest.mark.parametrize("text,amount,rest", [
    ("-350 кофе", 350, "кофе"), ("1200 5-го", 1200, "5-го"), ("700 р ресторан", 700, "ресторан"), ("1 200 000 квартира", 1_200_000, "квартира"),
])
def test_amount_no_false_thousands(text, amount, rest):
    a, r = parse_amount(text)
    assert a == amount and r == rest


def test_past_dates():
    dt, _ = parse_datetime("потратил на еду вчера", NOW)
    assert dt.date() == (NOW - timedelta(days=1)).date()
    dt, _ = parse_datetime("до 5 сентября", NOW)      # два дня назад — та же дата, а не через год
    assert dt.year == NOW.year and dt.month == 9 and dt.day == 5


def test_fuzzy_match():
    from core.services.match import same, score
    assert same("еду", "еда") and same("встречу", "встреча") and same("ваней", "ваня")
    assert not same("еда", "такси")
    assert score("Встреча с Ваней", "встречу с ваней") == 1.0


def test_quick_finance_rules():
    from core.services import finance
    run("баланс т-банк 50000")
    r = run("потратил 1200 на еду вчера")
    assert "Еда" in r.text
    r = run("700 такси")
    assert "Транспорт" in r.text
    r = run("сколько потратил на еду")
    assert "1 200" in r.text
    r = run("лимит на еду 20000")
    assert "20 000" in r.text
    run("долг Ване 10000")
    r = run("заплатил ване 2000")
    assert "8 000" in r.text
    r = run("закрой долг ване")
    assert "закрыт" in r.text
    assert not [d for d in finance.list_debts() if "ван" in d.title.lower()]
    r = run("снял 3000 наличных")
    assert "Наличные" in r.text
    r = run("подписка яндекс плюс 399 25-го")
    assert "25-е" in r.text
    r = run("отмени подписку яндекс")
    assert "остановлен" in r.text
    assert run("спасибо").via == "rules"


def test_agenda_and_move_by_case():
    from core.services import calendar
    run("встреча с Ваней в четверг в 15")
    r = run("перенеси встречу с ваней на пятницу")
    assert "Перенёс" in r.text
    ev = calendar.find_event("встречу с ваней")
    assert ev and ev.start.weekday() == 4
    r = run("что в пятницу")
    assert "Ваней" in r.text
    r = run("задача позвонить врачу завтра в 10")
    assert "add_task" in r.actions and "Позвонить врачу" in r.text


def test_remind_without_time_then_answer():
    r = run("напомни маме позвонить")
    assert "когда" in r.text
    r = run("завтра в 10")
    assert "Маме позвонить" in r.text and "10:00" in r.text


def test_gcal_queue_offline(monkeypatch):
    """Google включён, но сети нет (или нет event loop) → операции копятся в очереди, ничего не падает."""
    from core.services import calendar, gcal
    monkeypatch.setattr(gcal, "enabled", lambda: True)
    monkeypatch.setattr(gcal, "connected", lambda: True)
    ev = calendar.add_event("Тест Google", datetime(2030, 1, 1, 10, 0))
    q = gcal._queue()
    assert any(x["event_id"] == ev.id and x["op"] == "push" for x in q)
    body = gcal._body(ev)
    assert body["summary"] == "Тест Google" and body["start"]["timeZone"]
    calendar.update_event(ev.id, repeat="weekly", repeat_days=[0, 2])
    with db.session() as s:
        ev2 = s.get(db.Event, ev.id)
        assert "BYDAY=MO,WE" in gcal._body(ev2)["recurrence"][0]


def test_strip_think():
    from core.brain import llm
    assert llm.strip_think("<think>рассуждаю…</think>Готово, сэр.") == "Готово, сэр."
    assert llm.strip_think("Ответ без мыслей") == "Ответ без мыслей"
    # незакрытый <think> с черновиками — берём последний абзац
    t = "<think>\nThe user wants…\n\n— Option 1: Это не мем.\n\nОго, какая мотивация! Коллега знает, чем брать.</think>"
    assert "Option" not in llm.strip_think(t)
    t2 = "<think>анализ\n\nВариант 2 (игривый): Ого, какая мотивация!"
    assert llm.strip_think(t2).startswith("Ого")


def test_brain_prefix_saves_note():
    import asyncio
    from core.brain import agent
    from core.services import brain_notes
    r = asyncio.run(agent.handle("мозг- идея для ролика про кофе", channel="test"))
    assert "add_note" in r.actions
    n = brain_notes.list_notes(1)[0]
    assert "идея для ролика про кофе" in (n.raw or n.text)
    brain_notes.delete_note(n.id)
    # «мозговой штурм» — не префикс
    assert agent.NOTE_RX.match("мозговой штурм завтра") is None


def test_note_with_image(tmp_path):
    from core.services import brain_notes
    from PIL import Image
    import io
    buf = io.BytesIO(); Image.new("RGB", (2400, 1200), (200, 30, 30)).save(buf, "PNG")
    rel = brain_notes.save_image(buf.getvalue())
    f = brain_notes.MEDIA_DIR / rel
    assert f.is_file() and rel.endswith(".jpg")
    assert max(Image.open(f).size) <= 1600
    n = brain_notes.add_note("тест фото", source="test", image=rel, polish=False)
    assert n.image == rel and n.polished
    assert brain_notes.delete_note(n.id)
    assert not f.exists()


def test_media_endpoint():
    from fastapi.testclient import TestClient
    from core.api.app import app
    from core.services import brain_notes
    from PIL import Image
    import io
    buf = io.BytesIO(); Image.new("RGB", (10, 10)).save(buf, "JPEG")
    rel = brain_notes.save_image(buf.getvalue())
    c = TestClient(app)
    assert c.get(f"/media/{rel}").status_code == 200
    # клиент нормализует «..», поэтому шлём закодированный вариант — он доходит до обработчика как есть
    assert c.get("/media/%2e%2e/config.yaml").status_code in (404, 400)
    assert c.get("/media/2099-01/nope.jpg").status_code == 404
    (brain_notes.MEDIA_DIR / rel).unlink()


def test_finance_question_is_rule_not_llm():
    """«что по финансам» — сводка из базы правилом, без похода в LLM (LLM выдумывала цифры)."""
    from core.brain import agent
    for t in ("что по финансам", "Что там по деньгам?", "как у меня с балансом", "чё по бабкам"):
        r = agent.rules(t, "test")
        assert r is not None and "finance_summary" in r.actions, t
    assert "list_tasks" in agent.rules("что по задачам", "test").actions


def test_recheck_is_not_a_note():
    """«откуда ты взял… сверься» — перепроверка, а не заметка в мозг."""
    from core.brain import agent
    t = "откуда ты взял эти значения, у меня же там другие данные сейчас, сверься"
    assert agent._looks_like_question(t)
    assert agent._forced_tool("сколько у меня денег") == ("finance_summary", {"days": 30})
    assert agent._forced_tool("потратил 700 на еду") is None
    assert agent._forced_tool("что такое инфляция") is None
    r = agent.rules(t, "test")
    assert r is not None and "finance_summary" in r.actions and "Перечитал" in r.text


def test_analysis_request_not_recorded():
    """«…разбери ситуацию, а не записывай» — длинный рассказ с суммами не должен стать событием/заметкой по шаблону."""
    from core.brain import agent
    t = ("что по финансам, завтра еще должно придти за монтаж роликов 8500, и 22000 с сдачи квартиры, "
         "но 28500 нужно будет потратить 11 числа на пошлину. разбери ситуацию а не записывай куда то")
    assert agent.rules(t, "test") is None
    assert agent._is_analysis(t) and agent._forced_tool(t) is None
    # короткие команды с двумя суммами по-прежнему работают шаблоном
    assert "add_debt" in agent.rules("долг Сберу 120к плачу 8к 25-го", "test").actions
    assert agent.rules("сдача квартиры завтра в 10", "test") is None or "add_event" in agent.rules("сдача квартиры завтра в 10", "test").actions
