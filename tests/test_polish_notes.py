# -*- coding: utf-8 -*-
"""Правка заметок нейронкой (E2): «привести к одному смыслу» / «расширить тему»,
история версий, apply/revert и честные ошибки, когда LLM недоступна.

Сеть не трогаем: клиент LLM подменяется (monkeypatch по core.brain.llm), БД — временная
из tests/conftest.py (`fresh_db`/`_client`), data/jarvis.db на запись не открывается.
"""
from __future__ import annotations

import json
import os

import pytest  # noqa: F401  (фикстуры/параметризация могут пригодиться)

os.environ.setdefault("ASSISTANT_TEST", "1")


# ---------------- моки LLM ----------------
def _mock_llm(monkeypatch, answer):
    """Подменяем клиента LLM: answer — строка JSON либо callable(system, user) -> str."""
    from core.brain import llm

    async def avail(force=False):
        return True

    async def chat(messages, tools=None, temperature=0.3, json_mode=False, **kw):
        system = messages[0]["content"] if messages else ""
        user = messages[-1]["content"] if messages else ""
        return {"content": answer(system, user) if callable(answer) else answer, "tool_calls": []}

    async def no_embed():
        return False

    monkeypatch.setattr(llm, "ollama_available", avail)
    monkeypatch.setattr(llm, "ollama_chat", chat)
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(llm, "embed_available", no_embed)


def _llm_down(monkeypatch):
    """Ни Ollama, ни облака — как на выключенной машине."""
    from core.brain import llm

    async def no(force=False):
        return False

    async def no_embed():
        return False

    monkeypatch.setattr(llm, "ollama_available", no)
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(llm, "embed_available", no_embed)


# ---------------- хелперы ----------------
def _note(text, tags=None):
    """Заметка без фоновой причёсывания — чтобы LLM сама не переписала текст под тестом."""
    from core.services import brain_notes
    return brain_notes.add_note(text, tags or [], "web", polish=False)


def _get_note(nid):
    from core import db
    with db.session() as s:
        return s.get(db.Note, nid)


def _polish_url(nid):
    return f"/api/mind/notes/{nid}/polish"


