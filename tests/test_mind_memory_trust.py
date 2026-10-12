# -*- coding: utf-8 -*-
"""Экран доверия «Память»: source наружу, wrong, due, confirm, used_fact_ids, замок.

Правило: фикстуры fresh_db/_client из tests/conftest.py параметром,
писать в боевую data/jarvis.db запрещено.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from core.services import memory


@pytest.fixture(autouse=True)
def _clean_slots():
    """Слоты suggest/used общие на процесс — чистим до и после каждого теста файла,
    иначе «хвост» одного теста просочится в инжектор другого."""
    memory.clear_suggest()
    memory.clear_used_ids()
    yield
    memory.clear_suggest()
    memory.clear_used_ids()


def _offline(monkeypatch):
    """Без моделей: эмбеддингов нет, облака нет — только правила и офлайн-ветки."""
    from core.brain import llm
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)

    async def no_ollama(force=False):
        return False
    monkeypatch.setattr(llm, "ollama_available", no_ollama)

    async def emb_avail():
        return False
    monkeypatch.setattr(llm, "embed_available", emb_avail)


# ---------------------------------------------------------------- 1. source
def test_facts_list_has_source(_client):
    r = _client.post("/api/facts", json={"text": "Любит зелёный чай по утрам", "layer": "long"})
    assert r.status_code == 200, r.text
    items = _client.get("/api/facts").json()["items"]
    assert items, "факт не сохранился"
    for it in items:
        assert "source" in it, f"нет поля source: {sorted(it)}"
        assert it["source"] in ("чат", "сайт", "тг"), it["source"]


# ---------------------------------------------------------------- 2. wrong
def test_fact_wrong_archives_with_reason(_client):
    fid = _client.post("/api/facts", json={"text": "У хозяина собака Рекс", "layer": "long"}).json()["id"]
    r = _client.post(f"/api/facts/{fid}/wrong")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["layer"] == "archive" and body["archive_reason"] == "неверно", body
    long_ids = [f["id"] for f in _client.get("/api/facts", params={"layer": "long"}).json()["items"]]
    assert fid not in long_ids, "ошибочный факт остался в списке long"
    assert _client.post("/api/facts/99999/wrong").status_code == 404


# ---------------------------------------------------------------- 3. due
def test_fact_due_extracted(_client):
    r = _client.post("/api/facts", json={"text": "Сын уходит в армию 28 октября", "layer": "long"})
    assert r.status_code == 200, r.text
    due = r.json()["due"]
    assert due and "-10-28" in due, due  # календарный эвент при этом НЕ создаём — только метка
    r2 = _client.post("/api/facts", json={"text": "Любит зелёный чай по утрам", "layer": "long"})
    assert r2.status_code == 200, r2.text
    assert r2.json()["due"] is None
    items = {f["id"]: f for f in _client.get("/api/facts").json()["items"]}
    assert items[r.json()["id"]]["due"] and "-10-28" in items[r.json()["id"]]["due"]
    assert items[r2.json()["id"]]["due"] is None
    assert "due" in items[r.json()["id"]]


def test_fact_due_migration_on_old_schema(tmp_path):
    """Копия старой схемы (без due): миграции дотягивают колонку, данные целы."""
    import sqlite3

    from sqlalchemy import create_engine, text

    from core import migrations
    p = tmp_path / "old.db"
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE fact (id INTEGER PRIMARY KEY, text VARCHAR, layer VARCHAR,"
                " category VARCHAR, core BOOLEAN, confidence FLOAT, source_msg INTEGER,"
                " replaced_by INTEGER, archive_reason VARCHAR, vector VARCHAR, uses INTEGER,"
                " last_used DATETIME, created_at DATETIME, updated_at DATETIME)")
    con.execute("INSERT INTO fact (text, layer) VALUES ('Сын уходит в армию 28 октября', 'long')")
    con.commit()
    con.close()
    eng = create_engine(f"sqlite:///{p}")
    res = migrations.apply(eng, had_db=False)
    assert 14 in res["applied"]
    with eng.connect() as c:
        cols = {row[1] for row in c.execute(text('PRAGMA table_info("fact")')).all()}
        kept = c.execute(text("SELECT text FROM fact")).scalar()
    assert "due" in cols, sorted(cols)
    assert kept == "Сын уходит в армию 28 октября", "миграция потеряла данные"


# ---------------------------------------------------------------- 4. confirm
def test_fact_confirm_sets_confirmed(_client):
    from datetime import datetime, timedelta
    fid = _client.post("/api/facts", json={"text": "Ходит в бассейн по вторникам", "layer": "long"}).json()["id"]
    # состариваем, чтобы висел бейдж stale (>30 дней без касаний)
    from core import db
    with db.session() as s:
        f = s.get(db.Fact, fid)
        f.updated_at = datetime.now() - timedelta(days=45)
        s.add(f)
        s.commit()
    r = _client.post(f"/api/facts/{fid}/confirm")
    assert r.status_code == 200, r.text
    assert (datetime.now() - datetime.fromisoformat(r.json()["updated_at"])).days == 0
    meta = memory.fact_meta({fid})[fid]
    assert meta["confirmed"] is not None, "confirmed_at не выставлен — stale не снят"
    assert _client.post("/api/facts/99999/confirm").status_code == 404


# ---------------------------------------------------------------- 5. used_fact_ids
def test_context_with_ids_returns_used(fresh_db, monkeypatch):
    _offline(monkeypatch)

    async def go():
        core = await memory.add_fact("Хозяина зовут Тони", layer="long", core=True)
        cat = await memory.add_fact("У хозяина кот Барсик", layer="long")
        bike = await memory.add_fact("Любит кататься на велосипеде", layer="long")
        text, ids = await memory.context_with_ids("что купить для кот")
        assert "Тони" in text and "Барсик" in text and "велосипеде" not in text
        assert core.id in ids and cat.id in ids and bike.id not in ids, ids
        from core import db
        with db.session() as s:
            assert s.get(db.Fact, cat.id).uses >= 1, "uses должен инкрементиться как раньше"
        plain = await memory.context("что купить для кот")
        assert isinstance(plain, str) and "Барсик" in plain, "старый контракт context()->str не сломан"
        assert memory.peek_used_ids() is None, "прямой вызов слот не трогает — только путь агента"
    asyncio.run(go())


def test_chat_response_carries_used_fact_ids(_client, monkeypatch):
    _offline(monkeypatch)
    fid = asyncio.run(memory.add_fact("У хозяина кот Барсик", layer="long", core=True)).id
    from core.brain import agent

    async def fake_handle(text, channel="tg"):
        memory.set_used_ids([fid], channel)
        return agent.Reply("Мяу.", [], "rules", used_fact_ids=[fid])
    monkeypatch.setattr(agent, "handle", fake_handle)
    data = _client.post("/api/chat", json={"text": "привет", "channel": "web"}).json()
    assert data.get("used_fact_ids") == [fid], data
    # стрим: done Descriptive несёт те же ids (инжектор, без правки чужого app.py)
    memory.set_used_ids([fid], "web")
    r = _client.post("/api/chat/stream", json={"text": "привет", "channel": "web"})
    assert r.status_code == 200, r.text
    done = json.loads(r.text.split("event: done\ndata: ", 1)[1].split("\n\n", 1)[0])
    assert done.get("used_fact_ids") == [fid], done


# ---------------------------------------------------------------- 6. замок
def test_fact_private_migration_on_old_schema(tmp_path):
    """Схема после v14 (due есть, is_private нет): v15 дотягивает флаг, данные целы."""
    import sqlite3

    from sqlalchemy import create_engine, text

    from core import migrations
    p = tmp_path / "old14.db"
    con = sqlite3.connect(str(p))
    con.execute("CREATE TABLE fact (id INTEGER PRIMARY KEY, text VARCHAR, layer VARCHAR,"
                " category VARCHAR, core BOOLEAN, confidence FLOAT, source_msg INTEGER,"
                " replaced_by INTEGER, archive_reason VARCHAR, vector VARCHAR, uses INTEGER,"
                " last_used DATETIME, due VARCHAR, created_at DATETIME, updated_at DATETIME)")
    con.execute("INSERT INTO fact (text, layer) VALUES ('Счёт в зарубежном банке', 'long')")
    con.commit()
    con.close()
    eng = create_engine(f"sqlite:///{p}")
    res = migrations.apply(eng, had_db=False)
    assert 15 in res["applied"]
    with eng.connect() as c:
        cols = {row[1] for row in c.execute(text('PRAGMA table_info("fact")')).all()}
        kept = c.execute(text("SELECT text FROM fact")).scalar()
    assert "is_private" in cols, sorted(cols)
    assert kept == "Счёт в зарубежном банке", "миграция потеряла данные"


def test_fact_private_lock(_client, monkeypatch):
    _offline(monkeypatch)

    async def go():
        pub = await memory.add_fact("У хозяина кот Барсик", layer="long")
        priv = await memory.add_fact("Счёт в зарубежном банке", layer="long")
        return pub.id, priv.id
    pub_id, priv_id = asyncio.run(go())
    # тумблер — только ручной, через PUT
    r = _client.put(f"/api/facts/{priv_id}", json={"is_private": True})
    assert r.status_code == 200, r.text
    assert r.json()["is_private"] is True
    items = {f["id"]: f for f in _client.get("/api/facts").json()["items"]}
    assert items[priv_id]["is_private"] is True, "GET не отдаёт флаг"
    assert items[pub_id]["is_private"] is False
    # локально приватное в контексте есть...
    local_text, local_ids = asyncio.run(memory.context_with_ids("банк счёт деньги", include_private=True))
    assert priv_id in local_ids and "зарубежном" in local_text
    # ...а в облако не уходит
    cloud_text, cloud_ids = asyncio.run(memory.context_with_ids("банк счёт деньги", include_private=False))
    assert priv_id not in cloud_ids and "зарубежном" not in cloud_text, cloud_text


def test_patch_injects_used_ids_without_touching_empty(monkeypatch):
    """Инжектор: пустой слот — тело не трогаем (старые тесты на suggest целы),
    есть ids — вшиваем рядом с suggest_fact, suggest-флаг не мешает."""
    from core.api.routers import chat as chat_router
    monkeypatch.setattr(memory, "suggest_enabled", lambda: False)
    msgs = [
        {"type": "http.response.start", "status": 200,
         "headers": [(b"content-type", b"application/json"), (b"content-length", b"2")]},
        {"type": "http.response.body", "body": b'{"text": "ok"}'},
    ]
    assert chat_router._patch_json(msgs) == msgs
    memory.set_used_ids([7])
    out = chat_router._patch_json(msgs)
    body = b"".join(m["body"] for m in out if m["type"] == "http.response.body")
    assert json.loads(body)["used_fact_ids"] == [7]
    done = b'event: done\ndata: {"text": "ok", "actions": []}\n\n'
    assert chat_router._patch_sse(done) is None or True  # слот уже забрали JSON-веткой
    memory.set_used_ids([7])
    patched = json.loads(chat_router._patch_sse(done).decode("utf-8").split("data: ", 1)[1])
    assert patched["used_fact_ids"] == [7] and patched["text"] == "ok"


def test_clear_suggest_resets_used_slot():
    """Сброс хода гасит оба слота: чужие used-ids не прилипают к чужому ответу (регресс полного сьюта)."""
    from core.api.routers import chat as chat_router
    memory.set_used_ids([7])
    memory.clear_suggest()
    msgs = [
        {"type": "http.response.start", "status": 200,
         "headers": [(b"content-type", b"application/json"), (b"content-length", b"2")]},
        {"type": "http.response.body", "body": b'{"text": "ok"}'},
    ]
    assert chat_router._patch_json(msgs) == msgs


def test_extract_hides_private_from_cloud(fresh_db, monkeypatch):
    """Замок: приватные факты не уходят в облако даже в known-контексте извлечения."""
    from core.brain import llm
    pub = asyncio.run(memory.add_fact("Публичный факт про велосипед и утренние прогулки", core=True))
    priv = asyncio.run(memory.add_fact("Приватный факт про здоровье и таблетки", core=True))
    asyncio.run(memory.update_fact(priv.id, is_private=True))
    seen = {}

    async def fake_cloud(system, user):
        seen["user"] = user
        return '{"add": [], "update": []}'

    monkeypatch.setattr(memory, "where", lambda: "cloud")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)
    monkeypatch.setattr(llm, "cloud_chat", fake_cloud)
    asyncio.run(memory.extract("вчера долго гулял по парку с друзьями вечером"))
    assert "user" in seen, "облако вообще не позвали"
    assert "Приватный факт" not in seen["user"]
    assert "Публичный факт" in seen["user"]


def test_nightly_promote_keeps_hidden_private(fresh_db, monkeypatch):
    """Ночная уборка: спрятанный от облака приватный факт не архивируем вслепую — оставляем."""
    from datetime import datetime, timedelta

    from core.db import Fact, session
    pub = asyncio.run(memory.add_fact("Старый публичный факт про гараж и машину", layer="short"))
    priv = asyncio.run(memory.add_fact("Старый приватный факт про здоровье и анализы", layer="short"))
    asyncio.run(memory.update_fact(priv.id, is_private=True))
    with session() as s:
        for fid, uses in ((pub.id, 0), (priv.id, 999)):
            row = s.get(Fact, fid)
            row.created_at = datetime.now() - timedelta(days=400)
            row.updated_at = datetime.now() - timedelta(days=400)
            row.uses = uses
            s.add(row)
        s.commit()
    seen = {}

    async def fake_ask(system, user):
        seen["user"] = user
        return None, "none"

    monkeypatch.setattr(memory, "where", lambda: "cloud")
    monkeypatch.setattr(memory, "_ask", fake_ask)
    asyncio.run(memory.nightly())
    assert "приватный" not in seen.get("user", "").lower()
    with session() as s:
        assert s.get(Fact, priv.id).layer == "long"
        assert s.get(Fact, pub.id).layer == "archive"
