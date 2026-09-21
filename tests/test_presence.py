"""0.10.0 — persistent assistant: presence/state, events, attention, aims → focus, timeline, decisions, health, security."""
import asyncio
import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("ASSISTANT_TEST", "1")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from core import db
    from sqlmodel import create_engine
    from sqlalchemy import event
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    from core.services import events, state
    from core.brain import attention
    events.reset(); state.reset(); attention.clear()
    yield


def _say(text, channel="web"):
    from core.brain import agent
    return asyncio.run(agent.handle(text, channel))


# ---------------------------------------------------------------- 1. события: дедуп и журнал
def test_events_dedup_and_journal():
    from core.services import events
    from core.db import Memory, session
    from sqlmodel import select
    got = []
    events.on("user_arrived", got.append)
    e1 = events.emit("user_arrived", key="pc", dedup_sec=60)
    e2 = events.emit("user_arrived", key="pc", dedup_sec=60)
    assert e1 and e2 is None and len(got) == 1          # второй за минуту — подавлен
    assert events.emit("user_arrived", key="other", dedup_sec=60)   # другой ключ — проходит
    with session() as s:
        rows = s.exec(select(Memory).where(Memory.kind == "presence")).all()
    assert len(rows) == 2 and "сел за компьютер" in rows[0].text


# ---------------------------------------------------------------- 2. присутствие: сел → отошёл → вернулся, offline
def test_presence_lifecycle():
    from core.services import events, state
    t0 = datetime(2026, 9, 18, 10, 0)
    state.tick("Blender", "", "работа", 0, now=t0)
    assert state.snapshot(t0)["presence"] == "active"
    state.tick("Blender", "", "работа", 7 * 60, now=t0 + timedelta(minutes=8))
    assert state.snapshot()["presence"] == "idle"
    state.tick("Blender", "", "работа", 31 * 60, now=t0 + timedelta(minutes=32))
    assert state.snapshot()["presence"] == "away"
    state.tick("Chrome", "", "браузер", 2, now=t0 + timedelta(minutes=33))
    kinds = [e.kind for e in events.recent(20)]
    assert kinds[:4] == ["user_arrived", "user_idle", "user_away", "user_back"] or "user_back" in kinds
    state.offline_check(now=t0 + timedelta(minutes=40))
    assert state.snapshot()["presence"] == "offline"
    assert state.line() == ""          # ничего не знаем — в промпт ничего не подмешиваем


# ---------------------------------------------------------------- 3. строка для промпта без заголовков окон
def test_state_line_has_no_window_titles():
    from core.services import state
    t0 = datetime(2026, 9, 18, 10, 0)
    state.tick("Chrome", "ПАРОЛЬ от банка 1234 — Google Chrome", "браузер", 0, now=t0)
    state.tick("Chrome", "ПАРОЛЬ от банка 1234 — Google Chrome", "браузер", 0, now=t0 + timedelta(minutes=50))
    line = state.line(t0 + timedelta(minutes=50))
    assert "за ПК 50 мин" in line and "браузер" in line and "ПАРОЛЬ" not in line and "1234" not in line


# ---------------------------------------------------------------- 4. перезапуск ≠ первый запуск, pending переживает
def test_restart_restores_session_and_reports_gap():
    from core.services import events, state
    t0 = datetime(2026, 9, 18, 10, 0)
    state.tick("Blender", "", "работа", 0, now=t0)
    state.tick("Blender", "", "работа", 0, now=t0 + timedelta(minutes=30))
    state.shutdown(now=t0 + timedelta(minutes=30))
    state.reset()
    info = state.restore(now=t0 + timedelta(minutes=33))
    assert not info["first_run"] and info["gap_min"] == 3 and info["clean"] is True
    state.tick("Blender", "", "работа", 0, now=t0 + timedelta(minutes=34))
    assert state.snapshot(t0 + timedelta(minutes=34))["session_min"] == 34   # сессия продолжилась, а не началась заново
    assert any(e.kind == "restart" for e in events.recent(20))


