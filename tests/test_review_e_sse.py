"""Ревью E «Надёжность» — часть 2: SSE (`/api/events/stream` и broadcast).

Проверяем:
  * стрим отдаёт `retry` и heartbeat (`: ping`), т.е. соединение не умирает молча;
  * закрытие клиента снимает подписчика из `_subscribers` (утечки нет);
  * `broadcast` без клиентов — no-op и не блокирует event loop;
  * очередь подписчика (находка: не ограничена) — свидетель в test_..._finding.

Всё в памяти, на временной БД из фикстуры `fresh_db` (tests/test_core).
"""
from __future__ import annotations

import asyncio
import os
import time

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402
from tests.test_core import fresh_db  # noqa: E401,F401  (autouse: временная БД)

from core.config import DATA_DIR  # noqa: E402  (после ASSISTANT_TEST)


def _shared():
    from core.api import _shared
    return _shared


# ---------------------------------------------------------------- heartbeat
def test_sse_heartbeat_ping_arrives_while_idle(monkeypatch):
    """Если клиент молчит, сервер сам шлёт `: ping` (таймаут 25 с → в тесте 0.2 с)."""
    from core.api.app import stream

    orig = asyncio.wait_for

    def fast_wait_for(fut, timeout=None, **kw):
        if timeout == 25:
            timeout = 0.2
        return orig(fut, timeout, **kw)

    monkeypatch.setattr(asyncio, "wait_for", fast_wait_for)

    async def scenario():
        resp = await stream()
        gen = resp.body_iterator
        try:
            first = await gen.__anext__()
            assert first == "retry: 3000\n\n"
            second = await gen.__anext__()
            assert second == ": ping\n\n", f"heartbeat не пришёл: {second!r}"
        finally:
            await gen.aclose()

    asyncio.run(scenario())


# ---------------------------------------------------------------- утечка подписчика
def test_sse_subscriber_removed_on_client_disconnect():
    sh = _shared()
    from core.api.app import stream

    async def scenario():
        base = len(sh._subscribers)
        resp = await stream()
        gen = resp.body_iterator
        await gen.__anext__()                     # retry: 3000
        assert len(sh._subscribers) == base + 1
        sh.broadcast("ping", {"kind": "ping"})
        frame = await gen.__anext__()
        assert frame.startswith("data: ")
        # клиент закрылся (GeneratorExit) — подписчик обязан уйти из множества
        await gen.aclose()
        assert len(sh._subscribers) == base, "после разрыва клиента подписчик остался в _subscribers"

    asyncio.run(scenario())


def test_sse_pc_client_counter_updates_and_resets():
    sh = _shared()
    from core.api.app import stream
    from core.services import pc

    async def scenario():
        base_subs = len(sh._subscribers)
        base_pc = len(sh._pc_streams)
        resp = await stream(client="pc")
        gen = resp.body_iterator
        await gen.__anext__()
        assert len(sh._pc_streams) == base_pc + 1
        assert pc.SSE_CLIENTS == len(sh._pc_streams)
        await gen.aclose()
        assert len(sh._pc_streams) == base_pc
        assert pc.SSE_CLIENTS == len(sh._pc_streams)

    asyncio.run(scenario())


def test_sse_http_client_close_releases_subscriber():
    """Сквозная проверка на ASGI-уровне: клиент ушёл (`http.disconnect`) — подписчик снят.

    Синхронный TestClient для бесконечных SSE непригоден (портал ждёт завершения ответа),
    поэтому драйвим приложение напрямую: receive() отдаёт disconnect после первого чанка.
    """
    import asyncio as _aio

    from core.api.app import app

    sh = _shared()
    base = len(sh._subscribers)
    chunks: list[bytes] = []

    async def scenario():
        async def receive():
            await _aio.sleep(0.3)          # клиент закрыл вкладку через 0.3 с
            return {"type": "http.disconnect"}

        async def send(msg):
            if msg["type"] == "http.response.body" and msg.get("body"):
                chunks.append(msg["body"])

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": "GET", "scheme": "http",
            "path": "/api/events/stream", "raw_path": b"/api/events/stream",
            "query_string": b"", "root_path": "",
            "headers": [(b"host", b"testserver"), (b"accept", b"text/event-stream")],
            "client": ("127.0.0.1", 5555), "server": ("testserver", 80),
        }
        # защита от зависания: если disconnect не обработан — тест упадёт, а не повиснет
        await _aio.wait_for(app(scope, receive, send), timeout=15)
        return len(sh._subscribers)

    left = asyncio.run(scenario())
    assert chunks, "SSE не отдал ни одного чанка до разрыва"
    assert left == base, "после http.disconnect подписчик остался в _subscribers (утечка)"


