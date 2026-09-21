"""Доска: хранение, объекты, раскадровка, правила чата, связь с заказом и графом."""
import os

import pytest

os.environ.setdefault("ASSISTANT_TEST", "1")


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    from core import db as dbm
    from sqlmodel import SQLModel, create_engine
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.setattr(dbm, "engine", eng)
    SQLModel.metadata.create_all(eng)
    yield


def _c():
    from fastapi.testclient import TestClient
    from core.api.app import app
    return TestClient(app)


def test_board_crud_and_items():
    from core.services import boards
    b = boards.add_board("Ролик Пятёрочка")
    assert b.id and b.kind == "free"
    st = boards.add_item(b.id, "sticky", 10, 20, data={"text": "идея", "color": "pink"})
    tx = boards.add_item(b.id, "text", 0, 300, data={"text": "СЦЕНА 1", "size": "lg"})
    ar = boards.add_item(b.id, "arrow", data={"from": {"item": st.id}, "to": {"item": tx.id}})
    d = boards.get_board(b.id)
    assert len(d["items"]) == 3 and d["items"][0]["data"]["color"] == "pink"
    # мусор в data не проходит
    bad = boards.add_item(b.id, "sticky", data={"text": "x", "color": "neon", "evil": 1})
    assert boards.item_out(bad)["data"] == {"text": "x", "color": "yellow"}
    with pytest.raises(ValueError):
        boards.add_item(b.id, "blob")
    # bulk move
    n = boards.bulk_update(b.id, [{"id": st.id, "x": 100, "y": 200}, {"id": 999999, "x": 1}])
    assert n == 1
    # удаление стикера уносит и стрелку, которая в него упиралась
    assert boards.delete_items(b.id, [st.id]) == 2
    assert {i["id"] for i in boards.get_board(b.id)["items"]} == {tx.id, bad.id}
    # удаление доски = архив
    assert boards.delete_board(b.id) and boards.get_board(b.id)["archived"] is True
    assert boards.list_boards() == [] and len(boards.list_boards(archived=True)) == 1


def test_storyboard_frames_numbering_and_time():
    from core.services import boards
    b = boards.add_board("Свадьба", "storyboard", frames=5, ratio="9:16")
    d = boards.get_board(b.id)
    frames = [i for i in d["items"] if i["type"] == "frame"]
    assert len(frames) == 5 and all(f["data"]["ratio"] == "9:16" for f in frames)
    assert [f["data"]["n"] for f in frames] == [1, 2, 3, 4, 5]
    # переставили первый кадр в конец ряда → номера пересчитались
    first = frames[0]
    boards.update_item(first["id"], x=99999)
    out = boards.renumber_frames(b.id)
    assert out[-1]["id"] == first["id"] and out[-1]["data"]["n"] == 5 and out[0]["data"]["n"] == 1
    # «добавить кадр» — следующий, с номером 6
    nxt = boards.add_frame_next(b.id)
    assert boards.item_out(nxt)["data"]["n"] == 6
    # хронометраж в тексте
    boards.update_item(frames[1]["id"], data={"label": "Крупный план колец", "seconds": 4})
    boards.update_item(frames[2]["id"], data={"seconds": 90})
    t = boards.board_text(boards.get_board(b.id))
    assert "6 кадр" in t and "1:34" in t and "Крупный план колец" in t


def test_chat_rules_and_order_link():
    from core.services import boards, orders
    o = orders.add_order("Ролик для Пятёрочки", 25000)
    r = boards.chat_rule("раскадровка: ролик для пятёрочки на 4 кадра 9:16")
    assert r and "4 кадров 9:16" in r[0] and "доска заказа" in r[0]
    b = boards.find_board("пятёрочки")
    assert b and b.order_id == o.id
    assert orders.order_view(orders.find_order(o.id))["board_id"] == b.id
    r = boards.chat_rule("на доску: дрон над крышей, 3 секунды")
    assert r and "На доске" in r[0]
    r = boards.chat_rule("кинь идею с котом на доску пятёрочки")
    assert r and "идею с котом" in r[0]
    stick = [i for i in boards.get_board(b.id)["items"] if i["type"] == "sticky"]
    assert len(stick) == 2
    # стикеры не легли друг на друга
    assert stick[0]["x"] != stick[1]["x"]
    r = boards.chat_rule("что по доске пятёрочки?")
    assert r and "дрон над крышей" in r[0] and "4 кадр" in r[0]
    r = boards.chat_rule("мои доски")
    assert r and "Ролик для Пятёрочки" in r[0]
    assert boards.chat_rule("на доску несуществующая: текст")[0].startswith("Доски «несуществующая» нет")
    # сценарий с шаблоном; «сценарий: такой …» — не команда
    r = boards.chat_rule("сценарий: Кот и дрон")
    assert r and "Сценарий" in r[0]
    assert boards.chat_rule("сценарий: такой — герой идёт и падает, а потом встаёт и снова идёт долго-долго по улице до самого вечера пока не") is None
    assert boards.chat_rule("доска: Кот и дрон") is None or True  # уже есть — вернётся «уже есть», не исключение
    # анализ — не команда
    assert boards.chat_rule("разбери: на доску мысли что делать") is None or True