# ---------------------------------------------------------------- 5. attention: тихие часы / бюджет / занят / нет за ПК
def test_attention_decides_now_later_silent(monkeypatch):
    from core.brain import attention, llm
    from core.services import state
    monkeypatch.setattr(llm, "user_recent", lambda *_: False)
    day = datetime(2026, 9, 18, 14, 0)
    night = datetime(2026, 9, 18, 2, 0)
    assert attention.decide("x", 2, now=night).verdict == "later"
    assert attention.decide("x", 1, now=night).verdict == "silent"
    assert attention.decide("x", 2, urgent=True, now=night).verdict == "now"
    # нет за ПК → later
    state.tick("Blender", "", "работа", 40 * 60, now=day)
    assert attention.decide("x", 2, now=day).verdict == "later"
    # за ПК давно, не занят → now
    state.reset()
    state.tick("Chrome", "", "браузер", 0, now=day - timedelta(minutes=10))
    state.tick("Chrome", "", "браузер", 0, now=day)
    assert attention.decide("x", 2, now=day).verdict == "now"
    # бюджет
    for _ in range(attention.budget_left(day)):
        attention.spend(day)
    assert attention.budget_left(day) == 0
    assert attention.decide("x", 2, now=day).verdict == "silent"
    assert attention.decide("x", 3, now=day).verdict == "now"   # важное — проходит и без бюджета


# ---------------------------------------------------------------- 6. отложенное отдаётся при возвращении
def test_deferred_queue_delivered_when_user_back(monkeypatch):
    from core.brain import attention, llm
    from core.services import scheduler, state
    monkeypatch.setattr(llm, "user_recent", lambda *_: False)
    monkeypatch.setattr(scheduler, "_quiet_now", lambda: False)
    monkeypatch.setattr(attention, "quiet_hours", lambda *_: False)   # прогон в 7 утра не должен «молчать» из-за тихих часов
    sent = []

    async def notify(text, buttons=None):
        sent.append(text)
    sch = scheduler.build(notify)
    day = datetime.now().replace(hour=14, minute=0)
    # человек ушёл — сообщение уходит в очередь, не отправляется
    state.tick("Blender", "", "работа", 40 * 60, now=day)
    n = sch.get_job("presence_tick")
    attention.defer("test", "пока тебя не было: X", 2)
    assert attention.queue_size() == 1
    asyncio.run(n.func())
    assert sent == []                                   # away — молчим
    # вернулся, «отогрелся» 2+ минуты → отдали
    state.reset()
    state.tick("Chrome", "", "браузер", 0, now=datetime.now() - timedelta(minutes=5))
    state.tick("Chrome", "", "браузер", 0)
    asyncio.run(n.func())
    assert any("пока тебя не было" in t for t in sent) and attention.queue_size() == 0


# ---------------------------------------------------------------- 7. цель → веха → задача → прогресс, фокус дня
def test_aims_focus_and_progress():
    from core.services import aims, tasks
    r = _say("цель: собрать портфолио до конца года, чтобы брать заказы дороже")
    assert "add_aim" in r.actions
    a = aims.list_aims()[0]
    assert a["title"] == "Собрать портфолио" and a["why"] == "брать заказы дороже" and a["due"].month == 12
    assert "add_milestone" in _say("веха: 3 сцены").actions
    assert "add_task" in _say("задача: сцена кухни к вехе 3 сцены").actions
    assert "add_task" in _say("задача: сцена спальни к вехе 3 сцены").actions
    f = aims.focus()
    assert f["items"][0]["title"] == "Сцена кухни" and f["items"][0]["aim"] == "Собрать портфолио"
    r = _say("сделал сцену кухни")
    assert "complete_task" in r.actions and "Шаг к «Собрать портфолио»" in r.text and "Следующий: «Сцена спальни»" in r.text
    assert aims.progress(a["id"]) == 0.5
    r = _say("сделал сцену спальни")
    assert "последняя веха" in r.text and "цель достигнута" in r.text   # цель не закрывается сама — спрашиваем
    assert "Собрать портфолио — 100%" in _say("мои цели").text
    # денежный конверт («цель: подушка 300к») — по-прежнему goals, а не aims
    assert "add_goal" in _say("цель: подушка 300к к марту").actions
    assert len(aims.list_aims()) == 1


# ---------------------------------------------------------------- 8. заблокированная задача не в фокусе
def test_blocked_task_leaves_focus():
    from core.services import aims
    _say("цель: сайт студии")
    _say("задача: сверстать главную к цели сайт")
    assert aims.focus()["items"][0]["title"] == "Сверстать главную"
    r = _say("сверстать главную заблокирована: жду макет от дизайнера")
    assert "block_task" in r.actions
    f = aims.focus()
    assert not any(i["title"] == "Сверстать главную" for i in f["items"]) and f["blocked"][0]["blocked_by"] == "жду макет от дизайнера"
    assert "Мешает" in _say("что мне сегодня делать?").text
    _say("сверстать главную разблокирована")
    assert aims.focus()["items"][0]["title"] == "Сверстать главную"


