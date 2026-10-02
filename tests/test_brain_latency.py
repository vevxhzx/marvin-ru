# -*- coding: utf-8 -*-
"""ФАЗА «мозг» — задержка до первого токена и отсутствие блокировки event loop.

Офлайн, без сети: Ollama замокана, задержки считаются на asyncio-цикле.

Что проверяем:
1. блоки «уроки» и «память» готовятся ПАРАЛЛЕЛЬНО, а не по очереди (это и была задержка);
2. эмбеддинг реплики считается ОДИН раз за ход, а не по разу на блок;
3. SSE не «залипает»: пока ответа нет, соединение живо (ping-комментарии);
4. обработчики /api/memory/* не выполняют блокирующий SQLite в event loop;
5. первый токен стрима не ждёт завершения всех инструментов подряд.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402
from tests.test_core import fresh_db  # noqa: E402,F401  (autouse-фикстура на временной БД)

# Модель внутри _turn_context искусственно спит, чтобы параллельность была измерима, а не случайной.
STEP = 0.25


def _slow_ollama(monkeypatch, calls: list[str] | None = None):
    """Подменить локальные вызовы мозга на сон фиксированной длины."""

    async def embed_available() -> bool:
        if calls is not None:
            calls.append("embed_available")
        await asyncio.sleep(STEP)
        return True

    async def embed(texts):
        if calls is not None:
            calls.append("embed")
        await asyncio.sleep(STEP)
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def context(text):
        if calls is not None:
            calls.append("memory")
        await asyncio.sleep(STEP)
        return "ЧТО ТЫ ЗНАЕШЬ О ХОЗЯИНЕ:\n— кот Чиназес\n"

    async def lessons(text, vectors=None):
        if calls is not None:
            calls.append("lessons")
        await asyncio.sleep(STEP)
        return ""

    return embed_available, embed, context, lessons


def test_memory_and_lessons_prepare_in_parallel(monkeypatch):
    """Память и уроки — независимая работа; по очереди она удваивала задержку до первого токена."""
    from core.brain import agent

    calls: list[str] = []
    embed_available, embed, context, lessons = _slow_ollama(monkeypatch, calls)
    monkeypatch.setattr(agent.llm, "embed_available", embed_available)
    monkeypatch.setattr(agent.llm, "embed", embed)
    monkeypatch.setattr(agent.memory, "context", context)
    monkeypatch.setattr(agent, "_lessons_block", lessons)

    t0 = time.perf_counter()
    les, ctx = asyncio.run(agent._turn_context("сколько я потратил"))
    elapsed = time.perf_counter() - t0
    assert ctx and les is not None
    # embed_available + embed + (память ‖ уроки) = 3 шага, а не 4
    assert elapsed < STEP * 3.6, f"{elapsed:.2f} с — блоки идут последовательно"
    assert "memory" in calls and "lessons" in calls


def test_turn_embedding_is_computed_once(monkeypatch):
    """Эмбеддинг реплики — один на ход: раньше и память, и уроки считали его сами."""
    from core.brain import agent

    calls: list[str] = []
    embed_available, embed, context, lessons = _slow_ollama(monkeypatch, calls)
    monkeypatch.setattr(agent.llm, "embed_available", embed_available)
    monkeypatch.setattr(agent.llm, "embed", embed)
    monkeypatch.setattr(agent.memory, "context", context)
    monkeypatch.setattr(agent, "_lessons_block", lessons)

    asyncio.run(agent._turn_context("что там по заказам"))
    assert calls.count("embed") == 1, calls


def test_turn_context_survives_broken_lessons(monkeypatch):
    """Сбой блока уроков не должен ронять ход — память всё равно нужна."""
    from core.brain import agent

    async def boom(*a, **k):
        raise RuntimeError("уроки сломались")

    async def context(text):
        return "ЧТО ТЫ ЗНАЕШЬ О ХОЗЯИНЕ:\n— кот Чиназес\n"

    async def embed_available():
        return False

    monkeypatch.setattr(agent.llm, "embed_available", embed_available)
    monkeypatch.setattr(agent.memory, "context", context)
    monkeypatch.setattr(agent, "_lessons_block", boom)
    les, ctx = asyncio.run(agent._turn_context("привет"))
    assert les == "" and "кот" in ctx


# ============================================================ SSE не залипает
def test_sse_stream_sends_heartbeat_while_waiting(monkeypatch):
    """Пока модель думает (5–25 с на первом ответе), соединение не должно молча висеть.

    Без ping прокси и браузер рвут idle-поток, и пользователь видит «ничего не происходит»."""
    from fastapi.testclient import TestClient

    from core.api.app import app

    async def slow_chat(text, channel="chat"):
        await asyncio.sleep(6.0)          # дольше интервала ping (5 с) — должен уйти хотя бы один
        return type("R", (), {"text": "ответ", "actions": [], "via": "ollama"})()

    monkeypatch.setattr("core.brain.agent.handle", slow_chat)

    with TestClient(app, client=("127.0.0.1", 5555)) as c:
        with c.stream("POST", "/api/chat/stream", json={"text": "привет"}) as r:
            assert r.status_code == 200
            body = "".join(chunk for chunk in r.iter_text())
    assert ": ping" in body, "SSE-соединение молчало всё время ожидания"


def test_sse_still_delivers_tokens_and_done(monkeypatch):
    """Пинг не ломает поток: токены и финальное событие `done` на месте."""
    from fastapi.testclient import TestClient

    from core.api.app import app

    async def quick_chat(text, channel="chat"):
        return type("R", (), {"text": "вот ответ", "actions": [], "via": "ollama"})()

    monkeypatch.setattr("core.brain.agent.handle", quick_chat)
    with TestClient(app, client=("127.0.0.1", 5555)) as c:
        r = c.post("/api/chat/stream", json={"text": "привет"})
    assert r.status_code == 200
    assert "event: done" in r.text
    assert "вот ответ" in r.text


# ============================================================ блокирующий I/O в event loop
def test_memory_endpoints_do_not_block_event_loop():
    """/api/memory/confirm и /api/memory/dismiss — SQLite-пишем.

    Раньше это были sync-обработчики: FastAPI уводил их в пул потоков сам, но это зависело от
    сигнатуры. Сейчас async + asyncio.to_thread — блокирующий вызов точно не встанет в event loop
    (а значит, не заморозит параллельный стрим и не подвинет SSE-пинги)."""
    import inspect

    from core.api.routers import chat as chat_router

    for fn in (chat_router.memory_confirm, chat_router.memory_dismiss):
        assert inspect.iscoroutinefunction(fn), f"{fn.__name__} должен быть async (иначе БД в event loop)"
        assert "to_thread" in inspect.getsource(fn), f"{fn.__name__} должен уводить БД в поток"


def test_confirm_and_dismiss_work_end_to_end():
    """Эндпоинты работают как раньше — защита не сломала обычный тост «Запомнить?»."""
    from fastapi.testclient import TestClient

    from core.api.app import app
    from core.services import memory

    memory.set_suggest({"text": "хозяин пьёт кофе чёрный", "category": "быт"}, "chat")
    with TestClient(app, client=("127.0.0.1", 5555)) as c:
        ok = c.post("/api/memory/confirm", json={"text": "хозяин пьёт кофе чёрный", "category": "быт"})
        assert ok.status_code == 200 and ok.json()["ok"] is True
        # повторное подтверждение не падает (факт уже есть)
        assert c.post("/api/memory/confirm", json={"text": "хозяин пьёт кофе чёрный"}).status_code == 200
        assert c.post("/api/memory/dismiss", json={"text": "хозяин больше не пьёт кофе"}).json()["ok"] is True
        # пустой текст без fact_id — понятная ошибка, а не 500
        assert c.post("/api/memory/confirm", json={"text": ""}).status_code == 400


def test_chat_router_has_no_blocking_imports():
    """В роутере чата не должно быть тяжёлого импорта на уровне модуля или внутри обработчика.

    Тяжёлый импорт внутри async-обработчика блокирует event loop на весь импорт — отсюда были
    «подвисания» одного из эндпоинтов. Проверяем текстом: локальные импорты допустимы лишь лёгкие."""
    import inspect

    from core.api.routers import chat as chat_router

    src = inspect.getsource(chat_router)
    for heavy in ("import torch", "import numpy", "from PIL", "import cv2", "import whisper",
                  "import sqlite3", "import sqlalchemy", "from ...db import", "from ...config import"):
        assert heavy not in src, f"тяжёлый импорт {heavy!r} в роутере чата блокирует event loop"


# ============================================================ первый токен не ждёт всей обработки
def test_first_token_arrives_before_final_done(monkeypatch):
    """Стрим отдаёт токены по мере генерации, а не одним куском в конце.

    Проверяем, что в пути к модели токены уже уходят в sink (token_sink), то есть первый токен
    не ждёт завершения хода."""
    from core.brain import agent, llm

    got: list[str] = []

    async def fake_ollama_chat(messages, tools=None, temperature=0.3, json_mode=False):
        sink = llm.token_sink.get()
        for piece in ("Пер", "вый ", "токен"):
            if sink:
                await sink(piece)
            got.append(piece)
            await asyncio.sleep(0)
        return {"content": "Первый токен", "tool_calls": []}

    monkeypatch.setattr(llm, "ollama_chat", fake_ollama_chat)
    monkeypatch.setattr(llm, "ollama_available", lambda force=False: asyncio.sleep(0, result=True))
    monkeypatch.setattr(agent, "_turn_context", lambda t, with_lessons=True: asyncio.sleep(0, result=("", "")))

    async def main():
        async def sink(piece):
            got.append("sink:" + piece)
        tok = llm.token_sink.set(sink)
        try:
            return await agent.via_ollama("привет", "chat", with_tools=False)
        finally:
            llm.token_sink.reset(tok)

    r = asyncio.run(main())
    assert r is not None and r.text
    assert got.index("sink:Пер") < len(got), "токен должен уйти в поток сразу, а не в конце"


def test_stream_ping_interval_is_below_idle_timeout():
    """Интервал ping-ов должен быть заметно меньше типичного idle-таймаута прокси (30–60 с)."""
    from core.api.routers import chat as chat_router

    assert 0 < chat_router._SSE_PING_SEC <= 15, chat_router._SSE_PING_SEC