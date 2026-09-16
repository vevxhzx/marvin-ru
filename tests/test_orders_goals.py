"""Заказы (фриланс), помодоро, цели/конверты и финансовые техники: сервисы, правила чата и API."""
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


def _client():
    from fastapi.testclient import TestClient
    from core.api.app import app
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 5555))


def _bal():
    from core.services import finance
    return sum(a.balance for a in finance.list_accounts())


def _j(r):
    assert r.status_code < 400, (r.status_code, r.text)
    return r.json()


# ---------------------------------------------------------------- сервисы
def test_order_lifecycle_and_payments():
    from core.services import finance, orders
    finance.set_balance("Т-Банк", 40000)
    o = orders.add_order("ролик", 25000, "Пятёрочка", datetime.now() + timedelta(days=4))
    assert o.title == "Ролик" and o.status == "work"
    v = orders.order_view(o)
    assert v["client"] == "Пятёрочка" and v["left"] == 25000 and v["days_left"] == 4 and not v["overdue"]
    # аванс — это доход в финансах, привязанный к заказу
    t = orders.add_payment(o.id, 10000)
    assert t.kind == "income" and t.order_id == o.id
    assert _bal() == 50000
    assert orders.order_view(orders.get_order(o.id))["left"] == 15000
    # ожидаемые доходы — остаток по заказу к дедлайну
    exp = orders.expected_income(30)
    assert len(exp) == 1 and exp[0]["amount"] == 15000
    # доплата закрывает заказ как оплаченный
    orders.add_payment(o.id, 15000)
    o2 = orders.get_order(o.id)
    assert o2.status == "paid" and o2.paid_at is not None
    assert orders.expected_income(30) == []
    assert orders.list_orders() == []                 # закрытые по умолчанию скрыты
    assert len(orders.list_orders(include_closed=True)) == 1
    # нельзя оплатить отрицательную сумму
    with pytest.raises(orders.OrderError):
        orders.add_payment(o.id, -5)


def test_find_order_by_word_form_and_pomodoro():
    from core.services import orders
    o = orders.add_order("Ролик для Пятёрочки", 25000)
    assert orders.find_order("ролика").id == o.id
    assert orders.find_order("#1").id == o.id
    assert orders.find_order("свадьба") is None
    w = orders.start_session(o.id, 25)
    st = orders.timer_state()
    assert st["active"] and st["order"] == "Ролик для Пятёрочки" and 24 * 60 <= st["left_sec"] <= 25 * 60
    # второй таймер закрывает первый — один таймер на всех
    orders.start_session(None, 10, "break")
    assert orders.timer_state()["kind"] == "break"
    assert orders.stop_session() is not None and not orders.timer_state()["active"]
    # истёкший таймер пингуется ровно один раз
    with db.session() as s:
        w = orders.start_session(o.id, 25)
        row = s.get(db.WorkSession, w.id)
        row.started_at = datetime.now() - timedelta(minutes=26); s.add(row); s.commit()
    ev = orders.due_timer_ping()
    assert ev and "Помодоро" in ev["text"] and ev["order_id"] == o.id
    assert orders.due_timer_ping() is None
    orders.stop_session()
    assert orders.hours_for(o.id) >= 0.4


def test_goals_envelopes_and_finance_techniques():
    from core.services import finance, goals
    finance.set_balance("Т-Банк", 100000)
    g = goals.add_goal("подушка", 300000, datetime.now().replace(day=1) + timedelta(days=200))
    v = goals.goal_view(g)
    assert v["per_month"] and v["left"] == 300000
    r = goals.put_to_goal(g.id, 10000)
    assert r["goal"]["saved"] == 10000 and not r["reached"]
    # отложенное — расход «Накопления», свободные деньги уменьшились
    assert _bal() == 90000
    txs = finance.list_transactions(days=1, limit=5)
    assert any(t.goal_id == g.id and t.kind == "expense" for t in txs)
    assert goals.find_goal("подушку").id == g.id
    # достигли — закрылась
    r = goals.put_to_goal(g.id, 290000)
    assert r["reached"] and r["goal"]["closed"]
    assert goals.list_goals() == [] and len(goals.list_goals(include_closed=True)) == 1
    # техники не падают на пустой базе и отдают ожидаемые ключи
    b = goals.buckets_report()
    assert [x["bucket"] for x in b["buckets"]] == ["need", "want", "save"]
    assert next(x for x in b["buckets"] if x["bucket"] == "save")["amount"] == 300000   # конверты = накопления
    assert goals.month_compare()["spent"] == 300000
    assert goals.annual_reserve()["per_month"] == 0
    pc = goals.payment_check(7)
    assert pc["short"] == 0 and pc["balance"] == -200000
    assert "runway_days" in goals.runway()
    assert isinstance(goals.goals_text(), str) and isinstance(goals.buckets_text(), str) and isinstance(goals.month_compare_text(), str)


