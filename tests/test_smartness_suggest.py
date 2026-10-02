# -*- coding: utf-8 -*-
"""Тост «Запомнить?»: suggest_fact в ответах /api/chat и /api/chat/stream,
эндпоинты confirm/dismiss, слот предложения, синхронное извлечение на сайте
и профиль стиля хозяина одной строкой в system prompt."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

os.environ["ASSISTANT_TEST"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import db  # noqa: E402
from core.brain import agent  # noqa: E402
from core.services import memory  # noqa: E402
from core.api.routers import chat as chat_router  # noqa: E402


def _offline(monkeypatch):
    """Ни Ollama, ни облака: чат отвечает правилами, нейронка не зовётся."""
    from core.brain import llm
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)

    async def no_ollama(force=False):
        return False
    monkeypatch.setattr(llm, "ollama_available", no_ollama)

    async def emb_avail():
        return False
    monkeypatch.setattr(llm, "embed_available", emb_avail)


def _done_json(text: str) -> dict:
    """Распарсить финальное событие `done` из SSE-тела /api/chat/stream."""
    payload = text.split("event: done\ndata: ", 1)[1].split("\n\n", 1)[0]
    return json.loads(payload)


# ------------------------------------------------------------------ слот предложения
def test_suggest_slot_roundtrip():
    """Слот живёт один ход: положили → забрали → пусто; просроченное и очищенное не вшиваем."""
    memory.clear_suggest()
    assert memory.pop_suggest() is None
    memory.set_suggest({"text": "пельмени люблю", "category": "быт"}, "web")
    assert memory.pop_suggest() == {"text": "пельмени люблю", "category": "быт"}
    assert memory.pop_suggest() is None                       # забрали — второй раз не отдаёт
    memory.set_suggest({"text": "пельмени люблю"}, "web")
    assert memory.pop_suggest(max_age=-1) is None             # слишком старое — мимо
    memory.set_suggest({"text": "пельмени люблю"}, "web")
    memory.clear_suggest()
    assert memory.pop_suggest() is None
    memory.set_suggest(None)                                  # не падает
    assert memory.pop_suggest() is None


def test_reply_has_suggest_field():
    r = agent.Reply("ok")
    assert r.suggest_fact is None
    r.suggest_fact = {"text": "пельмени люблю", "category": "быт", "fact_id": 1}
    assert r.suggest_fact["fact_id"] == 1


# ------------------------------------------------------------------ инжектор ответов
def test_patch_json_adds_suggest_fact():
    msgs = [
        {"type": "http.response.start", "status": 200,
         "headers": [(b"content-type", b"application/json"), (b"content-length", b"2")]},
        {"type": "http.response.body", "body": b'{"text": "ok"}'},
    ]
    memory.clear_suggest()
    out = chat_router._patch_json(msgs)
    body = b"".join(m["body"] for m in out if m["type"] == "http.response.body")
    assert json.loads(body) == {"text": "ok", "suggest_fact": None}

    memory.set_suggest({"text": "пельмени люблю", "category": "предпочтение"}, "web")
    out2 = chat_router._patch_json(msgs)
    body2 = b"".join(m["body"] for m in out2 if m["type"] == "http.response.body")
    data = json.loads(body2)
    assert data["suggest_fact"] == {"text": "пельмени люблю", "category": "предпочтение"}
    start = next(m for m in out2 if m["type"] == "http.response.start")
    assert int(dict(start["headers"])[b"content-length"]) == len(body2)   # длина пересчитана
    assert sum(m["type"] == "http.response.body" for m in out2) == 1      # старое тело заменено

    # не 200 / не JSON / уже с ключом — не трогаем
    err = [{"type": "http.response.start", "status": 500, "headers": []},
           {"type": "http.response.body", "body": b"boom"}]
    assert chat_router._patch_json(err) == err
    other = {"text": "ok", "suggest_fact": {"x": 1}}
    memory.set_suggest({"text": "пельмени"}, "web")
    keep = [{"type": "http.response.start", "status": 200, "headers": [(b"content-type", b"application/json")]},
            {"type": "http.response.body", "body": json.dumps(other).encode()}]
    assert json.loads(b"".join(m["body"] for m in chat_router._patch_json(keep)
                               if m["type"] == "http.response.body")) == other
    memory.clear_suggest()                                    # слот общий: не тащим в другие тесты


def test_patch_sse_adds_suggest_fact():
    done = b'event: done\ndata: {"text": "ok", "actions": []}\n\n'
    memory.clear_suggest()
    patched = json.loads(chat_router._patch_sse(done).decode("utf-8").split("data: ", 1)[1])
    assert patched["suggest_fact"] is None and patched["text"] == "ok"

    memory.set_suggest({"text": "пельмени люблю", "category": "предпочтение"}, "web")
    patched2 = json.loads(chat_router._patch_sse(done).decode("utf-8").split("data: ", 1)[1])
    assert patched2["suggest_fact"]["text"] == "пельмени люблю"

    # не наше событие / не JSON / без «text» — не трогаем
    assert chat_router._patch_sse(b'event: token\ndata: {"t": 1}\n\n') is None
    assert chat_router._patch_sse(b'event: done\ndata: {"actions": []}\n\n') is None
    assert chat_router._patch_sse("event: done\ndata: не json\n\n".encode()) is None


# ------------------------------------------------------------------ HTTP: /api/chat
def test_chat_json_carries_suggest_fact(_client, monkeypatch):
    """Ответ /api/chat всегда содержит ключ suggest_fact (null, если предлагать нечего)."""
    _offline(monkeypatch)
    memory.clear_suggest()
    r = _client.post("/api/chat", json={"text": "что ты обо мне знаешь?", "channel": "web"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert "text" in data and "suggest_fact" in data
    assert data["suggest_fact"] is None
    assert data["via"] == "rules"

    # агент положил предложение в слот → инжектор вшивает его в JSON
    async def fake_handle(text, channel="tg"):
        memory.clear_suggest()
        memory.set_suggest({"text": "пельмени люблю", "category": "предпочтение", "fact_id": 7}, channel)
        return agent.Reply("Записал, сэр.", [], "rules")
    monkeypatch.setattr(agent, "handle", fake_handle)
    r2 = _client.post("/api/chat", json={"text": "привет", "channel": "web"})
    assert r2.status_code == 200
    assert r2.json()["suggest_fact"] == {"text": "пельмени люблю", "category": "предпочтение", "fact_id": 7}


def test_chat_stream_done_carries_suggest_fact(_client, monkeypatch):
    """Финальное SSE-событие `done` тоже содержит suggest_fact."""
    _offline(monkeypatch)
    memory.clear_suggest()
    r = _client.post("/api/chat/stream", json={"text": "что ты обо мне знаешь?", "channel": "web"})
    assert r.status_code == 200, r.text
    done = _done_json(r.text)
    assert "text" in done and done["suggest_fact"] is None

    async def fake_handle(text, channel="tg"):
        memory.clear_suggest()
        memory.set_suggest({"text": "пельмени люблю", "category": "предпочтение", "fact_id": 7}, channel)
        return agent.Reply("Записал, сэр.", [], "rules")
    monkeypatch.setattr(agent, "handle", fake_handle)
    r2 = _client.post("/api/chat/stream", json={"text": "привет", "channel": "web"})
    assert _done_json(r2.text)["suggest_fact"]["fact_id"] == 7


# ------------------------------------------------------------------ HTTP: confirm / dismiss
def test_confirm_dismiss_endpoints(_client, monkeypatch):
    _offline(monkeypatch)
    r = _client.post("/api/memory/confirm", json={"text": "пельмени люблю с мясом", "category": "предпочтение"})
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True
    fact = r.json()["fact"]
    assert fact["text"] == "пельмени люблю с мясом" and "vector" not in fact
    assert memory.fact_meta({fact["id"]})[fact["id"]]["confirmed"] is not None
    assert _client.post("/api/memory/confirm", json={}).status_code == 400

    ok = _client.post("/api/memory/dismiss", json={"text": "пельмени люблю с мясом"})
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert memory.find_fact("пельмени люблю с мясом") is None
    assert memory.find_fact("пельмени люблю с мясом", include_archived=True) is not None
    # повторное «да» возвращает в память
    again = _client.post("/api/memory/confirm", json={"text": "пельмени люблю с мясом"})
    assert again.status_code == 200
    assert memory.find_fact("пельмени люблю с мясом") is not None


# ------------------------------------------------------------------ извлечение после ответа
def test_memory_after_reply_web_sync(fresh_db, monkeypatch):
    """На сайте предложение собирается синхронно: первый факт → suggest_fact и в слот."""
    _offline(monkeypatch)
    f = memory.add_fact_sync("пельмени люблю с мясом", category="предпочтение")
    assert f is not None

    async def fake_extract(text, msg_id=None):
        return {"added": [f], "updated": [], "remind": None, "via": "cloud"}
    monkeypatch.setattr(memory, "extract", fake_extract)
    memory.clear_suggest()
    r = agent.Reply("ok")
    asyncio.run(agent._memory_after_reply("а пельмени я люблю с мясом очень", r, "web"))
    assert r.suggest_fact == {"text": f.text, "category": "предпочтение", "fact_id": f.id}
    assert memory.pop_suggest() == r.suggest_fact


def test_memory_after_reply_gates_and_fallback(fresh_db, monkeypatch):
    """Вопросы не извлекаем; не web / выключенные предложения / таймаут → фон, без suggest_fact."""
    _offline(monkeypatch)
    calls = []
    monkeypatch.setattr(agent, "_extract_memory_bg", lambda *a, **k: calls.append(a))
    memory.clear_suggest()

    r = agent.Reply("ok")
    asyncio.run(agent._memory_after_reply("сколько баланс?", r, "web"))     # вопрос — мимо
    assert calls == [] and r.suggest_fact is None

    asyncio.run(agent._memory_after_reply("а пельмени я люблю с мясом очень", agent.Reply("ok"), "tg"))
    assert len(calls) == 1                                                  # не web → фон

    monkeypatch.setattr(memory, "suggest_enabled", lambda: False)
    asyncio.run(agent._memory_after_reply("а пельмени я люблю с мясом очень", agent.Reply("ok"), "web"))
    assert len(calls) == 2                                                  # опция выключена → фон

    # не успели за таймаут → тоже фон, ответ не страдает
    async def slow_extract(text, msg_id=None):
        await asyncio.sleep(0.3)
        return {"added": [], "updated": [], "remind": None}
    monkeypatch.setattr(memory, "extract", slow_extract)
    monkeypatch.setattr(memory, "suggest_enabled", lambda: True)
    monkeypatch.setattr(memory, "suggest_timeout", lambda: 0.05)
    r2 = agent.Reply("ok")
    asyncio.run(agent._memory_after_reply("а пельмени я люблю с мясом очень", r2, "web"))
    assert len(calls) == 3 and r2.suggest_fact is None


# ------------------------------------------------------------------ профиль стиля
def test_style_line_is_single_line(fresh_db):
    assert memory.style_line() == ""                       # пусто — не мешаем системному промпту
    db.set_setting(memory.STYLE_KEY, "— пишет коротко\n— не любит восклицания\n— отвечает по-русски")
    line = memory.style_line()
    assert "\n" not in line and "·" in line
    assert line.startswith("пишет коротко") and "по-русски" in line
    assert len(line) <= memory.STYLE_LINE_MAX
    # длинный профиль обрезается по STYLE_LINE_MAX, но остаётся одной строкой
    db.set_setting(memory.STYLE_KEY, "\n".join(f"строка номер {i} довольно длинная такая" for i in range(50)))
    line2 = memory.style_line()
    assert "\n" not in line2 and len(line2) <= memory.STYLE_LINE_MAX


def test_system_prompt_carries_style_line(fresh_db):
    from core.brain import persona
    assert "СТИЛЬ ХОЗЯИНА" not in agent._system()         # без профиля — хвоста нет
    db.set_setting(memory.STYLE_KEY, "пишет коротко и с сухим юмором")
    for compact in (False, True):
        base = persona.system_prompt(compact=compact)
        s = agent._system(compact=compact)
        assert s.startswith(base)                          # системный промпт не переписан
        assert "СТИЛЬ ХОЗЯИНА" in s and "пишет коротко и с сухим юмором" in s
    # строка ровно одна — хвост добавляется один раз
    assert agent._system().count("СТИЛЬ ХОЗЯИНА") == 1


def test_context_style_and_system_line(fresh_db, monkeypatch):
    """Стиль остаётся в контексте (старый контракт tests/test_judge) и продублирован одной строкой
    в system prompt — там он постоянен и не зависит от реплики."""
    _offline(monkeypatch)
    db.set_setting(memory.STYLE_KEY, "СТИЛЬНЫЙМАРКЕР убирает по субботам")
    asyncio.run(memory.add_fact("кофе пью каждый день", category="привычка"))
    ctx = asyncio.run(memory.context("кофе люблю пить"))
    assert "кофе" in ctx
    assert "КАК ОН ПИШЕТ" in ctx and "СТИЛЬНЫЙМАРКЕР" in ctx
    assert "СТИЛЬ ХОЗЯИНА" in agent._system()
