"""Этап В: память о хозяине — слои, извлечение нейронкой, фильтр секретов, контекст, «запомни/забудь/что знаешь», уборка, API."""
import asyncio
import json
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


def _brain(monkeypatch, answer, embeds=None):
    """Облако отвечает `answer(user_text)`, Ollama нет; эмбеддинги — по словарю `embeds` (слово → вектор) или выключены."""
    from core.brain import llm
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)

    async def fake_cloud_chat(system, user, history=None, **kw):
        return answer(user) if callable(answer) else answer
    monkeypatch.setattr(llm, "cloud_chat", fake_cloud_chat)

    async def no_ollama(force=False):
        return False
    monkeypatch.setattr(llm, "ollama_available", no_ollama)

    async def emb_avail():
        return embeds is not None
    monkeypatch.setattr(llm, "embed_available", emb_avail)

    async def emb(texts):
        out = []
        for t in texts:
            v = [0.0, 0.0, 0.0]
            for k, vec in (embeds or {}).items():
                if k in t.lower():
                    v = [a + b for a, b in zip(v, vec)]
            out.append(v if any(v) else [0.0, 0.0, 1.0])
        return out
    monkeypatch.setattr(llm, "embed", emb)


def _facts():
    with db.session() as s:
        return list(s.exec(db.select(db.Fact)))


# ---------------------------------------------------------------- извлечение
def test_extract_adds_and_updates(monkeypatch):
    from core.services import memory
    _brain(monkeypatch, json.dumps({"add": [{"text": "У хозяина кот Барсик", "layer": "long", "category": "быт"}], "update": []}))
    r = asyncio.run(memory.extract("Кстати, мой кот Барсик сегодня опять разбил вазу, третий раз за неделю"))
    assert len(r["added"]) == 1 and r["added"][0].layer == "long"
    f = r["added"][0]
    # нейронка уточняет: тот же id → новая версия, старая в архив со ссылкой
    _brain(monkeypatch, json.dumps({"add": [], "update": [{"id": f.id, "text": "У хозяина два кота: Барсик и Мурзик"}]}))
    r2 = asyncio.run(memory.extract("Мы завели второго кота, назвали Мурзик, Барсик пока не в восторге"))
    assert len(r2["updated"]) == 1
    rows = _facts()
    live = [x for x in rows if x.layer != "archive"]
    arch = [x for x in rows if x.layer == "archive"]
    assert len(live) == 1 and "Мурзик" in live[0].text
    assert len(arch) == 1 and arch[0].replaced_by == live[0].id and arch[0].id == f.id


def test_extract_nothing_and_not_worth(monkeypatch):
    from core.services import memory
    calls = []

    def ans(user):
        calls.append(user)
        return json.dumps({"add": [], "update": []})
    _brain(monkeypatch, ans)
    assert asyncio.run(memory.extract("Сегодня погода в целом ничего, гулял по парку"))["added"] == []
    assert len(calls) == 1
    # команды, вопросы, короткое и действия правил — нейронку даже не зовём
    for t, acts in [("купить корм", None), ("поставь задачу купить корм коту завтра", None),
                    ("а что ты думаешь про отпуск в горах?", None), ("кофе 250", ["add_expense"]),
                    ("встреча с мопсом завтра в 15:00 в офисе", ["add_event"])]:
        assert not memory.worth_extracting(t, acts), t
    assert memory.worth_extracting("я вообще не пью кофе, только зелёный чай по утрам")


def test_secrets_never_stored(monkeypatch):
    from core.services import memory
    _brain(monkeypatch, json.dumps({"add": [{"text": "Пароль от почты qwerty123", "layer": "long"}], "update": []}))
    # реплика с паролем — extract не зовёт нейронку вовсе
    assert asyncio.run(memory.extract("запиши себе: пароль от почты qwerty123 на всякий"))["via"] == "skip"
    # даже если нейронка сама предложит секрет — фильтр на входе
    assert asyncio.run(memory.add_fact("Пароль от почты qwerty123")) is None
    assert asyncio.run(memory.add_fact("PIN карты 1234")) is None
    assert memory.add_fact_sync("токен api_key=abcdef") is None
    assert _facts() == []


def test_dedup(monkeypatch):
    from core.services import memory
    _brain(monkeypatch, "", embeds={"кот": [1.0, 0.0, 0.0]})
    a = asyncio.run(memory.add_fact("У хозяина кот Барсик"))
    b = asyncio.run(memory.add_fact("у хозяина кот барсик."))
    assert a.id == b.id and len(_facts()) == 1
    c = memory.add_fact_sync("У хозяина кот Барсик", layer="long", core=True)
    assert c.id == a.id and c.core
    assert len(_facts()) == 1


# ---------------------------------------------------------------- контекст
def test_context_core_and_relevant(monkeypatch):
    from core.services import memory
    _brain(monkeypatch, "", embeds={"кот": [1.0, 0.0, 0.0], "работ": [0.0, 1.0, 0.0]})
    asyncio.run(memory.add_fact("Хозяина зовут Тони", core=True))
    asyncio.run(memory.add_fact("У хозяина кот Барсик"))
    asyncio.run(memory.add_fact("Работает дизайнером на фрилансе", category="работа"))
    ctx = asyncio.run(memory.context("чем кормить кота при линьке?"))
    assert "Тони" in ctx and "Барсик" in ctx and "дизайнер" not in ctx
    ctx2 = asyncio.run(memory.context("сколько брать за работу над логотипом?"))
    assert "дизайнер" in ctx2 and "Барсик" not in ctx2
    # использование считается — это защищает факт от архива «не пригодился»
    cat = next(f for f in _facts() if "Барсик" in f.text)
    assert cat.uses == 1 and cat.last_used is not None
    # выключили — контекст пустой
    monkeypatch.setattr(memory, "enabled", lambda: False)
    assert asyncio.run(memory.context("кот")) == ""