def test_undo_goal_put_and_order_payment():
    from core.services import finance, goals, orders, undo
    finance.set_balance("Т-Банк", 100000)
    g = goals.add_goal("подушка", 50000)
    goals.put_to_goal(g.id, 50000)
    assert goals.find_goal("подушка") is None            # закрыта
    assert "трату" in undo.undo_last()                  # откат последнего — перевода в конверт
    g2 = goals.list_goals()[0]
    assert g2["saved"] == 0 and not g2["closed"]        # откат вернул конверт
    assert sum(a.balance for a in finance.list_accounts()) == 100000
    o = orders.add_order("ролик", 10000)
    orders.add_payment(o.id, 10000)
    assert orders.get_order(o.id).status == "paid"
    undo.undo_last()
    assert orders.get_order(o.id).status == "done" and orders.paid_for(o.id) == 0
    undo.undo_last()                                     # откат самого заказа
    assert orders.get_order(o.id) is None


def test_cash_forecast_includes_expected_income():
    from core.services import finance, insights, orders
    finance.set_balance("Т-Банк", 40000)
    orders.add_order("монтаж", 60000, "Иванов", datetime.now() + timedelta(days=10))
    f = insights.cash_forecast(30)
    assert f["expected_income"] == 60000
    assert "по заказам" in insights.cash_forecast_text()


# ---------------------------------------------------------------- правила чата (без модели)
def _say(t):
    from core.brain import agent
    return asyncio.run(agent.handle(t, "test"))


def test_chat_rules_orders_goals():
    from core.services import finance, goals, orders
    finance.set_balance("Т-Банк", 40000)
    r = _say("заказ: ролик для Пятёрочки, 25к, до пятницы")
    assert "add_order" in r.actions and "Пятёрочки" in r.text and "25 000" in r.text
    o = orders.list_orders()[0]
    assert o["title"] == "Ролик" and o["price"] == 25000 and o["deadline"] is not None
    r = _say("пришёл аванс 10000 за ролик")
    assert "order_payment" in r.actions and orders.list_orders()[0]["left"] == 15000
    assert "list_orders" in _say("заказы").actions
    assert "pomodoro" in _say("таймер на ролик").actions and orders.timer_state()["active"]
    assert "pomodoro" in _say("сколько я сегодня работал").actions
    assert "pomodoro" in _say("стоп").actions and not orders.timer_state()["active"]
    assert "не нашёл" in _say("таймер на свадьбу").text
    r = _say("цель: подушка 300к к марту")
    assert "add_goal" in r.actions and goals.list_goals()[0]["target"] == 300000 and goals.list_goals()[0]["due"].month == 3
    r = _say("отложил 10к в подушку")
    assert "save_to_goal" in r.actions and "10 000" in r.text
    assert "list_goals" in _say("цели").actions
    for q in ("50/30/20", "сравни с прошлым месяцем", "на сколько хватит", "хватит ли на платежи"):
        assert "finance_report" in _say(q).actions, q
    # обычные финансы не задеты
    assert "add_expense" in _say("потратил 700 на такси").actions
    assert "add_income" in _say("получил зарплату 50000").actions


# ---------------------------------------------------------------- API
def test_orders_goals_api():
    c = _client()
    o = _j(c.post("/api/orders", json={"title": "ролик", "price": 25000, "client": "Пятёрочка", "deadline": "2026-09-18T23:59:00"}))
    assert o["client"] == "Пятёрочка" and o["id"] == 1
    _j(c.post("/api/orders", json={"title": "свадьба", "price": 60000, "deadline": "2026-09-30T23:59:00"}))
    assert _j(c.post("/api/orders/1/payments", json={"amount": 10000}))["order"]["left"] == 15000
    assert c.post("/api/orders/99/payments", json={"amount": 1}).status_code == 404
    assert _j(c.post("/api/orders/timer", json={"order_id": 1, "minutes": 25}))["order"] == "Ролик"
    assert _j(c.get("/api/orders/timer"))["active"]
    assert not _j(c.delete("/api/orders/timer"))["active"]
    d = _j(c.get("/api/orders/1"))
    assert d["payments"][0]["amount"] == 10000 and isinstance(d["sessions"], list)
    assert _j(c.put("/api/orders/2", json={"status": "done"}))["status"] == "done"
    assert c.put("/api/orders/2", json={"status": "weird"}).status_code == 400
    assert [x["title"] for x in _j(c.get("/api/orders"))] == ["Ролик", "Свадьба"]
    assert _j(c.get("/api/orders/stats"))["unpaid"] == 75000
    assert _j(c.get("/api/orders/clients"))[0]["name"] == "Пятёрочка"
    # дедлайны заказов — в календаре как kind='order'
    kinds = {e["kind"] for e in _j(c.get("/api/events?tasks_too=true&start=2026-09-01T00:00:00&end=2026-10-01T00:00:00"))}
    assert "order" in kinds
    # цели
    g = _j(c.post("/api/finance/goals", json={"title": "подушка", "target": 300000, "due": "2027-03-01T00:00:00"}))
    assert g["per_month"]
    assert _j(c.post("/api/finance/goals/1/put", json={"amount": 10000}))["goal"]["saved"] == 10000
    assert c.post("/api/finance/goals/1/put", json={"amount": 0}).status_code == 400
    t = _j(c.get("/api/finance/techniques"))
    assert set(t) == {"buckets", "compare", "annual", "payments", "runway"}
    dash = _j(c.get("/api/dashboard"))
    assert "timer" in dash and dash["orders"]["unpaid"] == 75000 and "runway" in dash and len(dash["goals"]) == 1
    assert _j(c.delete("/api/orders/2"))["ok"] and c.delete("/api/orders/2").status_code == 404
    assert _j(c.delete("/api/finance/goals/1"))["ok"]