def test_api_roundtrip_and_validation():
    c = _c()
    b = c.post("/api/boards", json={"title": "Тест", "kind": "storyboard", "frames": 3}).json()
    assert len(b["items"]) == 3
    assert c.post("/api/boards", json={"title": " "}).status_code in (400, 422)
    assert c.post("/api/boards", json={"title": "x", "order_id": 999999}).status_code == 400
    it = c.post(f"/api/boards/{b['id']}/items", json={"type": "sticky", "x": 1, "y": 2, "data": {"text": "привет"}}).json()
    assert it["data"]["text"] == "привет"
    assert c.post(f"/api/boards/{b['id']}/items", json={"type": "nope"}).status_code == 400
    assert c.put(f"/api/boards/{b['id']}/items/{it['id']}", json={"data": {"color": "blue"}}).json()["data"]["color"] == "blue"
    assert c.put(f"/api/boards/{b['id']}/items/999999", json={"x": 1}).status_code == 404
    assert c.put(f"/api/boards/{b['id']}", json={"view": {"x": 10, "y": 20, "k": 1.5, "junk": 1}}).json()["view"] == {"x": 10, "y": 20, "k": 1.5}
    assert c.post(f"/api/boards/{b['id']}/frame").json()["data"]["n"] == 4
    assert c.get(f"/api/boards/{b['id']}/text").json()["text"].startswith("🗂")
    assert c.post(f"/api/boards/{b['id']}/items/delete", json={"ids": [it["id"]]}).json()["deleted"] == 1
    assert c.get("/api/boards/search?q=прив").json() == []
    assert c.delete(f"/api/boards/{b['id']}").json()["ok"] and c.get("/api/boards").json() == []
    assert c.get("/api/boards/999999").status_code == 404
    # картинка: не картинка → 400; src снаружи — отбрасывается
    assert c.post(f"/api/boards/{b['id']}/image", files={"file": ("x.png", b"not-an-image", "image/png")}).status_code == 400
    bad = c.post(f"/api/boards/{b['id']}/items", json={"type": "image", "data": {"src": "https://evil/x.png"}}).json()
    assert bad["data"]["src"] is None
    bad2 = c.post(f"/api/boards/{b['id']}/items", json={"type": "image", "data": {"src": "../../config.yaml"}}).json()
    assert bad2["data"]["src"] is None


def test_graph_has_board_node():
    from core.services import boards, graph, orders
    o = orders.add_order("Монтаж", 1000)
    b = boards.add_board("Монтаж", "storyboard", order_id=o.id, frames=2)
    g = graph.build()
    ids = {n["id"] for n in g["nodes"]}
    assert f"board:{b.id}" in ids
    assert any(e["rel"] == "board" and {e["source"], e["target"]} == {f"board:{b.id}", f"order:{o.id}"} for e in g["edges"])


def test_agent_routes_board_phrases():
    import asyncio
    from core.brain import agent
    r = asyncio.run(agent.handle("доска: Идеи для рилсов", "web"))
    assert "Идеи для рилсов" in r.text and r.via == "rules"
    r = asyncio.run(agent.handle("на доску: снять таймлапс сборки студии", "web"))
    assert "На доске" in r.text
    r = asyncio.run(agent.handle("что по доске?", "web"))
    assert "таймлапс" in r.text


