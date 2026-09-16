"""Этап Б: связи в Мозге — эмбеддинги отбирают кандидатов, нейронка решает, крестик убирает навсегда; фильтр секретов."""
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


def _client():
    from fastapi.testclient import TestClient
    from core.api.app import app
    return TestClient(app, base_url="http://localhost", client=("127.0.0.1", 5555))


def _seed(monkeypatch, decide):
    """Три заметки с «эмбеддингами», где всё похоже на всё (как у маленькой модели), и нейронка `decide`."""
    from core.brain import llm
    from core.services import brain_notes
    a = brain_notes.add_note("Помочь маме с сайтом: перенести на новый хостинг", polish=False)
    b = brain_notes.add_note("Купить апельсиновый сок и хлеб", polish=False)
    c = brain_notes.add_note("Домен для маминого сайта оплачен до марта", polish=False)
    vecs = {a.id: [1.0, 0.8, 0.1], b.id: [0.9, 0.7, 0.3], c.id: [1.0, 0.75, 0.15]}   # косинусы ~0.95+ у всех пар
    with db.session() as s:
        for nid, v in vecs.items():
            s.add(db.Embedding(ref_table="note", ref_id=nid, model=llm.EMBED_MODEL, vector=json.dumps(v), text_hash=f"h{nid}"))
        s.commit()

    async def cloud_enabled_true():
        return True
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)

    async def fake_cloud_chat(system, user, history=None, **kw):
        return decide(user)
    monkeypatch.setattr(llm, "cloud_chat", fake_cloud_chat)

    async def no_ollama(force=False):
        return False
    monkeypatch.setattr(llm, "ollama_available", no_ollama)
    return a, b, c


def _decide_by_topic(user: str) -> str:
    """«Нейронка»: связывает только кандидатов про мамин сайт."""
    out = []
    head, cands = user.split("КАНДИДАТЫ:")
    topic = lambda t: "сайт" in t.lower() and "мам" in t.lower()  # noqa: E731
    for line in cands.strip().splitlines():
        idx = line[1:line.index("]")]
        if topic(head) and topic(line):
            out.append({"id": idx, "why": "оба про сайт для мамы"})
    return json.dumps({"related": out}, ensure_ascii=False)


def test_llm_filters_orange_juice_and_cross_forgets(monkeypatch):
    from core.services import relations
    a, b, c = _seed(monkeypatch, _decide_by_topic)
    # кандидаты по эмбеддингам — всё похоже на всё (в этом и была беда)
    assert {k for k, _ in relations.candidates(f"note:{a.id}")} == {f"note:{b.id}", f"note:{c.id}"}
    got = asyncio.run(relations.compute(f"note:{a.id}"))
    assert [r.status for r in got] == ["auto"] and got[0].why == "оба про сайт для мамы"
    rel = relations.related(f"note:{a.id}")
    assert [r["id"] for r in rel] == [c.id] and rel[0]["via"] == "cloud"
    # сок отклонён и запомнен как «no» — второй раз не спрашиваем
    calls = []

    async def counting(system, user, history=None, **kw):
        calls.append(1); return _decide_by_topic(user)
    from core.brain import llm
    monkeypatch.setattr(llm, "cloud_chat", counting)
    assert asyncio.run(relations.compute(f"note:{a.id}")) == [] and not calls
    # у сока связей нет ни с кем (симметрия: пара a–b уже решена как no; b–c спросим — тоже нет)
    asyncio.run(relations.compute(f"note:{b.id}"))
    assert relations.related(f"note:{b.id}") == []
    # API: карточка, крестик, подтверждение
    cl = _client()
    r = cl.get(f"/api/notes/{a.id}/related").json()
    assert len(r) == 1 and r[0]["why"] == "оба про сайт для мамы"
    rid = r[0]["relation_id"]
    assert cl.put(f"/api/relations/{rid}", json={"status": "yes"}).json()["status"] == "yes"
    assert cl.put(f"/api/relations/{rid}", json={"status": "no"}).json()["status"] == "no"
    assert cl.get(f"/api/notes/{a.id}/related").json() == [] and cl.get(f"/api/notes/{c.id}/related").json() == []
    assert relations.pairs() == []
    assert cl.put("/api/relations/999", json={"status": "no"}).status_code == 404


def test_without_any_model_only_hard_threshold(monkeypatch):
    from core.brain import llm
    from core.services import relations
    a, b, c = _seed(monkeypatch, _decide_by_topic)
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    got = asyncio.run(relations.compute(f"note:{a.id}"))
    assert got and all(r.via == "embed" and r.why == "похоже по словам" and r.score >= relations.HARD_MIN for r in got)
    # правка текста → эмбеддинг сменился → запись снова в очереди на пересчёт
    assert f"note:{a.id}" not in relations.pending(100)
    with db.session() as s:
        e = s.exec(db.select(db.Embedding).where(db.Embedding.ref_id == a.id)).first()
        e.text_hash = "changed"; s.add(e); s.commit()
    assert f"note:{a.id}" in relations.pending(100)


def test_graph_uses_relations_and_delete_forgets(monkeypatch):
    from core.services import brain_notes, graph, relations
    a, b, c = _seed(monkeypatch, _decide_by_topic)
    asyncio.run(relations.compute(f"note:{a.id}"))
    g = graph.build()
    sim = [e for e in g["edges"] if e["rel"] == "similar"]
    assert len(sim) == 1 and {sim[0]["source"], sim[0]["target"]} == {f"note:{a.id}", f"note:{c.id}"}
    brain_notes.delete_note(c.id)
    assert relations.related(f"note:{a.id}") == [] and not [e for e in graph.build()["edges"] if e["rel"] == "similar"]


def test_relations_can_be_disabled(monkeypatch):
    from core.services import relations
    from core import config as _c
    monkeypatch.setattr(relations, "enabled", lambda: False)
    assert relations.related("note:1") == [] and relations.pairs() == []
    assert relations.where() in ("cloud", "auto", "local")
    assert _c.EDITABLE["brain.relations.where"][0] == "str"


def test_anonymizer_hides_secrets_but_keeps_everyday_text():
    from core.brain.llm import anonymize
    assert anonymize("пароль от вайфая qwerty123 запомни") == "пароль от вайфая [скрыто] запомни"
    assert anonymize("пин карты 4821") == "пин карты [скрыто]"
    assert anonymize("код из смс 384712 пришёл") == "код из смс [скрыто] пришёл"
    assert anonymize("Пароль: hunter2") == "Пароль: [скрыто]"
    assert anonymize("password=abc123") == "password=[скрыто]"
    assert anonymize("токен бота 123456:ABC-def") == "токен бота [скрыто]"
    assert "[ключ]" in anonymize("ключ gsk_abcdefghijklmnopqrstuvwxyz123456")
    assert anonymize("пароль от домофона 1234, код от сейфа 9876") == "пароль от домофона [скрыто], код от сейфа [скрыто]"
    # бытовые фразы со словом «пароль» без самого пароля — не трогаем
    assert anonymize("забыл пароль от почты, надо восстановить") == "забыл пароль от почты, надо восстановить"
    assert anonymize("поменять пароль в понедельник") == "поменять пароль в понедельник"
