"""Финансовый пульс (режим фрилансера): настройки, задержки оплат, ставка факт/план, налог, дайджест/неделя, API."""
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


def _j(r):
    assert r.status_code < 400, (r.status_code, r.text)
    return r.json()


def _on(**kw):
    from core.services import pulse
    return pulse.save_freelance_settings({"enabled": True, **kw})


def _done_order(title, price, client, days_ago, paid=0.0):
    """Сданный заказ days_ago дней назад (done_at в прошлом), с частичной оплатой."""
    from core.services import orders
    from sqlmodel import select
    o = orders.add_order(title, price=price, client=client)
    orders.update_order(o.id, status="done")
    with db.session() as s:
        row = s.get(db.Order, o.id)
        row.done_at = datetime.now() - timedelta(days=days_ago)
        s.add(row); s.commit()
    if paid:
        orders.add_payment(o.id, paid)
    return o


def _paid_order(client, done_days_ago, paid_after_days):
    from core.services import orders
    o = orders.add_order("старый", price=1000, client=client)
    orders.update_order(o.id, status="paid")
    with db.session() as s:
        row = s.get(db.Order, o.id)
        row.done_at = datetime.now() - timedelta(days=done_days_ago)
        row.paid_at = row.done_at + timedelta(days=paid_after_days)
        s.add(row); s.commit()
    return o


# ---------------------------------------------------------------- настройки

def test_settings_defaults_bounds_and_auto_enable():
    from core.services import pulse, orders
    st = pulse.freelance_settings()
    assert st["enabled"] is False and st["late_days"] == 3 and st["tax_percent"] == 0
    # первый запуск: заказов нет → режим остаётся выключенным; с заказами → включается сам
    assert pulse.auto_enable_if_used() is False
    from sqlmodel import delete
    with db.session() as s:
        s.exec(delete(db.Setting).where(db.Setting.key == "freelance")); s.commit()
    orders.add_order("Ролик", price=1000)
    assert pulse.auto_enable_if_used() is True
    st = pulse.save_freelance_settings({"late_days": 999, "rate_tolerance": 1, "tax_percent": "6", "weekly": "false", "junk": 1})
    assert st["late_days"] == 60 and st["rate_tolerance"] == 5 and st["tax_percent"] == 6 and st["weekly"] is False and "junk" not in st


# ---------------------------------------------------------------- задержки

def test_late_payments_threshold_and_habits():
    from core.services import pulse
    _on(late_days=3)
    _done_order("Ролик", 25000, "Пятёрочка", days_ago=5, paid=10000)     # задержка 5 дн., осталось 15к
    _done_order("Свежий", 10000, "Пятёрочка", days_ago=1)                 # ещё в пределах порога
    _done_order("Оплачен", 8000, "Иван", days_ago=10, paid=8000)          # закрыт деньгами — не задержка
    _paid_order("Пятёрочка", done_days_ago=40, paid_after_days=4)
    _paid_order("Пятёрочка", done_days_ago=60, paid_after_days=2)
    late = pulse.late_payments()
    assert [x["title"] for x in late] == ["Ролик"]
    x = late[0]
    assert x["left"] == 15000 and x["days"] == 5 and x["client"] == "Пятёрочка"
    assert x["typical_days"] == 2 or x["typical_days"] == 4   # медиана из двух — любая из них, главное посчитана
    assert x["beyond_habit"] is True
    lines = pulse.late_lines()
    assert len(lines) == 1 and "Пятёрочка" in lines[0] and "15 000" in lines[0] and "обычно платит" in lines[0]
    txt = pulse.late_text()
    assert "Задерживают" in txt and "Ролик" in txt
    # выключили подсказки — строк нет, но список для чата остаётся
    pulse.save_freelance_settings({"late_nudge": False})
    assert pulse.late_lines() == [] and pulse.late_payments()