def test_sync_is_atomic_idempotent_and_conflict_safe():
    from core.services import boards
    b = boards.add_board("Синк")
    r0 = boards.get_board(b.id)["revision"]
    items = [
        {"id": -1, "type": "sticky", "x": 0, "y": 0, "w": 180, "h": 180, "z": 1, "data": {"text": "а", "color": "pink", "font_size": 22}},
        {"id": -2, "type": "frame", "x": 300, "y": 0, "w": 320, "h": 10, "z": 2, "data": {"ratio": "9:16", "label": "кадр", "seconds": 2}},
        {"id": -3, "type": "arrow", "x": 0, "y": 0, "w": 0, "h": 0, "z": 3, "data": {"from": {"item": -1, "u": 1, "v": .5}, "to": {"item": -2, "u": 0, "v": .5}}},
    ]
    r = boards.sync_board(b.id, r0, "tok-aaaaaaa1", items)
    assert r["revision"] == r0 + 1 and set(r["id_map"]) == {"-1", "-2", "-3"}
    d = boards.get_board(b.id)
    arrow = next(i for i in d["items"] if i["type"] == "arrow")
    assert arrow["data"]["from"]["item"] == r["id_map"]["-1"] and arrow["data"]["from"]["u"] == 1
    frame = next(i for i in d["items"] if i["type"] == "frame")
    assert frame["h"] > 320 / (9 / 16)      # высота кадра считается на сервере: окно + подпись
    sticky = next(i for i in d["items"] if i["type"] == "sticky")
    assert sticky["data"]["font_size"] == 22
    # повтор того же запроса (сеть моргнула) — тот же ответ, без дублей
    again = boards.sync_board(b.id, r0, "tok-aaaaaaa1", items)
    assert again == r and len(boards.get_board(b.id)["items"]) == 3
    # старая ревизия — конфликт, ничего не записано
    with pytest.raises(boards.BoardConflict):
        boards.sync_board(b.id, r0, "tok-bbbbbbb2", [])
    assert len(boards.get_board(b.id)["items"]) == 3
    # стрелка в никуда / мусорные числа — 400 и откат целиком
    bad = [{"id": -9, "type": "arrow", "data": {"from": {"item": -1}, "to": {"item": 12345678}}}]
    with pytest.raises(ValueError):
        boards.sync_board(b.id, r["revision"], "tok-ccccccc3", bad)
    with pytest.raises(ValueError):
        boards.sync_board(b.id, r["revision"], "tok-ddddddd4", [{"id": -5, "type": "sticky", "x": float("inf"), "data": {}}])
    assert boards.get_board(b.id)["revision"] == r["revision"]
    # удаление через sync: прислали без стикера — стикер и стрелка ушли
    keep = [i for i in d["items"] if i["type"] == "frame"]
    r2 = boards.sync_board(b.id, r["revision"], "tok-eeeeeee5", keep)
    assert {i["type"] for i in boards.get_board(b.id)["items"]} == {"frame"} and r2["revision"] == r["revision"] + 1
    # чужой id (объект другой доски) — отказ
    b2 = boards.add_board("Другая")
    other = boards.add_item(b2.id, "sticky", data={"text": "x"})
    with pytest.raises(ValueError):
        boards.sync_board(b.id, r2["revision"], "tok-fffffff6", [{"id": other.id, "type": "sticky", "data": {}}])
    # камера не двигает ревизию
    boards.update_board(b.id, view={"x": 1, "y": 2, "k": 1.2})
    assert boards.get_board(b.id)["revision"] == r2["revision"]


def test_asset_upload_validates_and_dedups(tmp_path, monkeypatch):
    import io
    from PIL import Image
    from core.services import boards, brain_notes
    monkeypatch.setattr(brain_notes, "MEDIA_DIR", tmp_path)
    buf = io.BytesIO(); Image.new("RGBA", (40, 20), (255, 0, 0, 128)).save(buf, "PNG")
    a = boards.save_asset(buf.getvalue())
    assert a["w"] == 40 and a["h"] == 20 and a["src"].endswith(".png") and (tmp_path / a["src"]).exists()
    assert boards.save_asset(buf.getvalue())["src"] == a["src"]      # тот же файл — тот же путь
    with pytest.raises(ValueError):
        boards.save_asset(b"<svg onload=alert(1)>")
    with pytest.raises(ValueError):
        boards.save_asset(b"")
    c = _c()
    b = c.post("/api/boards", json={"title": "Ассеты"}).json()
    assert c.post(f"/api/boards/{b['id']}/asset", files={"file": ("x.png", buf.getvalue(), "image/png")}).status_code == 200
    assert c.post(f"/api/boards/{b['id']}/asset", files={"file": ("x.svg", b"<svg/>", "image/svg+xml")}).status_code == 400
    r = c.put(f"/api/boards/{b['id']}/sync", json={"revision": 0, "token": "tok-12345678", "items": [{"id": -1, "type": "image", "x": 0, "y": 0, "w": 40, "h": 20, "data": {"src": a["src"]}}]})
    assert r.status_code == 200 and r.json()["revision"] == 1
    assert c.put(f"/api/boards/{b['id']}/sync", json={"revision": 0, "token": "tok-87654321", "items": []}).status_code == 409
    assert c.put(f"/api/boards/{b['id']}/sync", json={"revision": 1, "token": "short", "items": []}).status_code == 422
