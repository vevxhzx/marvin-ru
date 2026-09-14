"""Люди и клиенты: упоминания по имени/падежам, карточка, правила чата, граф связей, API."""
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


def _person(name, **kw):
    from core.services import people
    return people.add_person(name, **kw)


# ---------------------------------------------------------------- упоминания

def test_mentions_name_cases_and_aliases():
    from core.services.people import mentions
    ivan = _person("Иван Петров", kind="client", aliases="Ваня")
    assert mentions("созвон с Иваном", ivan)
    assert mentions("отправить Ване правки", ivan)
    assert mentions("Петрову надо счёт", ivan)
    assert mentions("иван петров просил", ivan)
    # чужие слова с похожим началом — не он
    assert not mentions("Иванов звонил", ivan)
    assert not mentions("едем в Ивановку", ivan)
    assert not mentions("ванну починить", ivan)


def test_mentions_short_names_need_exact_form():
    from core.services.people import mentions
    lena = _person("Лена")
    mama = _person("Мама")
    assert mentions("Лена советовала книгу", lena)
    assert mentions("позвонила Лене", lena)
    assert not mentions("ленивый день", lena)
    assert mentions("маме нужно лекарство", mama)
    assert not mentions("мамин пирог", mama)
    assert not mentions("", mama) and not mentions(None, mama)


def test_find_person_by_alias_and_partial():
    from core.services import people
    ivan = _person("Иван Петров", aliases="Ваня, @ivan")
    _person("Пятёрочка", kind="client")
    assert people.find_person("ване").id == ivan.id
    assert people.find_person("@ivan").id == ivan.id
    assert people.find_person("Петров").id == ivan.id
    assert people.find_person("пятёрочке").name == "Пятёрочка"
    assert people.find_person("Гриша") is None


# ---------------------------------------------------------------- карточка

def test_card_collects_orders_money_and_links():
    from core.services import people, orders, calendar, tasks, brain_notes as notes
    ivan = _person("Иван Петров", kind="client", aliases="Ваня")
    o = orders.add_order("Монтаж свадьбы", price=40000, client="Иван Петров", deadline=datetime.now() + timedelta(days=3))
    orders.add_payment(o.id, 15000)
    calendar.add_event("Созвон с Ваней", datetime.now() + timedelta(days=1, hours=2))
    tasks.add_task("Отправить Ване правки")
    notes.add_note("Ваня просил ролик потемнее #монтаж")
    d = people.card(ivan)
    assert d["money"]["paid"] == 15000 and d["money"]["unpaid"] == 25000 and d["money"]["open"] == 1
    assert d["orders"][0]["left"] == 25000 and d["orders"][0]["unpaid"]
    assert [e["title"] for e in d["upcoming"]] == ["Созвон с Ваней"]
    assert d["tasks"][0]["title"] == "Отправить Ване правки"
    assert d["notes"][0]["text"].startswith("Ваня просил")
    assert d["about"] is None and d["last_contact"] is not None
    txt = people.card_text(d)
    assert "ждёт оплаты 25 000" in txt and "Созвон с Ваней" in txt


def test_card_about_not_shadowed_by_notes_list():
    from core.services import people
    lena = _person("Лена", notes="сестра, живёт в Питере")
    d = people.card(lena)
    assert d["about"] == "сестра, живёт в Питере"
    assert isinstance(d["notes"], list)
    assert "сестра" in people.card_text(d)


def test_trigger_line_skips_fresh_and_hint_cooldown(monkeypatch):
    from core.services import people, orders
    ivan = _person("Иван Петров", kind="client", aliases="Ваня")
    orders.add_order("Ролик", price=10000, client="Иван Петров")
    # только что созданный заказ не повторяем — сказать нечего
    assert people.trigger_line(ivan) is None
    line = people.trigger_line(ivan, fresh_sec=0)
    assert line and "10 000" in line
    # hint_once: первый раз говорит, второй раз в течение cooldown — молчит
    monkeypatch.setattr(people, "trigger_line", lambda c, fresh_sec=90: "👤 Иван Петров: тест.")
    assert people.hint_once(ivan, cooldown_h=3)
    assert people.hint_once(ivan, cooldown_h=3) is None
    assert people.hint_once(ivan, cooldown_h=0)


def test_people_today_lists_only_people_in_todays_calendar():
    from core.services import people, calendar
    lena = _person("Лена")
    _person("Мама")
    calendar.add_event("Встреча с Леной", datetime.now().replace(hour=23, minute=0, second=0, microsecond=0))
    calendar.add_event("Мама приезжает", datetime.now() + timedelta(days=2))
    today = people.people_today()
    assert [p["id"] for p in today] == [lena.id]
    assert today[0]["event"] == "Встреча с Леной"