# ---------------- rewrite: предложение → apply → revert ----------------
def test_rewrite_apply_revert_history(_client, monkeypatch):
    n = _note("ну вот идея — снять ролик про какуюто кофейню, типа репортаж")
    _mock_llm(monkeypatch, '{"text": "Идея: снять репортажный ролик про кофейню."}')

    r = _client.post(_polish_url(n.id), json={"mode": "rewrite"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["mode"] == "rewrite"
    assert d["original"] == n.text
    assert d["polished"] == "Идея: снять репортажный ролик про кофейню."
    assert d["revision_id"] >= 1

    # предложение ещё НЕ сохранено — заметка как была
    assert _get_note(n.id).text == n.text

    # история: текущая версия уже записана, помечена как текущая и «оригинал»
    revs = _client.get(f"/api/mind/notes/{n.id}/revisions")
    assert revs.status_code == 200, revs.text
    items = revs.json()
    assert [v["text"] for v in items] == [n.text]
    assert items[0]["current"] is True and items[0]["action"] == "оригинал"
    assert items[0]["at"]  # дата есть

    # применяем
    a = _client.post(f"/api/mind/notes/{n.id}/apply", json={"text": d["polished"]})
    assert a.status_code == 200, a.text
    assert a.json()["text"] == d["polished"]
    assert _get_note(n.id).text == d["polished"]
    items = _client.get(f"/api/mind/notes/{n.id}/revisions").json()
    assert len(items) == 2, items
    assert items[0]["current"] is False and items[-1]["current"] is True

    # откат — возвращается прежний текст, оригинал в raw не тронут
    v = _client.post(f"/api/mind/notes/{n.id}/revert")
    assert v.status_code == 200, v.text
    assert v.json()["text"] == n.text
    assert _get_note(n.id).text == n.text
    assert _get_note(n.id).raw == n.text

    # история после отката ничего не потеряла
    texts = [x["text"] for x in _client.get(f"/api/mind/notes/{n.id}/revisions").json()]
    assert n.text in texts and d["polished"] in texts


# ---------------- expand: контекст из чужих заметок ----------------
def test_expand_uses_related_notes_as_context(_client, monkeypatch):
    _note("План съёмки ролика про кофейню на пятницу", ["идея"])
    n = _note("кофейня", ["идея"])
    seen: dict = {}

    def answer(system, user):
        seen["system"], seen["user"] = system, user
        return '{"text": "кофейня — тема ролика; план съёмки на пятницу."}'

    _mock_llm(monkeypatch, answer)
    r = _client.post(_polish_url(n.id), json={"mode": "expand"})
    assert r.status_code == 200, r.text
    payload = json.loads(seen["user"])
    assert payload["note"]["text"] == "кофейня"
    assert "контекст" in seen["system"].lower()   # взят именно промпт расширения, а не причёсывания
    # другая заметка с тем же тегом попала в контекст — материал есть, выдумывать не надо
    assert "План съёмки" in payload["context"]
    assert r.json()["mode"] == "expand"
    assert r.json()["original"] == "кофейня"


def test_expand_without_context_still_works(_client, monkeypatch):
    """Контекста нет — просто структурируем, без выдумок и без ошибки."""
    n = _note("абсолютно одинокая мысль про маршруты")
    seen: dict = {}

    def answer(system, user):
        seen["user"] = user
        return '{"text": "Маршруты: одна мысль."}'

    _mock_llm(monkeypatch, answer)
    r = _client.post(_polish_url(n.id), json={"mode": "expand"})
    assert r.status_code == 200, r.text
    assert json.loads(seen["user"])["context"] == ""


# ---------------- честные ошибки ----------------
def test_llm_down_is_503_and_note_untouched(_client, monkeypatch):
    n = _note("идейка какаято про маршруты велосипедные по городу")
    _llm_down(monkeypatch)
    r = _client.post(_polish_url(n.id), json={"mode": "rewrite"})
    assert r.status_code == 503, r.text
    assert "Нейронка недоступна" in r.json()["detail"]
    assert _get_note(n.id).text == n.text            # заметка НЕ изменена
    assert _client.get(f"/api/mind/notes/{n.id}/revisions").json() == []   # и история не выросла


def test_llm_garbage_answer_is_503(_client, monkeypatch):
    """Молчит/несёт чушь → 503 с текстом, а не «успех» с пустым текстом."""
    n = _note("что то там про маршруты и кофе")
    _mock_llm(monkeypatch, "просто текст вообще без json")
    r = _client.post(_polish_url(n.id), json={"mode": "rewrite"})
    assert r.status_code == 503, r.text
    assert "пустой ответ" in r.json()["detail"]
    assert _get_note(n.id).text == n.text


def test_bad_mode_and_missing_note(_client, monkeypatch):
    _mock_llm(monkeypatch, '{"text": "ок"}')
    n = _note("заметка")
    assert _client.post(_polish_url(n.id), json={"mode": "poetry"}).status_code == 400
    assert _client.post(_polish_url(999999), json={"mode": "rewrite"}).status_code == 404
    assert _client.get("/api/mind/notes/999999/revisions").status_code == 404
    assert _client.post("/api/mind/notes/999999/apply", json={"text": "x"}).status_code == 404
    assert _client.post("/api/mind/notes/999999/revert", json={}).status_code == 404


def test_revert_without_history_is_honest(_client):
    n = _note("просто заметка без правок")
    r = _client.post(f"/api/mind/notes/{n.id}/revert", json={})
    assert r.status_code == 400, r.text
    assert "Истории" in r.json()["detail"]
    assert _get_note(n.id).text == n.text


# ---------------- конкретная версия + ручная правка ----------------
def test_revert_to_specific_revision(_client, monkeypatch):
    n = _note("версия первая")
    _mock_llm(monkeypatch, '{"text": "версия вторая"}')
    d = _client.post(_polish_url(n.id), json={"mode": "rewrite"}).json()
    assert _client.post(f"/api/mind/notes/{n.id}/apply", json={"text": d["polished"]}).status_code == 200
    assert _client.post(f"/api/mind/notes/{n.id}/apply", json={"text": "версия третья"}).status_code == 200

    revs = _client.get(f"/api/mind/notes/{n.id}/revisions").json()
    assert [v["text"] for v in revs] == ["версия первая", "версия вторая", "версия третья"]

    r = _client.post(f"/api/mind/notes/{n.id}/revert", json={"revision_id": revs[0]["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["text"] == "версия первая"
    assert _get_note(n.id).text == "версия первая"

    # несуществующая версия — честный отказ, текст не меняется
    bad = _client.post(f"/api/mind/notes/{n.id}/revert", json={"revision_id": 999999})
    assert bad.status_code == 400
    assert _get_note(n.id).text == "версия первая"


def test_manual_edit_also_goes_to_history(_client):
    """Ручное редактирование (PUT /api/notes) тоже попадает в историю — иначе правка теряется."""
    n = _note("до правки")
    r = _client.put(f"/api/notes/{n.id}", json={"text": "после правки"})
    assert r.status_code == 200, r.text
    items = _client.get(f"/api/mind/notes/{n.id}/revisions").json()
    assert [v["text"] for v in items] == ["до правки", "после правки"]
    assert items[0]["current"] is False and items[-1]["current"] is True


def test_deleted_note_takes_history_with_it(_client):
    """id в SQLite может достаться новой заметке — старую историю уносим вместе с удалённой."""
    from core.services import polish
    n = _note("то что удалят")
    _client.put(f"/api/notes/{n.id}", json={"text": "правка перед удалением"})
    assert polish.list_revisions(n.id)
    assert _client.delete(f"/api/notes/{n.id}").status_code == 200
    assert polish.list_revisions(n.id) == []
    assert _client.get(f"/api/mind/notes/{n.id}/revisions").status_code == 404


# ---------------- доступ ----------------
def test_remote_without_key_gets_401(fresh_db):
    """Новые маршруты закрыты той же AuthMiddleware, что и соседние /api/notes."""
    from fastapi.testclient import TestClient
    from core.api.app import app

    c = TestClient(app, client=("192.168.1.50", 5555), base_url="http://testserver")
    assert c.get("/api/mind/notes/1/revisions").status_code == 401
    assert c.post("/api/mind/notes/1/polish", json={"mode": "rewrite"}).status_code == 401
    assert c.post("/api/mind/notes/1/apply", json={"text": "x"}).status_code == 401
    assert c.post("/api/mind/notes/1/revert", json={}).status_code == 401
