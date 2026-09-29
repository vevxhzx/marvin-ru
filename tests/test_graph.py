"""Граф связей: реальное с реальным — заказы/деньги/долги/задачи, а не только заметки и теги (0.9.19)."""
import os
import pytest

os.environ["ASSISTANT_TEST"] = "1"


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from core import db
    from sqlmodel import create_engine
    from sqlalchemy import event
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


def _rels(g):
    return {(e["source"], e["target"], e["rel"]) for e in g["edges"]}


def _linked(g, a, b, rel=None):
    return any({x, y} == {a, b} and (rel is None or r == rel) for x, y, r in _rels(g))


def test_keywords_skip_generic_words():
    from core.services.graph import keywords, mentions_title
    assert keywords("Сбер кредит") == ["сбер"]
    assert keywords("Кредитная карта") == []                 # нечего искать — общие слова
    assert keywords("Headway v1") == ["headway"]
    assert mentions_title("надо доделать хедвей", ["headway"]) is False
    assert mentions_title("Headway: правки по второй сцене", ["headway"]) is True
    assert mentions_title("закрыть сбер досрочно", ["сбер"]) is True
    assert mentions_title("любой текст", []) is False


def test_work_cluster_orders_clients_tag_and_project():
    from core.services import graph, orders, people, tasks
    people.add_person("Кот Прод", kind="client")
    people.add_person("Мама", kind="family")
    o = orders.add_order("Headway v1", price=20000, client="Кот Прод")
    t1 = tasks.add_task("Отрендерить финал", project="Headway v1")
    t2 = tasks.add_task("Купить лампу", project="Дом")
    tasks.add_task("Повесить полку", project="Дом")
    tasks.add_task("Одинокая задача", project="Гараж")     # проект с одной задачей — не узел, задача не висит сиротой
    tasks.add_task("Просто дело без проекта")
    g = graph.build()
    ids = {n["id"] for n in g["nodes"]}
    cli = next(n for n in g["nodes"] if n["kind"] == "person" and n["label"] == "Кот Прод")
    mom = next(n for n in g["nodes"] if n["kind"] == "person" and n["label"] == "Мама")
    assert _linked(g, f"order:{o.id}", "tag:работа", "work")
    assert _linked(g, cli["id"], "tag:работа", "work")
    assert not _linked(g, mom["id"], "tag:работа")             # семья к #работа не липнет
    assert _linked(g, f"task:{t1.id}", f"order:{o.id}", "project")   # проект = заказ → прямо к заказу
    assert _linked(g, f"task:{t2.id}", "project:дом", "project")
    assert next(n for n in g["nodes"] if n["id"] == "project:дом")["deg"] == 2
    assert "project:гараж" not in ids
    assert not any(n["kind"] == "task" and n["label"] in ("Просто дело без проекта", "Одинокая задача") for n in g["nodes"])


def test_notes_mention_orders_and_debts_by_keywords():
    from core.services import graph, orders, finance, brain_notes as notes
    o = orders.add_order("Headway v1", price=20000)
    d = finance.add_debt("Сбер кредит", 100000, payment=5000)
    d2 = finance.add_debt("Альфа кредитка", 50000, payment=3000)
    n1 = notes.add_note("Идея для Headway: сделать интро на 3 секунды")
    n2 = notes.add_note("сбер кредит по наследству — узнать про рефинансирование")
    n3 = notes.add_note("вкусная еда сегодня")
    g = graph.build()
    assert _linked(g, f"note:{n1.id}", f"order:{o.id}", "mention")
    assert _linked(g, f"note:{n2.id}", f"debt:{d.id}", "mention")
    assert not _linked(g, f"note:{n2.id}", f"debt:{d2.id}")      # «кредит» — общее слово, альфу не цепляем
    assert not _linked(g, f"debt:{d.id}", f"debt:{d2.id}")       # долги друг с другом по «кредит» не слипаются
    assert not any(f"note:{n3.id}" in (a, b) for a, b, _ in _rels(g))


def test_money_categories_link_payments_tags_and_people():
    from core.services import graph, orders, finance, people, goals, brain_notes as notes
    people.add_person("Кот Прод", kind="client")
    o = orders.add_order("Headway v1", price=20000, client="Кот Прод")
    d = finance.add_debt("Сбер кредит", 100000, payment=5000)
    finance.add_category("Дом", "expense")
    finance.add_transaction(1500, "expense", category="Дом", note="лампочки")
    notes.add_note("Ремонт полки #дом")
    orders.add_payment(o.id, 10000)
    finance.pay_debt(d.id, 5000)
    gl = goals.add_goal("Подушка", 300000)
    goals.put_to_goal(gl.id, 2000)
    g = graph.build()
    kinds = {n["id"]: n for n in g["nodes"]}
    money = [n for n in g["nodes"] if n["kind"] == "money"]
    assert money, "категории с оборотом должны стать узлами"
    assert any(_linked(g, m["id"], f"order:{o.id}", "pay") for m in money)   # оплата заказа → категория дохода ↔ заказ
    assert any(_linked(g, m["id"], f"debt:{d.id}", "pay") for m in money)    # платёж по долгу ↔ долг
    assert _linked(g, "money:дом", "tag:дом", "same")                         # категория «Дом» ↔ #дом
    assert any(_linked(g, m["id"], f"goal:{gl.id}", "pay") for m in money)   # перевод в конверт ↔ цель
    assert all(n["deg"] >= 1 for n in money)                                   # одинокие категории не показываем
    assert g["stats"]["edges"] == len(g["edges"])
    # одна линия на пару, без дублей
    pairs = [tuple(sorted((e["source"], e["target"]))) for e in g["edges"]]
    assert len(pairs) == len(set(pairs))


def test_focus_on_work_tag_shows_cluster():
    from core.services import graph, orders, people, brain_notes as notes
    people.add_person("Кот Прод", kind="client")
    o = orders.add_order("Headway v1", price=20000, client="Кот Прод")
    n = notes.add_note("Headway — референсы по цвету")
    far = notes.add_note("купить хлеб #быт")
    notes.add_note("второй про быт #быт")
    g = graph.build(focus="tag:работа")
    ids = {x["id"] for x in g["nodes"]}
    assert f"order:{o.id}" in ids and f"note:{n.id}" in ids and f"note:{far.id}" not in ids