def test_ui_prefs_roundtrip_and_notes_put():
    """Синхронизация оформления через сервер + правка заметки через PUT (регресс: не импортированные get_setting/select)."""
    c = _client()
    assert _j(c.get("/api/ui-prefs"))["prefs"] == {}
    r = _j(c.put("/api/ui-prefs", json={"prefs": {"accent": "moss", "todayOrder": ["tasks", "orders"]}}))
    assert r["ok"] is True or "updated_at" in r
    got = _j(c.get("/api/ui-prefs"))
    assert got["prefs"]["accent"] == "moss" and got["prefs"]["todayOrder"] == ["tasks", "orders"]
    n = _j(c.post("/api/notes", json={"text": "мысль про заказ", "tags": []}))
    nid = n["id"] if "id" in n else n["note"]["id"]
    e = _j(c.put(f"/api/notes/{nid}", json={"text": "мысль про заказ — исправлено"}))
    assert "исправлено" in (e.get("text") or e.get("note", {}).get("text", ""))
    evs = _j(c.get("/api/events?tasks_too=true"))
    assert isinstance(evs, list)


def test_pomodoro_settings_auto_break_and_api(monkeypatch):
    """Настройки помодоро: хранятся в базе, применяются к старту без минут, длинный перерыв каждый N-й,
    авто-перерыв стартует сам после фокуса; API отдаёт и принимает их."""
    from core.services import orders
    if datetime.now().hour == 0 and datetime.now().minute < 30:
        # «26 минут назад» — это ещё вчера, и «сегодняшних» помидоров не будет; ждать нельзя — сдвигаем часы сервиса на час вперёд
        class _Now(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime.now(tz) + timedelta(hours=1)
        monkeypatch.setattr(orders, "datetime", _Now)
    orders.stop_session()
    d = orders.pomo_settings()
    assert d["focus"] == 25 and d["short"] == 5 and d["long"] == 15 and d["sound"] == "bell"
    # мусор и выход за границы не проходят, неизвестные ключи игнорируются
    r = orders.save_pomo_settings({"focus": 40, "short": 3, "long_every": 2, "sound": "ding", "volume": 5, "nonsense": 1})
    assert r["focus"] == 40 and r["short"] == 3 and r["long_every"] == 2 and r["sound"] == "ding" and 0 < r["volume"] <= 1 and "nonsense" not in r
    assert orders.pomo_settings()["focus"] == 40
    w = orders.start_session(None)                     # без минут → из настроек
    assert w.planned_min == 40 and orders.timer_state()["focus_min"] == 40
    orders.stop_session()
    # авто-перерыв: истёкший фокус закрывается сам, перерыв уже идёт
    orders.save_pomo_settings({"auto_break": True})
    with db.session() as s:
        w = orders.start_session(None, 25)
        row = s.get(db.WorkSession, w.id); row.started_at = orders.datetime.now() - timedelta(minutes=26); s.add(row); s.commit()
    ev = orders.due_timer_ping()
    assert ev and ev["auto_break"] and ev["session_kind"] == "focus" and ev["settings"]["sound"] == "ding"
    st = orders.timer_state()
    assert st["active"] and st["kind"] == "break" and st["planned_min"] == ev["break_min"]
    orders.stop_session()
    # таймер, остановленный через минуту, помидором не считается; отработанный — считается
    with db.session() as s:
        w = orders.start_session(None, 25)
        row = s.get(db.WorkSession, w.id); row.started_at = orders.datetime.now() - timedelta(minutes=1); s.add(row); s.commit()
    orders.stop_session()
    n = orders.today_sessions()
    with db.session() as s:
        w = orders.start_session(None, 25)
        row = s.get(db.WorkSession, w.id); row.started_at = orders.datetime.now() - timedelta(minutes=24); s.add(row); s.commit()
    orders.stop_session()
    assert orders.today_sessions() == n + 1
    # каждый 2-й помидор — длинный перерыв (сколько их уже набежало за сегодня от других тестов — неважно: добиваем до чётного)
    if orders.today_sessions() % 2:
        with db.session() as s:
            w = orders.start_session(None, 25)
            row = s.get(db.WorkSession, w.id); row.started_at = orders.datetime.now() - timedelta(minutes=24); s.add(row); s.commit()
        orders.stop_session()
    assert orders.today_sessions() % 2 == 0 and orders.next_break_minutes() == orders.pomo_settings()["long"]
    # API
    c = _client()
    assert _j(c.get("/api/orders/pomodoro"))["focus"] == 40
    r = _j(c.put("/api/orders/pomodoro", json={"focus": 25, "auto_break": False, "long_every": 4, "short": 5, "sound": "bell"}))
    assert r["focus"] == 25 and r["auto_break"] is False
    t = _j(c.post("/api/orders/timer", json={"kind": "break"}))   # без минут → из настроек
    assert t["active"] and t["kind"] == "break" and t["planned_min"] in (5, 15)
    _j(c.delete("/api/orders/timer"))


def test_payment_backdated_lands_in_its_month():
    """Старый заказ: оплата задним числом попадает в тот месяц, заказ закрывается той датой, а не сегодняшней."""
    from datetime import datetime, timedelta
    from core.services import orders
    o = orders.add_order("Старый ролик", 15000, "Кот прод", status="done")
    when = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0) - timedelta(days=40)
    orders.add_payment(o.id, 15000, date=when)
    o2 = orders.get_order(o.id)
    assert o2.status == "paid" and o2.paid_at.date() == when.date() and o2.done_at.date() <= when.date()
    st = orders.stats(3)
    by = {m["month"]: m["income"] for m in st["months"]}
    assert by.get(when.strftime("%Y-%m")) == 15000
    assert by.get(datetime.now().strftime("%Y-%m"), 0) == 0
    assert all(c["unpaid"] == 0 for c in st["clients"])
    # через API — дата уходит в теле
    c = _client()
    o3 = _j(c.post("/api/orders", json={"title": "Ещё старый", "price": 1000, "status": "done"}))
    r = _j(c.post(f"/api/orders/{o3['id']}/payments", json={"amount": 1000, "date": when.isoformat()}))
    assert r["order"]["status"] == "paid" and r["tx"]["date"][:10] == when.date().isoformat()