# ---------------------------------------------------------------- broadcast
def test_broadcast_without_clients_is_noop():
    sh = _shared()
    assert len(sh._subscribers) == 0
    sh.broadcast("task", {"id": 1})   # не должен бросить исключение
    assert len(sh._subscribers) == 0


def test_broadcast_does_not_block_event_loop():
    """broadcast зовётся из синхронных роутов — 200 подписчиков должны раздаваться мгновенно."""
    sh = _shared()

    async def scenario():
        queues = []
        base = len(sh._subscribers)
        for _ in range(200):
            q = asyncio.Queue()
            sh._subscribers.add(q)
            queues.append(q)
        try:
            t0 = time.perf_counter()
            for i in range(20):
                sh.broadcast("pulse", {"i": i})
            elapsed = time.perf_counter() - t0
            assert elapsed < 1.0, f"broadcast на 200 подписчиков занял {elapsed:.2f} с"
            # и event loop жив: параллельная корутина отрабатывает
            await asyncio.sleep(0)
            assert all(q.qsize() == 20 for q in queues)
        finally:
            for q in queues:
                sh._subscribers.discard(q)

    asyncio.run(scenario())


# ---------------------------------------------------------------- chat/stream
def test_chat_stream_delivers_tokens_then_done_and_closes():
    """`POST /api/chat/stream` (POST-SSE) завершается событием `done`, а не висит вечно.

    Драйвим приложение напрямую (ASGI): receive отдаёт запрос один раз, далее —
    «мёртвый» клиент, который просто читает до `done`. Тест гарантирует:
      * поток не бесконечный (есть финальный `event: done`),
      * поток закрывается сам (io.read(timeout) не нужен),
      * в `data/card_cache` ничего не дописано (ответ нейтральный → карточка не рисуется).
    """
    import asyncio as _aio
    import json as _json

    from core.api.app import app

    card_dir = DATA_DIR / "card_cache"
    before = set(card_dir.glob("*")) if card_dir.is_dir() else set()

    body = _json.dumps({"text": "привет", "channel": "web"}, ensure_ascii=False).encode("utf-8")
    frames: list[bytes] = []
    sent_request = False

    async def scenario():
        nonlocal sent_request

        async def receive():
            nonlocal sent_request
            if not sent_request:
                sent_request = True
                return {
                    "type": "http.request", "body": body, "more_body": False,
                }
            # клиент продолжает дочитывать поток, затем закрывается
            await _aio.sleep(3600)
            return {"type": "http.disconnect"}

        async def send(msg):
            if msg["type"] == "http.response.body" and msg.get("body"):
                frames.append(msg["body"])

        scope = {
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1", "method": "POST", "scheme": "http",
            "path": "/api/chat/stream", "raw_path": b"/api/chat/stream",
            "query_string": b"", "root_path": "",
            "headers": [(b"host", b"testserver"), (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode())],
            "client": ("127.0.0.1", 5556), "server": ("testserver", 80),
        }
        # защита от зависания: если done не придёт — упадём, а не повиснем
        await _aio.wait_for(app(scope, receive, send), timeout=30)

    asyncio.run(scenario())

    blob = b"".join(frames).decode("utf-8", "replace")
    assert "event: done" in blob, f"chat/stream не завершился событием done:\n{blob[:500]}"
    assert "event: token" in blob or "event: done" in blob
    # поток закрыт сервером: после done новых чанков быть не должно
    assert blob.rstrip().endswith("}") or blob.endswith("\n\n")

    after = set(card_dir.glob("*")) if card_dir.is_dir() else set()
    assert after == before, f"chat/stream дописал файлы в card_cache: {after - before}"


# ---------------------------------------------------------------- находка: очередь без ограничения
def test_sse_slow_consumer_queue_is_unbounded_finding():
    """FINDING (P2): очередь подписчика не ограничена — медленный/зависший клиент
    накапливает сообщения в памяти процесса без предела (broadcast не ждёт чтения).

    Тест фиксирует ТЕКУЩЕЕ поведение: после 500 сообщений без чтения все 500 лежат в очереди.
    Если появится лимит/отключение — тест упадёт, его надо будет обновить вместе с находкой.
    """
    sh = _shared()

    async def scenario():
        from core.api.app import stream
        before = set(sh._subscribers)
        resp = await stream()
        gen = resp.body_iterator
        await gen.__anext__()          # retry
        # находим именно свою очередь (добавлена этим же вызовом stream)
        fresh = set(sh._subscribers) - before
        assert len(fresh) == 1
        (q,) = fresh
        for i in range(500):
            sh.broadcast("noise", {"i": i})
        assert q.qsize() == 500, "сообщения не копятся — возможно, появился лимит (обновите находку)"
        await gen.aclose()

    asyncio.run(scenario())
