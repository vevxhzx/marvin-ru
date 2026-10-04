"""HTTP API ядра. Его используют: сайт (Этап 2) и голосовой клиент на ПК (Этап 3)."""
from __future__ import annotations

from collections import deque
from typing import Optional

from fastapi.responses import JSONResponse, RedirectResponse
import logging
import time
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from ..brain import agent, persona
from ..config import ROOT, cfg
from ..services import brain_notes, finance
from .schemas import (  # ФАЗА 7 шаг 7.0: тела моделей вынесены в core/api/schemas.py, имена те же
   ChatIn,
)

log = logging.getLogger("jarvis.api")

app = FastAPI(title="Marvin Core", version="0.1")

# доступ с других устройств — только с токеном (см. core/api/auth.py); с самого ПК — свободно
from .auth import AuthMiddleware, is_loopback  # noqa: E402


# ---------------- лимиты запросов: защита от перегрузки и перебора ----------------
# Окно скользящее и живёт в памяти процесса (перезапуск сервера сбрасывает счётчики).
CHAT_RATE_LIMIT = 30           # не больше стольких запросов к чату...
CHAT_RATE_WINDOW = 60          # ...за столько секунд с одного не-loopback адреса
CHAT_PATHS = ("/api/chat", "/api/chat/stream")

BODY_JSON_LIMIT = 4 * 1024 * 1024             # обычный JSON: больше всех наших тел, но не «8 МБ в память целиком»
BODY_MULTIPART_LIMIT = 25 * 1024 * 1024       # файлы (выписка, картинки)
BODY_BIG_JSON_LIMIT = 25 * 1024 * 1024        # JSON с картинкой: /api/vision/ask шлёт скриншот в base64
BODY_BIG_JSON_PATHS = ("/api/vision/ask",)

_chat_hits: dict[str, deque] = {}


def reset_chat_rate() -> None:  # для тестов
    """Сбросить скользящее окно лимита чата."""
    _chat_hits.clear()