# ---------------------------------------------------------------- 9. лента дня сшивает источники
def test_timeline_merges_sources():
    from core.services import timeline
    _say("задача: позвонить в банк")
    _say("сделал позвонить в банк")
    _say("решил: не беру мелкие заказы, потому что съедают день")
    items = timeline.build()
    texts = [i["text"] for i in items]
    assert any("Позвонить в банк" in t and "Выполнено" in t for t in texts)
    assert any("не беру мелкие заказы" in t for t in texts)
    assert any(i["kind"] == "chat" for i in items)
    assert all(i["kind"] != "chat" or "сообщ" in i["text"] for i in items)   # тексты сообщений в ленту не попадают
    assert "банк" in timeline.text(query="банк") and "мелкие" not in timeline.text(query="банк")


# ---------------------------------------------------------------- 10. решения: записать и найти «почему»
def test_decisions_journal():
    r = _say("решил: беру заказ у Лены только с предоплатой, потому что в прошлый раз ждал месяц")
    assert "decision" in r.actions and "предоплатой" in r.text
    r = _say("почему я так решил про Лену")
    assert "ждал месяц" in r.text
    assert "предоплатой" in _say("мои решения").text


# ---------------------------------------------------------------- 11. самопроверка: человеческий вывод + событие один раз
def test_health_diagnose_and_event_once(monkeypatch):
    from core.brain import llm
    from core.services import events, health

    async def no(*a, **k):
        return False

    async def diag():
        return "Нет соединения"
    monkeypatch.setattr(llm, "ollama_available", no)
    monkeypatch.setattr(llm, "ollama_diagnose", diag)
    res = asyncio.run(health.diagnose())
    assert not res["ok"] and any(i["level"] == "bad" and "Ollama" in i["what"] for i in res["items"])
    health.record(res); health.record(res)
    assert len([e for e in events.recent(50) if e.kind == "health_bad"]) == 1
    r = _say("проверь себя")
    assert "diagnose" in r.actions and "Ollama" in r.text


# ---------------------------------------------------------------- 12. безопасность: выключение только после «да», пульс валидируется
def test_shutdown_needs_confirmation_and_ping_validation(monkeypatch):
    from core.services import pc
    from fastapi.testclient import TestClient
    from core.api.app import app
    sent = []
    monkeypatch.setattr(pc, "alive", lambda: True)
    monkeypatch.setattr(pc, "dispatch", lambda cmd, ch: sent.append(cmd.arg) or "ok")
    r = _say("выключи компьютер")
    assert "clarify" in r.actions and sent == []
    _say("нет")
    assert sent == []
    _say("выключи компьютер"); _say("да")
    assert sent == ["shutdown"]
    c = TestClient(app)
    assert c.post("/api/pc/ping", json={"mode": "idle", "screen": True, "app": "x" * 81, "title": "t", "idle_sec": 1}).status_code == 422
    assert c.post("/api/pc/ping", json={"mode": "idle", "screen": True, "app": "a", "title": "t", "idle_sec": -5}).status_code == 422
    assert c.post("/api/pc/ping", json={"mode": "idle", "screen": True, "app": "blender.exe", "title": "t", "idle_sec": 0}).json()["ok"]
    assert c.get("/api/state").json()["presence"] == "active"


# ---------------------------------------------------------------- 13. фоновые работы: tracked → события, «стоп»
def test_background_jobs_tracked_and_stoppable():
    from core.services import events, state

    @state.tracked("тест-работа")
    async def ok_job():
        return 1

    @state.tracked("падающая")
    async def bad_job():
        raise RuntimeError("boom")
    asyncio.run(ok_job())
    with pytest.raises(RuntimeError):
        asyncio.run(bad_job())
    kinds = [(e.kind, e.data.get("job")) for e in events.recent(20)]
    assert ("background_done", "тест-работа") in kinds and ("background_failed", "падающая") in kinds
    state.job_start("рендер")
    r = _say("стоп")
    assert "stop_job" in r.actions and state.running_job() is None


# ---------------------------------------------------------------- 14. инструменты: transient-ошибка записи повторяется, деньги — нет
def test_registry_retries_transient_write_not_money(monkeypatch):
    from core.tools import registry
    calls = {"n": 0}

    def flaky(**_):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("database is locked")
        return "ок"
    monkeypatch.setitem(registry.FUNCS, "list_tasks", flaky)
    monkeypatch.setattr(registry.time, "sleep", lambda *_: None)
    res = registry.call("list_tasks", {}, "web")
    assert res.ok and calls["n"] == 3
    calls["n"] = 0

    def money_flaky(**_):
        calls["n"] += 1
        raise RuntimeError("database is locked")
    monkeypatch.setitem(registry.FUNCS, "add_expense", money_flaky)
    res = registry.call("add_expense", {"amount": 100, "category": "еда"}, "web")
    assert not res.ok and calls["n"] == 1          # деньги не повторяем сами


