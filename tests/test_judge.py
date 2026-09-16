"""Этап Г: судья на спорных фразах, «это задача/заказ» → откат + перезапись + урок, малая модель, регрессии «записал одно — сделал другое»."""
import asyncio
import json
import os

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


def _brain(monkeypatch, answer, ollama=True, cloud=False):
    """Судья отвечает `answer(user_text)` через small_chat (локально) и/или cloud_chat; эмбеддинги выключены."""
    from core.brain import llm
    monkeypatch.setattr(llm, "cloud_enabled", lambda: cloud)

    async def fake_small(system, user, json_mode=True, num_predict=200):
        return answer(user) if callable(answer) else answer
    monkeypatch.setattr(llm, "small_chat", fake_small)

    async def fake_cloud(system, user, history=None, **kw):
        return answer(user) if callable(answer) else answer
    monkeypatch.setattr(llm, "cloud_chat", fake_cloud)

    async def avail(force=False):
        return ollama
    monkeypatch.setattr(llm, "ollama_available", avail)

    async def no_embed():
        return False
    monkeypatch.setattr(llm, "embed_available", no_embed)
    monkeypatch.setattr(llm, "GEMINI_AUTO", False)


def _sure(kind, conf=0.95):
    return json.dumps({"kind": kind, "confidence": conf})


def _handle(text, ch="judge-test"):
    from core.brain import agent
    return asyncio.run(agent.handle(text, ch))


# ---------------------------------------------------------------- спорные фразы
def test_disputed_detection():
    from core.brain import agent
    assert agent._disputed("сайт 15000")                                # сумма + слово без категории
    assert agent._disputed("отдал Ване 2000") == ("expense", "debt", "income")
    assert agent._disputed("потратил 700 на такси") is None            # явный глагол — шаблон
    assert agent._disputed("кофе 350") is None                          # известная категория — шаблон
    assert agent._disputed("встреча завтра в 15:00") is None
    assert agent._disputed("сколько я потратил на еду?") is None
    assert agent._disputed("получил 30000 аванс") is None


def test_judge_sure_writes_order_not_expense(monkeypatch):
    """Регрессия «записал одно — сделал другое»: «логотип для Кати 8к» раньше падало в траты «Другое»."""
    from core.services import pulse
    monkeypatch.setattr(pulse, "enabled", lambda: True)
    _brain(monkeypatch, _sure("order"))
    r = _handle("логотип для Кати 8к")
    assert "add_order" in r.actions and "judge" in r.actions
    with db.session() as s:
        assert s.exec(db.select(db.Transaction)).first() is None
        o = s.exec(db.select(db.Order)).first()
        assert o and o.price == 8000 and o.client_id


def test_judge_unsure_asks_then_learns(monkeypatch):
    """Не уверен → вопрос с вариантами → ответ одним словом пишет и становится уроком → похожая фраза без вопроса."""
    _brain(monkeypatch, _sure("expense", 0.5))
    r = _handle("сайт 15000")
    assert "clarify" in r.actions and "трата" in r.text and "доход" in r.text
    r = _handle("доход")
    assert "add_income" in r.actions and "lesson" in r.actions
    with db.session() as s:
        tx = s.exec(db.select(db.Transaction)).all()
        assert len(tx) == 1 and tx[0].kind == "income" and tx[0].amount == 15000
        assert s.exec(db.select(db.Lesson)).one().kind == "income"
    # похожая фраза — урок, без судьи и без вопроса (судья сейчас сказал бы «expense» — но урок важнее)
    _brain(monkeypatch, _sure("expense", 0.99))
    r = _handle("сайт 22000")
    assert "add_income" in r.actions and "clarify" not in r.actions
    assert "если не то" not in r.text


def test_judge_unavailable_falls_back_to_rules(monkeypatch):
    """Ни модели, ни облака — поведение как до судьи: шаблон «700 такси»/«сайт 15000» → как раньше."""
    _brain(monkeypatch, "", ollama=False, cloud=False)
    r = _handle("сайт 15000")
    assert "clarify" in r.actions or "add_expense" in r.actions or r.via in ("none", "rules")
    assert "judge" not in r.actions


def test_judge_disabled(monkeypatch):
    from core.services import judge
    monkeypatch.setattr(judge, "enabled", lambda: False)
    _brain(monkeypatch, _sure("order"))
    r = _handle("отдал Ване 2000")
    assert "judge" not in r.actions