def _cfg_flag(path: str, default: bool) -> bool:
    """Булев ключ настроек по точечному пути (`api.rate_limit_chat`); ключа в config.yaml нет → default.

    Читается «в момент запроса»: настройку можно поменять без перезапуска (и из тестов)."""
    node = cfg
    for part in path.split("."):
        node = getattr(node, part, None)
        if node is None:
            return default
    if isinstance(node, str):
        return node.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(node)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Лимиты запросов с одного адреса для внешних (не-loopback) клиентов.

    Два независимых окна в одном middleware:
      * чат — POST /api/chat и /api/chat/stream, CHAT_RATE_LIMIT за CHAT_RATE_WINDOW
        (выключается настройкой `api.rate_limit_chat`, по умолчанию включён);
      * чувствительные маршруты (AUTH_PATHS) — AUTH_RATE_LIMIT за то же окно, но
        СЧИТАЮТСЯ ТОЛЬКО НЕАВТОРИЗОВАННЫЕ попытки: по этим маршрутам подбирают ключ
        доступа (?t= / X-Auth-Token), а он — единственный барьер между домашней сетью
        и всей базой. Владелец с верным ключом со своего телефона в лимит не упирается.

    Loopback (свой ПК, тесты) не считаем — лимиты защищают от внешнего флуда/перебора."""

    # маршруты, где лимит защищает от подбора ключа доступа и от выгрузки данных
    AUTH_PATHS = ("/api/settings", "/api/status", "/api/backups", "/api/dashboard",
                  "/api/export", "/api/phone", "/api/setup")
    AUTH_RATE_LIMIT = 60           # не больше стольких попыток в минуту…

    async def dispatch(self, request: Request, call_next):
        from .auth import is_authorized
        from .tg_auth import _client_key
        path = request.url.path
        chat = request.method == "POST" and path in CHAT_PATHS
        sensitive = any(path == p or path.startswith(p + "/") for p in self.AUTH_PATHS)
        if not is_loopback(request) and (
                (chat and _cfg_flag("api.rate_limit_chat", True))
                # по служебным маршрутам считаем ТОЛЬКО неавторизованные попытки:
                # с ними подбирают ключ (?t=/X-Auth-Token), а владелец с верным ключом
                # не должен упираться в лимит на своём же телефоне
                or (sensitive and not is_authorized(request))):
            limit = CHAT_RATE_LIMIT if chat else self.AUTH_RATE_LIMIT
            # ключ — XFF-aware (_client_key доверяет X-Forwarded-For только от прокси на этом же ПК):
            # за NAT все клиенты делят адрес соединения, а подделкой XFF лимит не обойти
            key = _client_key(request) + ("|chat" if chat else "|auth")
            now = time.monotonic()
            if len(_chat_hits) > 512:
                # редкая уборка: адреса с протухшим окном не держим в памяти
                for k, q in list(_chat_hits.items()):
                    while q and now - q[0] > CHAT_RATE_WINDOW:
                        q.popleft()
                    if not q:
                        _chat_hits.pop(k, None)
            q = _chat_hits.get(key)
            if q:
                while q and now - q[0] > CHAT_RATE_WINDOW:
                    q.popleft()
            if q and len(q) >= limit:
                log.warning("Лимит запросов: адрес %s сделал %d попыток за %d с (%s) — отвечаю 429",
                            key, len(q), CHAT_RATE_WINDOW, path)
                what = "к чату" if chat else "к служебным маршрутам"
                return JSONResponse(
                    {"detail": f"Слишком много запросов {what}: не больше {limit} за минуту. Попробуйте чуть позже."},
                    status_code=429, headers={"Retry-After": str(CHAT_RATE_WINDOW)})
            if not q:
                q = _chat_hits[key] = deque()
            q.append(now)
        return await call_next(request)


class BodyLimitMiddleware(BaseHTTPMiddleware):
    """Слишком большое тело запроса — сразу 413 с JSON, а не чтение мегабайтов в память."""

    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            raw = request.headers.get("content-length")
            try:
                size = int(raw) if raw else None
            except ValueError:
                size = None  # мусорный заголовок — дальше решат роут/валидация
            if size is not None and size > 0:
                ctype = request.headers.get("content-type", "")
                if ctype.startswith("multipart/form-data"):
                    limit = BODY_MULTIPART_LIMIT
                elif request.url.path in BODY_BIG_JSON_PATHS:
                    limit = BODY_BIG_JSON_LIMIT
                else:
                    limit = BODY_JSON_LIMIT
                if size > limit:
                    log.warning("Слишком большое тело: %s %s — %d байт (лимит %d)",
                                request.method, request.url.path, size, limit)
                    return JSONResponse(
                        {"detail": f"Тело запроса слишком большое (не больше {limit // (1024 * 1024)} МБ)"},
                        status_code=413)
        return await call_next(request)


# Порядок: каждый add_middleware кладёт middleware НАРУЖУ уже имеющихся. Поэтому AuthMiddleware
# регистрируется ПЕРВЫМ (самая глубокая — авторизация не ослабляется), а CORS — ПОСЛЕДНИМ (самый внешний).
app.add_middleware(AuthMiddleware)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(RateLimitMiddleware)
# CORS: сайт живёт на том же origin, что и API, — чужим сайтам доступ не нужен. Разрешаем только dev-сервер Vite.
# Внешним он и для того, чтобы заголовки ставились на ответы авторизации/лимитов и на OPTIONS-preflight:
# раньше AuthMiddleware был снаружи, префлайт получал 401 и CORS для dev-стенда не работал.
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def _security_headers(request, call_next):
    """Минимум защитных заголовков на каждый ответ. Без CSP: её вводим отдельно
    в Report-Only — сейчас только то, что ничего не ломает."""
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Permissions-Policy"] = "camera=(),microphone=(),geolocation=()"
    return resp

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

# Потолок SSE-подписчиков: очередь подписок на адрес клиента, не больше SSE_MAX_PER_IP потоков.
# Без потолка клиент, открывающий вкладку за вкладкой, держит в памяти процесса неограниченное
# число подписок (каждая — своя очередь и своё ожидание); самое старое подключение отвязываем.
SSE_MAX_PER_IP = 20
_SSE_CLOSE = object()                     # сигнал в очередь: «твоё подключение отвязано»
_sse_by_ip: dict[str, deque] = {}          # адрес → очередь открытых подключений (старые вперёд)


def _sse_key(request: Optional[Request]) -> str:
    """Адрес клиента для потолка подписок. X-Forwarded-For не берём: заголовок подделывается,
    и чужой клиент мог бы под ним отвязывать чужие потоки."""
    if request is None:
        return "local"
    return ((request.client.host if request.client else "") or "?")[:64]


@app.get("/api/events/stream")
async def stream(client: str = "", request: Request = None):
    """Живые события. `?client=pc` — так подключается voice.bat: по этим подключениям ядро знает, слушает ли кто-то ПК-команды.

    `request` подставляет FastAPI (адрес клиента нужен для потолка подписок); при прямом вызове
    из тестов его можно не передавать.
    """
    from ..services import pc as _pc
    q: _asyncio.Queue = _asyncio.Queue()
    key = _sse_key(request)
    dq = _sse_by_ip.setdefault(key, deque())
    while len(dq) >= SSE_MAX_PER_IP:
        # самое старое подключение этого адреса отвязываем (с логом) и просим корректно завершиться
        old_q, old_client = dq.popleft()
        _subscribers.discard(old_q)
        if old_client == "pc":
            _pc_streams.discard(id(old_q)); _pc.SSE_CLIENTS = len(_pc_streams)
        try:
            old_q.put_nowait(_SSE_CLOSE)
        except Exception:  # pragma: no cover
            pass
        log.warning("SSE: с %s открыто больше %d подключений — самое старое закрыто", key, SSE_MAX_PER_IP)
    entry = (q, client)
    dq.append(entry)
    _subscribers.add(q)
    if client == "pc":
        _pc_streams.add(id(q)); _pc.SSE_CLIENTS = len(_pc_streams)

    async def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    msg = await _asyncio.wait_for(q.get(), timeout=25)
                    if msg is _SSE_CLOSE:      # нас отвязали по потолку — закрываем поток
                        break
                    yield f"data: {msg}\n\n"
                except _asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            _subscribers.discard(q)
            if client == "pc":
                _pc_streams.discard(id(q)); _pc.SSE_CLIENTS = len(_pc_streams)
            if entry in dq:
                dq.remove(entry)
            if not _sse_by_ip.get(key):
                _sse_by_ip.pop(key, None)
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
    root = brain_notes.MEDIA_DIR.resolve()
    f = (root / path).resolve()
    if not f.is_file() or not f.is_relative_to(root):
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.get("/manifest.webmanifest", include_in_schema=False)
@app.get("/manifest.json", include_in_schema=False)
def manifest():
    """Манифест PWA.

    Имя и цвета берём из настроек (identity + тема), структуру и иконки — из статического
    файла web/public/manifest.webmanifest, который копирует сборка в web/site. Поэтому
    переименование ассистента в конфиге меняет имя установленного приложения, а поля
    (иконки, ярлыки, режим standalone) живут в одном месте.
    """
    from fastapi.responses import JSONResponse

    static = ROOT / "web" / "site" / "manifest.webmanifest"
    data: dict = {}
    if static.is_file():
        try:
            data = _json.loads(static.read_text(encoding="utf-8"))
        except Exception as e:  # pragma: no cover - битый статический файл
            log.warning("манифест PWA не прочитан: %s", e)
    name = persona.display_name() or data.get("name") or "Marvin"
    data["name"] = name
    data["short_name"] = name[:12]
    # цвета — из темы: фон страницы тёмной темы и светлой
    dark = "#0f1530"
    data.setdefault("theme_color", dark)
    data.setdefault("background_color", dark)
    return JSONResponse(data, headers={"Cache-Control": "no-cache"})


# ---------------- роутеры по доменам (ФАЗА 7) ----------------
# ИНВАРИАНТ: этот вызов стоит ПОСЛЕ app.include_router(crm) и ДО регистрации статики
# и catch-all-роута SPA в конце файла. Если подключить роутеры после catch-all,
# SPA перехватит /api/* и сайт перестанет открываться.
# Шаг 7.4: подключены routers/finance.py (42), routers/orders.py (22),
# routers/boards.py (17), routers/people.py (15) и routers/tasks.py (15).
# Шаг 7.5a: подключён routers/mind.py (32 роута: notes/links/facts/lessons/
# memory/graph/search/cards/chat/undo) — после tasks, до статики.
# Позже добавлен routers/learn.py (7 роутов: /api/english/*) — перед system, тот остаётся последним.
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