def test_late_lines_silent_when_mode_off():
    from core.services import pulse
    _done_order("Ролик", 25000, "Пятёрочка", days_ago=9)
    assert pulse.late_lines() == []
    assert pulse.weekly_block() == []
    assert pulse.rate_check({"hours": 5, "estimate_h": 2, "price": 1000}) is None
    assert pulse.tax_rate() == 0.0


def test_expected_income_uses_client_habit():
    from core.services import pulse, orders
    _on(late_days=3)
    _paid_order("Пятёрочка", done_days_ago=40, paid_after_days=10)
    o = _done_order("Ролик", 25000, "Пятёрочка", days_ago=1)
    exp = [e for e in orders.expected_income(60) if e["order_id"] == o.id]
    assert exp and (exp[0]["date"].date() - datetime.now().date()).days == 9   # сдан вчера + обычно 10 дней


# ---------------------------------------------------------------- ставка

def test_rate_check_and_line():
    from core.services import pulse
    _on(rate_tolerance=30)
    assert pulse.rate_check({"hours": 0.1, "estimate_h": 2, "price": 1000}) is None       # таймер почти не гоняли
    r = pulse.rate_check({"hours": 12, "estimate_h": 8, "price": 24000})
    assert r["rate"] == 2000 and r["planned_rate"] == 3000 and r["over_pct"] == 50 and r["warn"] is True
    r2 = pulse.rate_check({"hours": 9, "estimate_h": 8, "price": 24000})
    assert r2["warn"] is False and r2["over_pct"] == 12
    r3 = pulse.rate_check({"hours": 4, "estimate_h": 0, "price": 8000})
    assert r3["planned_rate"] is None and r3["over_pct"] is None and r3["rate"] == 2000
    assert "вместо" in pulse.rate_line({"hours": 12, "estimate_h": 8, "price": 24000})
    assert "вместо" not in pulse.rate_line({"hours": 9, "estimate_h": 8, "price": 24000})


def test_order_view_carries_pulse():
    from core.services import orders, pulse
    _on()
    o = orders.add_order("Ролик", price=24000, estimate_h=8)
    d = next(x for x in orders.list_orders() if x["id"] == o.id)
    assert d["pulse"] is None   # часов нет — нечего сравнивать
    pulse.save_freelance_settings({"enabled": False})
    d = next(x for x in orders.list_orders() if x["id"] == o.id)
    assert d["pulse"] is None


# ---------------------------------------------------------------- налог

def test_tax_month_and_forecast():
    from core.services import pulse, orders, insights
    _on(tax_percent=6)
    o = orders.add_order("Ролик", price=50000, client="Пятёрочка")
    orders.update_order(o.id, status="work")
    orders.add_payment(o.id, 20000)
    tm = pulse.tax_month()
    assert tm["percent"] == 6 and tm["received"] == 20000 and tm["tax_received"] == 1200
    assert tm["expected"] == 30000 and tm["tax_expected"] == 1800 and tm["tax_total"] == 3000
    f = insights.cash_forecast(30)
    assert f["expected_income"] == 28200 and f["expected_tax"] == 1800
    assert "за вычетом налога" in insights.cash_forecast_text()
    txt = orders.summary_text()
    assert "Налог 6 %" in txt and "1 200" in txt
    pulse.save_freelance_settings({"tax_percent": 0})
    assert insights.cash_forecast(30)["expected_income"] == 30000
    assert "Налог" not in orders.summary_text()


# ---------------------------------------------------------------- дайджест / неделя / чат

def test_digest_and_weekly_block():
    from core.services import pulse, scheduler, orders
    _on(late_days=3, tax_percent=4)
    _done_order("Ролик", 25000, "Пятёрочка", days_ago=6)
    o = orders.add_order("Монтаж", price=10000)
    orders.add_payment(o.id, 10000)
    digest = scheduler.morning_digest_text()
    assert "задерживает" in digest and "Пятёрочка" in digest
    wk = pulse.weekly_block()
    assert wk and wk[0].startswith("💼") and "10 000" in wk[0] and "налог ~400" in wk[0]
    assert any("задерживает" in x for x in wk)
    pulse.save_freelance_settings({"weekly": False})
    assert pulse.weekly_block() == []