# ---------------------------------------------------------------- «это задача»
def test_fix_moves_expense_to_debt(monkeypatch):
    """«отдал Ване 2000» записалось тратой → «это долг» → трата откачена, долг записан, урок сохранён."""
    from core.services import finance
    _brain(monkeypatch, _sure("expense"))
    r = _handle("отдал Ване 2000")
    assert "add_expense" in r.actions
    r = _handle("это долг")
    assert "fix" in r.actions and "add_debt" in r.actions and "Переложил" in r.text
    with db.session() as s:
        assert [t for t in s.exec(db.select(db.Transaction)).all() if t.kind == "expense"] == []
        d = s.exec(db.select(db.Debt)).one()
        assert d.remaining == 2000 and "ване" in d.title.lower()
        l = s.exec(db.select(db.Lesson)).one()
        assert l.kind == "debt" and l.wrong == "expense"
    # второй раз — сразу долг
    r = _handle("отдал Ване 3000")
    assert "add_debt" in r.actions and "clarify" not in r.actions


def test_fix_event_to_task_and_nothing_to_fix(monkeypatch):
    from core.services import tasks, calendar
    _brain(monkeypatch, "", ollama=False)
    r = _handle("зубной завтра в 9")
    assert "add_event" in r.actions
    r = _handle("это задача")
    assert "add_task" in r.actions and "fix" in r.actions
    assert [e for e in calendar.list_events() if "зубн" in e.title.lower()] == [] if hasattr(calendar, "list_events") else True
    assert any("зубн" in t.title.lower() and t.due for t in tasks.list_tasks())
    r = _handle("это задача")   # уже так
    assert "fix" not in r.actions and "Так и записано" in r.text
    r = _handle("что сегодня")
    r = _handle("это заметка")   # последняя запись — задача, «это заметка» её переложит: проверим только что не падает
    assert r.text


def test_fix_requires_recent_action(monkeypatch):
    _brain(monkeypatch, "", ollama=False)
    r = _handle("это трата")
    assert "fix" not in r.actions and "Исправлять нечего" in r.text


def test_fix_is_not_triggered_by_normal_text(monkeypatch):
    from core.brain import agent
    for t in ("это была хорошая встреча с командой", "задача: купить корм", "это долго", "мысль: это заказ мечты"):
        assert agent.FIX_RX.match(t) is None, t
    assert agent.FIX_RX.match("это заказ")
    assert agent.FIX_RX.match("нет, это была трата")
    assert agent.FIX_RX.match("не трата, а долг")
    assert agent.FIX_RX.match("запиши как задачу")


# ---------------------------------------------------------------- малая модель
def test_small_chat_falls_back_to_main_model(monkeypatch):
    from core.brain import llm
    calls = []

    async def fake_ollama_chat(messages, tools=None, temperature=0.3, json_mode=False):
        calls.append(messages[0]["content"][:10]); return {"content": '{"kind":"task","confidence":0.9}', "tool_calls": []}
    monkeypatch.setattr(llm, "ollama_chat", fake_ollama_chat)
    monkeypatch.setattr(llm, "SMALL_MODEL", "")
    assert json.loads(asyncio.run(llm.small_chat("sys", "usr")))["kind"] == "task"
    assert calls
    monkeypatch.setattr(llm, "SMALL_MODEL", "qwen2.5:1.5b")
    llm._SMALL_MISSING.add("qwen2.5:1.5b")   # не скачана → тоже основная
    assert not llm.small_model_active()
    asyncio.run(llm.small_chat("sys", "usr"))
    assert len(calls) == 2
    llm._SMALL_MISSING.discard("qwen2.5:1.5b")


# ---------------------------------------------------------------- связки между системами (Г5)
def test_family_prefix_creates_family_not_client(monkeypatch):
    """«Семья: мама» раньше проваливалось в модель («мозг не запущен»); теперь карточка семьи."""
    from core.services import people
    _brain(monkeypatch, "", ollama=False)
    r = _handle("Семья: мама")
    assert "add_person" in r.actions and "Семья" in r.text
    assert people.find_person("мама").kind == "family"
    r = _handle("друг: Петя, сосед")
    assert people.find_person("Петя").kind == "friend"


def test_done_future_event_asks_instead_of_not_found(monkeypatch):
    """«сделал встреча с мамой» про субботнюю встречу: раньше «не нашёл», теперь вопрос → «да» ставит галочку."""
    from core.services import calendar
    _brain(monkeypatch, "", ollama=False)
    _handle("встреча с мамой через 3 дня в 12")
    r = _handle("сделал встреча с мамой")
    assert "clarify" in r.actions and "не наступило" in r.text
    r = _handle("да")
    assert "complete_event" in r.actions
    ev = calendar.find_event("встреча с мамой")
    assert calendar.is_done(ev)


def test_order_payment_closes_and_card_reflects(monkeypatch):
    from core.services import people
    _brain(monkeypatch, "", ollama=False)
    _handle("клиент: Пётр")
    _handle("заказ: сайт для Петра 40к")
    r = _handle("пришло 20000 от Петра")
    assert "order_payment" in r.actions and "Осталось 20 000" in r.text
    r = _handle("что по Петру")
    assert "person_card" in r.actions and "ждёт оплаты 20 000" in r.text
    assert people.find_person("Пётр").kind == "client"