# ---------------------------------------------------------------- 15. API целей
def test_aims_api_roundtrip():
    from fastapi.testclient import TestClient
    from core.api.app import app
    c = TestClient(app)
    a = c.post("/api/aims", json={"title": "Портфолио", "why": "дороже"}).json()
    assert a["title"] == "Портфолио" and a["progress"] == 0
    v = c.post(f"/api/aims/{a['id']}/milestones", json={"title": "3 сцены"}).json()
    mid = v["milestones"][0]["id"]
    t = c.post("/api/tasks", json={"title": "Сцена"}).json()
    assert c.put(f"/api/tasks/{t['id']}", json={"milestone_id": mid}).json()["aim_id"] == a["id"]
    assert c.get("/api/focus").json()["items"][0]["title"] == "Сцена"
    c.post(f"/api/tasks/{t['id']}/done")
    assert c.get(f"/api/aims/{a['id']}").json()["progress"] == 1.0
    assert c.put(f"/api/aims/{a['id']}", json={"status": "done"}).json()["status"] == "done"
    assert c.get("/api/aims").json() == [] and len(c.get("/api/aims?all=true").json()) == 1
    assert c.get("/api/timeline").status_code == 200 and c.get("/api/presence/events").status_code == 200


# ---------------------------------------------------------------- 19.09: аудит «чёрный экран» и грязный ввод
def _tc():
    from fastapi.testclient import TestClient
    from core.api.app import app
    return TestClient(app)


def test_bad_input_is_4xx_not_500():
    c = _tc()
    # повтор по дням недели вне 0..6 раньше ронял сериализацию события (IndexError → 500)
    r = c.post("/api/events", json={"title": "x", "start": "2026-09-19T10:00", "repeat": "weekly", "repeat_days": [9, 1]})
    assert r.status_code == 200 and r.json()["repeat_days"] == "1"
    assert c.post("/api/events", json={"title": "   ", "start": "2026-09-19T10:00"}).status_code == 422
    assert c.post("/api/tasks", json={"title": ""}).status_code == 422
    assert c.post("/api/notes", json={"text": " "}).status_code == 422
    assert c.get("/api/timeline?day=abc").status_code == 422
    # привязка задачи к несуществующей вехе/цели — 404, а не молчаливая запись
    t = c.post("/api/tasks", json={"title": "тест привязки"}).json()
    assert c.put(f"/api/tasks/{t['id']}", json={"milestone_id": 999999}).status_code == 404
    assert c.put(f"/api/tasks/{t['id']}", json={"aim_id": 999999}).status_code == 404
    # пустой PUT не пишет в ленту «(без изменений)»
    from core.db import session, Memory
    from sqlmodel import select
    def cnt():
        with session() as s:
            return len(s.exec(select(Memory).where(Memory.kind == "task")).all())
    before = cnt()
    assert c.put(f"/api/tasks/{t['id']}", json={}).status_code == 200
    after = cnt()
    assert after == before


def test_people_birthday_and_order_price_sanity():
    c = _tc()
    p = c.post("/api/people", json={"name": "Тест Тестов", "kind": "friend"}).json()
    assert c.put(f"/api/people/{p['id']}", json={"birthday": "99.99"}).json()["birthday"] is None
    assert c.put(f"/api/people/{p['id']}", json={"birthday": "1990-03-12"}).json()["birthday"] == "12.03.1990"
    assert c.put(f"/api/people/{p['id']}", json={"birthday": "5.7"}).json()["birthday"] == "05.07"
    o = c.post("/api/orders", json={"title": "Тестовый заказ", "price": 100}).json()
    assert c.put(f"/api/orders/{o['id']}", json={"price": -100}).status_code == 400


def test_impossible_time_does_not_crash_parser():
    from core.brain.dates import parse_datetime
    assert parse_datetime("встреча в 25:70")[0] is None
    assert parse_datetime("счёт 12:99 в пользу гостей")[0] is None
    assert parse_datetime("зубной в 09:30")[0] is not None


def test_title_has_no_space_before_comma_after_date_cut():
    from core.brain.dates import parse_datetime
    dt, rest = parse_datetime("встреча с Димой в среду в 15, кофейня на Патриках")
    assert dt is not None and rest == "встреча с Димой, кофейня на Патриках"