def test_chat_rule_late():
    from core.brain.agent import LATE_Q_RX, _orders_rules
    _on()
    for q in ["кто задерживает", "кто тянет с оплатой?", "задержки по оплатам", "кто должен давно"]:
        assert LATE_Q_RX.match(q), q
    assert not LATE_Q_RX.match("кто мне должен")   # это обычная сводка по заказам
    r = _orders_rules("кто задерживает", "кто задерживает", "web")
    assert r and "late_payments" in r.actions and "Никто не задерживает" in r.text


# ---------------------------------------------------------------- API

def test_api_freelance_and_pulse():
    c = _client()
    st = _j(c.get("/api/orders/freelance"))
    assert st["enabled"] is False
    st = _j(c.put("/api/orders/freelance", json={"enabled": True, "tax_percent": 6, "late_days": 2}))
    assert st["enabled"] and st["tax_percent"] == 6 and st["late_days"] == 2
    _done_order("Ролик", 25000, "Пятёрочка", days_ago=4)
    p = _j(c.get("/api/orders/pulse"))
    assert p["enabled"] and p["late"][0]["client"] == "Пятёрочка" and p["tax"]["percent"] == 6
    d = _j(c.get("/api/dashboard"))
    assert d["freelance"] is True and d["orders"]["late"][0]["left"] == 25000
    _j(c.put("/api/orders/freelance", json={"enabled": False}))
    p = _j(c.get("/api/orders/pulse"))
    assert p == {"enabled": False, "late": [], "tax": None}
    d = _j(c.get("/api/dashboard"))
    assert d["freelance"] is False and d["orders"]["late"] == []


# ---------------------------------------------------------------- клиент платит пачкой / по числам

def _set_pay(name, **fields):
    from core.services import people
    from sqlmodel import select
    with db.session() as s:
        c = s.exec(select(db.Client).where(db.Client.name == name)).first()
    return people.update_person(c.id, **fields)


def test_next_payday_monthly_and_batch():
    from core.services import pulse
    c = db.Client(name="кот", pay_mode="monthly", pay_days="10, 25", created_at=datetime(2026, 1, 1))
    assert pulse.next_payday(c, datetime(2026, 9, 16)).date() == datetime(2026, 9, 25).date()
    assert pulse.next_payday(c, datetime(2026, 9, 26)).date() == datetime(2026, 10, 10).date()
    c31 = db.Client(name="кот", pay_mode="monthly", pay_days="31", created_at=datetime(2026, 1, 1))
    assert pulse.next_payday(c31, datetime(2026, 9, 1)).date() == datetime(2026, 9, 30).date()  # в сентябре 30 дней
    each = db.Client(name="лена", pay_mode="each")
    assert pulse.next_payday(each) is None
    # пачкой: раз в 14 дней от даты создания (оплат ещё не было) → не раньше сегодня
    with db.session() as s:
        b = db.Client(name="студия", kind="client", pay_mode="batch", pay_every=14, created_at=datetime.now() - timedelta(days=20))
        s.add(b); s.commit(); s.refresh(b)
    d = pulse.next_payday(b)
    assert d.date() == (datetime.now() - timedelta(days=20) + timedelta(days=28)).date()


def test_expected_income_groups_batch_client_into_one_point():
    from core.services import orders
    _on()
    _done_order("логотип", 5000, "кот прод", days_ago=3)
    _done_order("баннер", 3000, "кот прод", days_ago=1)
    _done_order("сайт", 7000, "лена", days_ago=2)
    items_each = orders.expected_income()
    assert len(items_each) == 3
    _set_pay("кот прод", pay_mode="monthly", pay_days="10,25")
    items = orders.expected_income()
    titles = [i["title"] for i in items]
    assert any(t.startswith("кот прод, 2 заказа") for t in titles), titles
    grp = next(i for i in items if i["title"].startswith("кот прод"))
    assert grp["amount"] == 8000
    assert grp["date"].day in (10, 25)
    assert any(i["client"] == "лена" and i["amount"] == 7000 for i in items)


