# -*- coding: utf-8 -*-
"""Мост «запись Мозга → факт Памяти» (кнопка «Запомнить») + ?q у фактов.

Правило: фикстуры fresh_db/_client из tests/conftest.py параметром,
писать в боевую data/jarvis.db запрещено.
"""
from __future__ import annotations


def _facts(client):
    return client.get("/api/facts").json()["items"]


# ---------------------------------------------------------------- 1. note → fact
def test_remember_note_creates_fact(_client):
    nid = _client.post("/api/notes", json={"text": "Люблю кататься на велосипеде по утрам"}).json()["id"]
    r = _client.post(f"/api/notes/{nid}/remember")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "велосипеде" in body["text"], body
    assert body["source_ref"] == f"note:{nid}", body
    assert body["source"] == "мозг", body
    assert body["layer"] != "archive"
    assert any(f["id"] == body["id"] for f in _facts(_client)), "факт не виден в GET /api/facts"


def test_remember_note_dedup(_client):
    nid = _client.post("/api/notes", json={"text": "Собираю виниловые пластинки с джазом"}).json()["id"]
    first = _client.post(f"/api/notes/{nid}/remember").json()
    second = _client.post(f"/api/notes/{nid}/remember").json()
    assert second["id"] == first["id"], "повторный вызов создал дубль"
    mine = [f for f in _facts(_client) if f.get("source_ref") == f"note:{nid}"]
    assert len(mine) == 1, f"дубли факта: {mine}"


# ---------------------------------------------------------------- 2. link → fact
def test_remember_link_creates_fact(_client):
    lid = _client.post("/api/links", json={"url": "https://example.com/statya-pro-son",
                                           "comment": "Статья про здоровый сон"}).json()["id"]
    r = _client.post(f"/api/links/{lid}/remember")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "example.com" in body["text"] or "сон" in body["text"], body
    assert body["source_ref"] == f"link:{lid}", body
    assert body["source"] == "мозг", body


def test_remember_link_dedup(_client):
    lid = _client.post("/api/links", json={"url": "https://example.com/retsepty-pitstsy",
                                           "comment": "Рецепты пиццы"}).json()["id"]
    first = _client.post(f"/api/links/{lid}/remember").json()
    second = _client.post(f"/api/links/{lid}/remember").json()
    assert second["id"] == first["id"], "повторный вызов создал дубль"
    mine = [f for f in _facts(_client) if f.get("source_ref") == f"link:{lid}"]
    assert len(mine) == 1, f"дубли факта: {mine}"


# ---------------------------------------------------------------- 3. 404
def test_remember_missing_returns_404(_client):
    assert _client.post("/api/notes/99999/remember").status_code == 404
    assert _client.post("/api/links/99999/remember").status_code == 404


# ---------------------------------------------------------------- 4. ?q у фактов
def test_facts_search_q(_client):
    _client.post("/api/facts", json={"text": "Обожает утренние велопрогулки", "layer": "long"})
    _client.post("/api/facts", json={"text": "Коллекционирует марки", "layer": "long"})
    r = _client.get("/api/facts", params={"q": "велопрогулки"})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert items, "поиск ничего не нашёл"
    assert all("велопрогулки" in f["text"].lower() for f in items), items
    assert len(items) == 1, items
