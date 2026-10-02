"""Чат: подтверждение предложенного факта (тост «Запомнить?») и вшивание `suggest_fact` в ответы чата.

Почему отдельный роутер:
- `POST /api/chat` живёт в `core/api/routers/mind.py`, `POST /api/chat/stream` — в `core/api/app.py`;
  оба файла чужие (их ведут другие агенты), поэтому сами роуты не трогаем. Ключ `suggest_fact`
  дописывается в их ответ уже ПОСЛЕ генерации — ASGI-обёрткой `SuggestInjector` (см. ниже);
- сюда же вынесены `POST /api/memory/confirm` («да» — подтвердить факт) и `POST /api/memory/dismiss`
  («нет» — убрать и больше не предлагать): в mind.py для них нет места, а создавать дубль роута нельзя.

Подключение: `routers/__init__.py` → `chat.register(app)` ДО `system.register(app)`, иначе catch-all
SPA из app.py перехватит `/api/memory/*` (см. инварианты в `routers/__init__.py`).
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ...services import memory

router = APIRouter()


def register(app) -> None:
    app.include_router(router)
    # Наружу остальных middleware — чтобы видеть уже готовый ответ роутов mind.py/app.py.
    # Авторизация и лимиты при этом работают как раньше: они просто оборачивают приложение глубже.
    app.add_middleware(SuggestInjector)


# ---------------- предложенный факт: «да» / «нет» ----------------
class SuggestIn(BaseModel):
    text: str = ""
    category: Optional[str] = None
    fact_id: Optional[int] = None


@router.post("/api/memory/confirm")
async def memory_confirm(p: SuggestIn):
    """«Да, запомни»: факт подтверждается (confirmed_at) — он больше не затухает и не архивируется по decay_days.

    `async def` + `asyncio.to_thread`: SQLite-пишем — блокирующий вызов. Раньше обработчик был sync,
    и FastAPI уводил такой в пул потоков сам; помечено явно, чтобы при возврате к sync-подписи
    (или при вызове из другого обработчика) БД не встала в event loop и не подвесила стрим."""
    f = await asyncio.to_thread(memory.confirm, p.fact_id, p.text, p.category)
    if not f:
        raise HTTPException(400, "Нечего подтверждать: пустой текст и нет fact_id")
    return {"ok": True, "fact": f.model_dump(exclude={"vector"})}


@router.post("/api/memory/dismiss")
async def memory_dismiss(p: SuggestIn):
    """«Нет»: предложенный факт уходит в архив, а сама фраза запоминается как отклонённая — больше не предложим."""
    ok = await asyncio.to_thread(memory.dismiss, p.fact_id, p.text)
    return {"ok": ok}


# ---------------- вшивание suggest_fact в ответы чата ----------------
def _patch_json(msgs: list[dict]) -> list[dict]:
    """Добавить suggest_fact в JSON-ответ /api/chat. Меняем тело только если это наш (200, JSON, есть «text»)."""
    start = next((m for m in msgs if m.get("type") == "http.response.start"), None)
    if not start or start.get("status") != 200:
        return msgs
    headers = dict(start.get("headers") or [])
    if b"application/json" not in headers.get(b"content-type", b""):
        return msgs
    body = b"".join(m.get("body", b"") for m in msgs if m.get("type") == "http.response.body")
    try:
        data = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return msgs
    if not isinstance(data, dict) or "text" not in data or "suggest_fact" in data:
        return msgs
    data["suggest_fact"] = memory.pop_suggest() or None
    new = json.dumps(data, ensure_ascii=False).encode("utf-8")
    out: list[dict] = []
    for m in msgs:
        if m.get("type") == "http.response.start":
            hs = [(k, str(len(new)).encode() if k == b"content-length" else v) for k, v in (m.get("headers") or [])]
            if not any(k == b"content-length" for k, _ in hs):
                hs.append((b"content-length", str(len(new)).encode()))
            out.append({**m, "headers": hs})
        elif m.get("type") == "http.response.body":
            continue                      # старое тело заменяем одним сообщением ниже
        else:
            out.append(m)
    out.append({"type": "http.response.body", "body": new, "more_body": False})
    return out


# как часто шлём SSE-комментарий, пока ответа нет (сек). Меньше 10 — прокси успевают закрыть idle-соединение.
_SSE_PING_SEC = 5.0


def _patch_sse(chunk: bytes) -> bytes | None:
    """Добавить suggest_fact в финальное событие `done` потока /api/chat/stream. None — не наш кусок."""
    try:
        s = chunk.decode("utf-8")
    except UnicodeDecodeError:
        return None
    head = "event: done\ndata: "
    if not s.startswith(head):
        return None                      # события отдаются по одному (yield на каждое), ищем только начало куска
    rest = s[len(head):]
    end = rest.find("\n\n")
    payload, tail = (rest[:end], rest[end:]) if end >= 0 else (rest, "")
    try:
        data = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(data, dict) or "text" not in data or "suggest_fact" in data:
        return None
    data["suggest_fact"] = memory.pop_suggest() or None
    return (head + json.dumps(data, ensure_ascii=False) + tail).encode("utf-8")


class SuggestInjector:
    """ASGI-обёртка только для POST /api/chat и /api/chat/stream: дописывает `suggest_fact` в ответ.

    Предложение (если оно есть) кладёт в общий слот `memory.set_suggest()` сам агент (agent.handle очищает
    слот в начале хода), а отсюда забирает — иначе пришлось бы лезть в чужие роуты.
    Запрос не трогаем вообще: тело читают сами роуты, тут меняется только ответ."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http" or scope.get("method") != "POST" or scope.get("path") not in ("/api/chat", "/api/chat/stream"):
            await self.app(scope, receive, send)
            return
        if scope["path"] == "/api/chat/stream":
            # «дыхание», пока первый токен ещё не пришёл: без него прокси/браузер рвут соединение
            # на ожидании (первый ответ локальной модели — 5–25 с, модель ещё в видеопамяти грузится).
            # Комментарий SSE сервер и клиент игнорируют, соединение и таймеры не трогают.
            async def heartbeat() -> None:
                try:
                    while True:
                        await asyncio.sleep(_SSE_PING_SEC)
                        await send({"type": "http.response.body", "body": b": ping\n\n", "more_body": True})
                except asyncio.CancelledError:
                    raise

            async def wrap(m):
                if m.get("type") == "http.response.body" and m.get("body"):
                    patched = _patch_sse(m["body"])
                    if patched is not None:
                        m = {**m, "body": patched}
                await send(m)
            ping = asyncio.create_task(heartbeat())
            try:
                await self.app(scope, receive, wrap)
            finally:
                ping.cancel()
            return
        captured: list[dict] = []

        async def capture(m):
            captured.append(m)

        await self.app(scope, receive, capture)   # JSON-ответ небольшой и не потоковый — собираем и отдаём разом
        for m in _patch_json(captured):
            await send(m)