def test_late_payments_batch_counts_from_payday_not_done():
    from core.services import pulse
    _on(late_days=3)
    _done_order("логотип", 5000, "кот прод", days_ago=10)
    assert pulse.late_payments(), "за каждый заказ: 10 дней после сдачи — задержка"
    # клиент платит раз в 60 дней, создан вчера → день выплат ещё не наступил → не задерживает
    c = _set_pay("кот прод", pay_mode="batch", pay_every=60)
    with db.session() as s:
        row = s.get(db.Client, c.id); row.created_at = datetime.now() - timedelta(days=1); s.add(row); s.commit()
    assert pulse.late_payments() == []
    # по числам: платит 1-го; заказ сдан 10 дней назад — если после сдачи день выплат ещё не был, задержки нет
    c = _set_pay("кот прод", pay_mode="monthly", pay_days="1")
    prev = pulse._prev_payday(c, datetime.now())
    late = pulse.late_payments()
    days_since_payday = (datetime.now() - prev).days
    if prev < datetime.now() - timedelta(days=10) or days_since_payday < 3:
        assert late == []
    else:
        assert late and late[0]["days"] == days_since_payday
    # заказ сдан 40 дней назад → день выплат точно прошёл → задержка считается от него, а не от сдачи
    _done_order("старый баннер", 2000, "кот прод", days_ago=40)
    late = pulse.late_payments()
    if days_since_payday >= 3:
        assert late and max(l["days"] for l in late) == days_since_payday
    else:
        assert late == []


def test_update_person_pay_fields_are_sanitised():
    from core.services import people
    c = people.add_person("кот прод", kind="client")
    c = people.update_person(c.id, pay_mode="weird", pay_every=9999, pay_days="0, 5, 40, 25, 25")
    assert c.pay_mode == "each" and c.pay_every == 120 and c.pay_days == "5,25"
    card = people.card(c)
    assert card["pay_mode"] == "each" and card["next_payday"] is None
    c = people.update_person(c.id, pay_mode="monthly")
    assert people.card(c)["next_payday"]
    from core.services import orders
    orders.add_order("лого", price=1000, client="кот прод")
    txt = people.card_text(people.card(c))
    assert "платит 5 и 25 числа" in txt and "ближайшая выплата" in txt and " в " not in txt.split("ближайшая выплата")[1].split("\n")[0]


def test_guess_batch_clients_and_api():
    from core.services import pulse, orders
    _on()
    for t in ("а", "б"):
        o = orders.add_order(t, price=1000, client="кот прод"); orders.update_order(o.id, status="done")
        orders.add_payment(o.id, 1000)
    o = orders.add_order("в", price=1000, client="лена"); orders.update_order(o.id, status="done"); orders.add_payment(o.id, 1000)
    hints = pulse.guess_batch_clients()
    assert [h["name"] for h in hints] == ["кот прод"]
    r = _j(_client().get("/api/people/batch-hints"))
    assert r and r[0]["name"] == "кот прод"
    _set_pay("кот прод", pay_mode="batch")
    assert pulse.guess_batch_clients() == []


def test_none_string_is_not_a_note():
    from core.tools.registry import _coerce
    from core.brain.sorter import _s
    assert _s("None") is None and _s("null") is None and _s("норм") == "норм"
    for v in ("None", "null", " NULL "):
        assert _coerce("add_order", "notes", {"type": "string"}, v) is None
    assert _coerce("add_order", "notes", {"type": "string"}, "срочно") == "срочно"