# ---------------------------------------------------------------- проактив (Г3)
def test_proactive_candidates_limit_quiet_and_mute(monkeypatch):
    from datetime import datetime, timedelta
    from core.services import proactive, tasks, memory
    _brain(monkeypatch, "", ollama=False)
    t = tasks.add_task("Разобрать балкон", None, source="test")
    with db.session() as s:
        row = s.get(db.Task, t.id); row.created_at = datetime.now() - timedelta(days=8); s.add(row); s.commit()
    memory.add_fact_sync("Простудился, лечится дома", layer="short", category="здоровье")
    with db.session() as s:
        f = s.exec(db.select(db.Fact)).one(); f.created_at = datetime.now() - timedelta(days=3); s.add(f); s.commit()
    c = proactive.candidates()
    assert {x["key"].split(":")[0] for x in c} == {"stale", "health"}
    # тихие часы — молчим; лимит 0 — молчим
    assert asyncio.run(proactive.tick(quiet=True)) is None
    monkeypatch.setattr(proactive, "per_day", lambda: 0)
    assert asyncio.run(proactive.tick()) is None
    monkeypatch.setattr(proactive, "per_day", lambda: 5)
    one = asyncio.run(proactive.tick())
    assert one and one["key"].startswith("stale") and one["buttons"]
    # тот же повод второй раз не всплывает; следующий тик — про здоровье
    two = asyncio.run(proactive.tick())
    assert two and two["key"].startswith("health")
    assert asyncio.run(proactive.tick()) is None
    # «не надо про это» — тема замьючена, даже новый ключ не пройдёт
    assert proactive.act("mute", t.id, "stale").startswith("Понял")
    with db.session() as s:
        row = s.get(db.Task, t.id); row.created_at = datetime.now() - timedelta(days=20); s.add(row); s.commit()
    assert all(not x["key"].startswith("stale") for x in proactive.candidates())
    assert proactive._today_count() == 2


def test_proactive_task_button(monkeypatch):
    from datetime import datetime, timedelta
    from core.services import proactive, tasks, memory
    _brain(monkeypatch, "", ollama=False)
    memory.add_fact_sync("Хочет на неделе позвонить маме", layer="short")
    with db.session() as s:
        f = s.exec(db.select(db.Fact)).one(); f.created_at = datetime.now() - timedelta(days=2); s.add(f); s.commit()
    c = proactive.candidates()
    assert c and c[0]["key"].startswith("plan")
    msg = proactive.act("task", int(c[0]["key"].split(":")[1]), "plan")
    assert "Поставил задачу" in msg
    assert any("позвонить маме" in t.title.lower() for t in tasks.list_tasks())
    assert proactive.candidates() == []   # задача есть — повод исчез


def test_remind_from_conversation(monkeypatch):
    """Нейронка в извлекателе предложила напоминание → задача с источником proactive, «отмени» её откатывает."""
    from core.services import memory, tasks, undo
    from core.brain import llm
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)

    async def fake_cloud(system, user, history=None, **kw):
        return json.dumps({"add": [], "update": [], "remind": {"title": "Продлить домен", "when": None}})
    monkeypatch.setattr(llm, "cloud_chat", fake_cloud)

    async def no(force=False):
        return False
    monkeypatch.setattr(llm, "ollama_available", no)

    async def no_embed():
        return False
    monkeypatch.setattr(llm, "embed_available", no_embed)
    r = asyncio.run(memory.extract("кстати домен у меня в конце месяца кончается, надо бы не забыть продлить"))
    assert r["remind"] and r["remind"]["title"] == "Продлить домен"
    assert any(t.title == "Продлить домен" and t.source == "proactive" for t in tasks.list_tasks())
    assert asyncio.run(memory.extract("кстати домен у меня в конце месяца кончается, надо бы не забыть продлить"))["remind"] is None  # дубль
    assert "задачу" in undo.undo_last()
    assert not any(t.title == "Продлить домен" for t in tasks.list_tasks())


def test_style_in_context(monkeypatch):
    from core.services import memory
    from core.brain import llm, agent
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)

    async def fake_cloud(system, user, history=None, **kw):
        return "— пишет коротко, без точек\n— «мопс» = встреча с Мопсовым\n— не любит длинные ответы"
    monkeypatch.setattr(llm, "cloud_chat", fake_cloud)

    async def no(force=False):
        return False
    monkeypatch.setattr(llm, "ollama_available", no)

    async def no_embed():
        return False
    monkeypatch.setattr(llm, "embed_available", no_embed)
    assert asyncio.run(memory.rebuild_style(force=True)) == ""   # мало реплик — не собираем
    for i in range(25):
        agent._log_chat("user", f"кофе {100 + i}", "test")
    st = asyncio.run(memory.rebuild_style(force=True))
    assert "мопс" in st
    ctx = asyncio.run(memory.context("привет"))
    assert "КАК ОН ПИШЕТ" in ctx and "мопс" in ctx
