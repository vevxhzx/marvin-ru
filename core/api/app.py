"""HTTP API ядра. Его используют: сайт (Этап 2) и голосовой клиент на ПК (Этап 3)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi.responses import JSONResponse, RedirectResponse
import asyncio
import logging
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlmodel import select

from ..brain import agent, persona
from ..config import ROOT
from ..db import session, Event, Task, Note, Link, Transaction, Debt, Recurring, Aim, Milestone, get_setting, set_setting
from ..services import brain_notes, calendar, finance, goals, insights, orders, pc, people, pulse, relations, tasks, screen
from ..services.scheduler import morning_digest_text
from .schemas import (  # ФАЗА 7 шаг 7.0: тела моделей вынесены в core/api/schemas.py, имена те же
   ChatIn, PcPing, PcAck, PcLaunch, PcResult, PcClip, VisionIn, CloudPreviewIn, RelationIn, EventIn,
   SkipIn, EventDoneIn, TaskIn, TaskPatch, AimIn, AimPatch, MilestoneIn, TxIn, TxPatch, CategoryIn,
   CategoryPatch, BalanceIn, AccountIn, AccountPatch, DebtIn, PayIn, DebtPatch, RecurringIn, RecurringPatch,
   ClientIn, OrderIn, OrderPatch, PaymentIn, TimerIn, ManualTimeIn, ScreenImportIn, PersonIn, PomoSettingsIn,
   FreelanceIn, GoalIn, GoalPatch, GoalPut, NoteIn, LinkIn, BoardIn, BoardPatch, BoardItemIn, BoardItemPatch,
   BoardBulk, BoardIds, BoardSync, NoteEdit, LinkEdit, FactIn, FactPatch, StyleIn, UiPrefsIn, EditionIn,
   SettingsIn, TgLogin, VoicePick, GameBody, BackupRestoreIn,
)

log = logging.getLogger("jarvis.api")

app = FastAPI(title="J.A.R.V.I.S. Core", version="0.1")
# CORS: сайт живёт на том же origin, что и API, — чужим сайтам доступ не нужен. Разрешаем только dev-сервер Vite.
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
# доступ с других устройств — только с токеном (см. core/api/auth.py); с самого ПК — свободно
from .auth import AuthMiddleware  # noqa: E402
app.add_middleware(AuthMiddleware)

# CRM (фаза 4) — отдельный роутер в core/crm/, подключается здесь; существующие пути не трогаются
from ..crm.router import router as _crm_router  # noqa: E402
app.include_router(_crm_router)


# ---------------- живые обновления (сайт узнаёт о действиях из Telegram/голоса мгновенно) ----------------
# ФАЗА 7 шаг 7.0: общее состояние роутов вынесено в core/api/_shared.py, здесь реэкспорт —
# core/crm/router.py и тесты импортируют `broadcast` из core.api.app, ломать нельзя.
import asyncio as _asyncio
import json as _json
from fastapi.responses import StreamingResponse

from ._shared import _ev_out, _pc_streams, _subscribers, broadcast  # noqa: F401  (реэкспорт)


agent.on_change = broadcast


@app.get("/api/events/stream")
async def stream(client: str = ""):
    """Живые события. `?client=pc` — так подключается voice.bat: по этим подключениям ядро знает, слушает ли кто-то ПК-команды."""
    from ..services import pc as _pc
    q: _asyncio.Queue = _asyncio.Queue()
    _subscribers.add(q)
    if client == "pc":
        _pc_streams.add(id(q)); _pc.SSE_CLIENTS = len(_pc_streams)

    async def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    msg = await _asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {msg}\n\n"
                except _asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            _subscribers.discard(q)
            if client == "pc":
                _pc_streams.discard(id(q)); _pc.SSE_CLIENTS = len(_pc_streams)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------- чат ----------------
def _card_for(r) -> str | None:
    """URL карточки-картинки для важного ответа (или None). Одна логика с Telegram — cards.for_result."""
    try:
        from pathlib import Path
        from ..services import cards
        p = cards.for_result(getattr(r, "actions", []) or [], getattr(r, "text", "") or "")
        if p and Path(p).exists():
            return f"/api/cards/{Path(p).name}"
    except Exception:
        pass
    return None


@app.post("/api/chat/stream")
async def chat_stream(inp: ChatIn):
    """Тот же чат, но ответ LLM приходит по словам (SSE): event token / done."""
    from ..brain import llm
    q: _asyncio.Queue = _asyncio.Queue()

    async def sink(piece: str):
        await q.put(("token", piece))

    async def run():
        token = llm.token_sink.set(sink)
        try:
            r = await agent.handle(inp.text, inp.channel)
            card = await _asyncio.to_thread(_card_for, r)
            await q.put(("done", {"text": r.text, "actions": r.actions, "via": r.via, "card": card}))
        except Exception as e:  # pragma: no cover
            await q.put(("done", {"text": f"Ошибка: {e}", "actions": [], "via": "none"}))
        finally:
            llm.token_sink.reset(token)

    async def gen():
        task = _asyncio.create_task(run())
        try:
            while True:
                kind, data = await q.get()
                yield f"event: {kind}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"
                if kind == "done":
                    break
        finally:
            if not task.done():
                task.cancel()
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------- финансы ----------------
@app.exception_handler(finance.FinanceError)
async def _fin_err(_, exc: finance.FinanceError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/media/{path:path}", include_in_schema=False)
def media(path: str):
    from fastapi.responses import FileResponse
    f = (brain_notes.MEDIA_DIR / path).resolve()
    if not str(f).startswith(str(brain_notes.MEDIA_DIR.resolve())) or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/manifest.json", include_in_schema=False)
def manifest():
    return {
        "name": persona.display_name(), "short_name": persona.display_name(), "start_url": "/", "display": "standalone",
        "background_color": "#f4f3f0", "theme_color": "#f4f3f0", "lang": "ru",
        "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}],
        # Ярлыки PWA (долгое нажатие на иконку на телефоне): быстрая запись без блужданий по меню
        "shortcuts": [
            {"name": "Трата", "short_name": "Трата", "url": "/?quick=exp", "icons": [{"src": "/icon-192.png", "sizes": "192x192"}]},
            {"name": "Доход", "short_name": "Доход", "url": "/?quick=inc", "icons": [{"src": "/icon-192.png", "sizes": "192x192"}]},
            {"name": "Задача", "short_name": "Задача", "url": "/?quick=task", "icons": [{"src": "/icon-192.png", "sizes": "192x192"}]},
            {"name": "Мысль", "short_name": "Мысль", "url": "/?quick=note", "icons": [{"src": "/icon-192.png", "sizes": "192x192"}]},
        ],
    }


# ---------------- роутеры по доменам (ФАЗА 7) ----------------
# ИНВАРИАНТ: этот вызов стоит ПОСЛЕ app.include_router(crm) и ДО регистрации статики
# и catch-all-роута SPA в конце файла. Если подключить роутеры после catch-all,
# SPA перехватит /api/* и сайт перестанет открываться.
# Шаг 7.4: подключены routers/finance.py (42), routers/orders.py (22),
# routers/boards.py (17), routers/people.py (15) и routers/tasks.py (15).
# Шаг 7.5a: подключён routers/mind.py (32 роута: notes/links/facts/lessons/
# memory/graph/search/cards/chat/undo) — после tasks, до статики.
# ⚠️ /api/events/stream (SSE) и /api/chat/stream (POST-SSE) НАМЕРЕННО остаются
# в app.py и по итогам шага 7.6: литерал `stream` должен регистрироваться РАНЬШЕ
# параметрического /api/events/{event_id} (иначе 422 вместо SSE), а system.py
# подключается последним — ПОСЛЕ tasks. Переносить их в system.py нельзя
# (см. reviews/P7_6_system.md, reviews/P7_5a_mind.md). Не переставлять.
from .routers import register as _register_routers  # noqa: E402

_register_routers(app)


# ---------------- сайт (Этап 2): раздаём собранную статику, если есть ----------------
web_dist = ROOT / "web" / "site"
if not web_dist.exists():
    web_dist = ROOT / "web" / "dist"
if (web_dist / "index.html").exists():
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        # До завершения мастера не отдаём приложение наружу: auth middleware
        # закроет /setup для проксированных клиентов, а локальный ПК увидит мастер.
        from ..config import setup_done
        if path == "setup":
            return HTMLResponse((ROOT / "core" / "api" / "setup.html").read_text(encoding="utf-8"))
        if not setup_done() and not path.startswith(("api", "media", "assets")):
            return RedirectResponse("/setup")
        # Неизвестный /api/… не должен перехватываться SPA и отдавать HTML с кодом 200:
        # клиент/скрипт получает «200 OK» на опечатке в URL и не видит ошибку (P2 в ревью
        # A и E, см. reviews/review_A.md и reviews/review_E.md). Живые API-роуты
        # регистрируются ДО catch-all, сюда они не попадают.
        if path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        # любой не-API маршрут (/finance, /calendar…) → index.html, роутинг делает React
        # P0 (reviews/review_A.md): `web_dist / path` без resolve() позволял прочитать
        # '/../..' — сырой GET '/../../data/api_token' отдавал файл из корня репозитория,
        # а AuthMiddleware считает не-/api/ пути публичными. Как у media() ниже:
        # сначала resolve, потом проверка, что путь остался внутри дистрибутива.
        f = (web_dist / path).resolve()
        if path and f.is_file() and f.is_relative_to(web_dist.resolve()):
            return FileResponse(f)
        return FileResponse(web_dist / "index.html")
else:
    _preview = (ROOT / "core" / "api" / "preview.html").read_text(encoding="utf-8")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def preview_page():
        return _preview