# ---------------------------------------------------------------- правила чата

def test_person_regexes():
    from core.brain.agent import PERSON_Q_RX, PERSON_ADD_RX
    for q in ["что по Ване", "что по Ване?", "кто такой Иванов", "кто такая Лена", "карточка клиента Пятёрочка", "досье на Петрова", "что с Пятёрочкой"]:
        assert PERSON_Q_RX.match(q), q
    for bad in ["что по деньгам", "что по плану на завтра", "кто такой умный", "что по ролику"]:
        m = PERSON_Q_RX.match(bad)
        # регэксп сам по себе может совпасть на «Плану» — важнее, что find_person не найдёт; но строчные не должны
        assert not m or m.group(1)[0].isupper(), bad
    assert PERSON_ADD_RX.match("человек: Лена, сестра").group(1) == "Лена, сестра"
    assert PERSON_ADD_RX.match("клиент — Пятёрочка, магазин").group(1) == "Пятёрочка, магазин"
    assert not PERSON_ADD_RX.match("человеку нужно позвонить")


def test_people_rules_add_and_card():
    from core.brain.agent import _people_rules
    from core.services import people
    r = _people_rules("человек: Лена, сестра, др 12.03", "web")
    assert r and "add_person" in r.actions
    lena = people.find_person("Лена")
    assert lena is not None and lena.kind == "person"
    r2 = _people_rules("кто такая Лена", "web")
    assert r2 and "person_card" in r2.actions and "Лена" in r2.text
    assert _people_rules("кто такой Гриша", "web") is None or "не знаю" in (_people_rules("кто такой Гриша", "web").text.lower())


# ---------------------------------------------------------------- граф

def test_graph_edges_client_mention_tag_wiki():
    from core.services import graph, orders, brain_notes as notes
    ivan = _person("Иван Петров", kind="client", aliases="Ваня")
    o = orders.add_order("Монтаж", price=1000, client="Иван Петров")
    n1 = notes.add_note("Идея для рилса про кофе #монтаж")
    n2 = notes.add_note("Продолжение: см. [[идея для рилса про кофе]] — Ваня одобрил #монтаж")
    g = graph.build()
    rels = {(e["source"], e["target"], e["rel"]) for e in g["edges"]}
    assert (f"order:{o.id}", f"person:{ivan.id}", "client") in rels or (f"person:{ivan.id}", f"order:{o.id}", "client") in rels
    assert any(r == "mention" and f"note:{n2.id}" in (a, b) and f"person:{ivan.id}" in (a, b) for a, b, r in rels)
    assert any(r == "wiki" and {a, b} == {f"note:{n1.id}", f"note:{n2.id}"} for a, b, r in rels)
    assert any(r == "tag" and a.startswith("tag:") or b.startswith("tag:") for a, b, r in rels)
    assert g["stats"]["people"] == 1 and g["stats"]["edges"] == len(g["edges"])
    # фокус оставляет только окрестность (2 шага): person → note2 → note1, а чужая мысль отпадает
    n3 = notes.add_note("совсем про другое: купить хлеб")
    f = graph.build(focus=f"person:{ivan.id}")
    ids = {n["id"] for n in f["nodes"]}
    assert {f"person:{ivan.id}", f"order:{o.id}", f"note:{n2.id}"} <= ids and f"note:{n3.id}" not in ids
    back = graph.backlinks("person", ivan.id)
    assert any(b["id"] == f"order:{o.id}" for b in back)


def test_graph_drops_lonely_tags():
    from core.services import graph, brain_notes as notes
    notes.add_note("одна мысль с редким #тегом")
    g = graph.build()
    assert not any(n["kind"] == "tag" for n in g["nodes"])


# ---------------------------------------------------------------- API

def test_people_api_roundtrip():
    c = _client()
    p = _j(c.post("/api/people", json={"name": "Лена", "kind": "person", "aliases": "Ленка"}))
    assert p["name"] == "Лена" and p["aliases"] == "Ленка"
    lst = _j(c.get("/api/people"))
    assert [x["name"] for x in lst] == ["Лена"]
    upd = _j(c.put(f"/api/people/{p['id']}", json={"notes": "сестра", "tags": "семья", "birthday": "12.03"}))
    assert upd["about"] == "сестра" and upd["tags"] == ["семья"] and upd["birthday"] == "12.03"
    assert c.post("/api/people", json={"name": "  "}).status_code == 400
    assert c.get("/api/people/999").status_code == 404
    g = _j(c.get("/api/graph"))
    assert {"nodes", "edges", "stats"} <= set(g)
    assert c.get("/api/graph/backlinks/bogus/1").status_code == 400
    assert isinstance(_j(c.get("/api/people/today")), list)