def test_chat_payment_with_past_date():
    from datetime import datetime
    from core.services import orders
    from core.brain.agent import _orders_rules
    o = orders.add_order("Логотип", 5000, "Ромашка", status="done")
    t = "пришло 5000 за логотип 3 сентября"; rep = _orders_rules(t, t.lower(), "web")
    assert rep and "в доходах за 03.09" in rep.text, rep and rep.text
    p = orders.payments_for(o.id)[0]
    assert p.date.month == 9 and p.date.day == 3 and p.date <= datetime.now()


def test_manually_paid_order_waits_for_nothing():
    """Старый заказ закрыли статусом «оплачен» без записи денег — он не должен «ждать оплаты» ни в заказах, ни у клиента."""
    from core.services import orders, people
    o = orders.add_order("Давний ролик", 13500, "Кот прод", status="done")
    orders.update_order(o.id, status="paid")
    v = orders.order_view(orders.get_order(o.id))
    assert v["left"] == 0 and v["paid"] == 0
    assert orders.stats(3)["unpaid"] == 0
    card = people.card(people.find_person("Кот прод"))
    assert card["money"]["unpaid"] == 0
    c = _client()
    assert _j(c.get("/api/dashboard"))["orders"]["unpaid"] == 0


def test_review_after_deadline_is_not_overdue_and_client_totals():
    """«На правках» после срока — не просрочка (первая версия сдана); в статистике по клиенту — сумма заказов и получено за всё время."""
    from core.services import orders
    o = orders.add_order("Ролик Headway", 1500, "Кот Прод", datetime.now() - timedelta(days=1))
    v = orders.order_view(orders.get_order(o.id))
    assert v["overdue"] and not v["past_due"]
    orders.update_order(o.id, status="review")
    v = orders.order_view(orders.get_order(o.id))
    assert not v["overdue"] and v["past_due"]
    assert not any("Headway" in x for x in orders.deadline_nudges())
    assert "срок был" in orders.summary_text()
    st = orders.stats(1)
    c = next(x for x in st["clients"] if x["client"] == "Кот Прод")
    assert c["total"] >= 1500 and c["unpaid"] >= 1500 and "_paid_period" not in c