def test_context_empty_without_facts(monkeypatch):
    from core.services import memory
    _brain(monkeypatch, "")
    assert asyncio.run(memory.context("привет")) == ""


# ---------------------------------------------------------------- правила чата
def test_chat_remember_forget_about(monkeypatch):
    from core.brain import agent
    from core.services import memory
    _brain(monkeypatch, "")
    r = agent.rules("запомни, что у меня аллергия на арахис", "test")
    assert r and "add_fact" in r.actions
    assert any("аллергия" in f.text and f.layer == "long" for f in _facts())
    # «запомни: идея для ролика» — это заметка в Мозг, а не факт о человеке
    r2 = agent.rules("запомни: идея для ролика про кофе", "test")
    assert r2 is None or "add_fact" not in r2.actions
    r3 = agent.rules("что ты обо мне знаешь?", "test")
    assert r3 and "about_me" in r3.actions and "арахис" in r3.text
    r4 = agent.rules("забудь про аллергию на арахис", "test")
    assert r4 and "forget_fact" in r4.actions
    assert all(f.layer == "archive" for f in _facts() if "арахис" in f.text)
    r5 = agent.rules("что ты обо мне знаешь", "test")
    assert "арахис" not in r5.text


def test_undo_fact(monkeypatch):
    from core.brain import agent
    from core.services import undo
    _brain(monkeypatch, "")
    agent.rules("запомни, что у меня кот Барсик", "test")
    msg = undo.undo_last()
    assert msg and "факт" in msg
    assert all(f.layer == "archive" for f in _facts())


def test_tool_remember_fact(monkeypatch):
    from core.tools import registry
    _brain(monkeypatch, "")
    out = registry.run_tool("remember_fact", {"text": "Хозяин предпочитает отвечать коротко"})
    assert "апомнил" in out
    assert any("коротко" in f.text for f in _facts())


# ---------------------------------------------------------------- уборка
def test_nightly_promote_archive(monkeypatch):
    from core.services import memory
    _brain(monkeypatch, lambda u: json.dumps({"keep": [int(l.split("]")[0][1:]) for l in u.splitlines() if "простуд" not in l.lower() and l.startswith("[")]}))
    a = asyncio.run(memory.add_fact("Простудился, лечится дома", layer="short"))
    b = asyncio.run(memory.add_fact("Любит ездить на дачу по выходным", layer="short"))
    c = asyncio.run(memory.add_fact("Свежее: сегодня много встреч", layer="short"))
    d = asyncio.run(memory.add_fact("Когда-то интересовался шахматами", layer="long"))
    e = asyncio.run(memory.add_fact("Пьёт кофе без сахара", layer="long"))
    with db.session() as s:
        for fid, days in ((a.id, 10), (b.id, 10), (d.id, 90)):
            f = s.get(db.Fact, fid); f.created_at = datetime.now() - timedelta(days=days); s.add(f)
        f = s.get(db.Fact, e.id); f.created_at = datetime.now() - timedelta(days=90); f.uses = 3; f.last_used = datetime.now(); s.add(f)
        s.commit()
    res = asyncio.run(memory.nightly())
    assert res["promoted"] == 1 and res["archived"] == 2
    by = {f.id: f for f in _facts()}
    assert by[a.id].layer == "archive" and by[b.id].layer == "long" and by[c.id].layer == "short"
    assert by[d.id].layer == "archive" and by[d.id].archive_reason == "не пригодился"
    assert by[e.id].layer == "long"


def test_portrait(monkeypatch):
    from core.services import memory
    _brain(monkeypatch, "— Тони, дизайнер\n— Живёт с котом\n— Любит кофе")
    for t in ("Зовут Тони", "Дизайнер на фрилансе", "Есть кот Барсик"):
        asyncio.run(memory.add_fact(t))
    p = asyncio.run(memory.rebuild_portrait(force=True))
    assert "Тони" in p and db.get_setting("user.portrait_at", "")
    # не форс — в течение недели не пересобирается
    _brain(monkeypatch, "ДРУГОЙ")
    assert "Тони" in asyncio.run(memory.rebuild_portrait())
    assert "Тони" in asyncio.run(memory.context("привет"))


# ---------------------------------------------------------------- API
def test_facts_api(monkeypatch):
    from core.services import memory
    _brain(monkeypatch, "")
    c = _client()
    r = c.post("/api/facts", json={"text": "Не ест мясо", "layer": "long", "category": "предпочтение"})
    assert r.status_code == 200
    fid = r.json()["id"]
    assert c.post("/api/facts", json={"text": "пароль 1234"}).status_code == 400
    r = c.put(f"/api/facts/{fid}", json={"core": True})
    assert r.json()["core"] is True and r.json()["id"] == fid
    r = c.put(f"/api/facts/{fid}", json={"text": "Вегетарианец уже 5 лет"})
    new_id = r.json()["id"]
    assert new_id != fid and r.json()["layer"] == "long" and r.json()["core"] is True
    lst = c.get("/api/facts").json()
    assert lst["stats"]["long"] == 1 and lst["stats"]["archive"] == 1 and lst["stats"]["core"] == 1
    assert "vector" not in lst["items"][0]
    assert c.get("/api/facts", params={"layer": "archive"}).json()["items"][0]["replaced_by"] == new_id
    assert c.post(f"/api/facts/{new_id}/forget").json()["layer"] == "archive"
    assert c.post(f"/api/facts/{new_id}/restore").json()["layer"] == "long"
    assert c.post("/api/facts/99999/forget").status_code == 404
    assert c.post("/api/facts/nightly").json() == {"promoted": 0, "archived": 0}
    assert memory.stats()["long"] == 1
