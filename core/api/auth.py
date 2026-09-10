"""Доступ к API: с самого компьютера (loopback) — свободно; с телефона/другой машины — только с токеном.

Зачем: сервер слушает 0.0.0.0, чтобы сайт открывался с телефона (домашний Wi-Fi, Tailscale). Без проверки любой
сайт в браузере соседа по сети мог бы слать POST /api/chat, менять ключи в настройках или выключить компьютер
через ПК-клиент. Отдельного пароля не вводим: токен генерируется сам и один раз попадает в браузер телефона
через ссылку/QR из ⚙ Настроек → «с телефона» (query ?t=… → cookie на год).

Как передавать токен: cookie `assistant_session` (браузер) или заголовок `X-Auth-Token` (скрипты, голосовой клиент
на другой машине; на самом ПК он ходит на 127.0.0.1 и токен ему не нужен).
"""
from __future__ import annotations

import hmac
import ipaddress
import logging
import os
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import DATA_DIR

log = logging.getLogger("assistant.auth")

TOKEN_FILE = DATA_DIR / "api_token"
COOKIE = "assistant_session"
HEADER = "x-auth-token"
QUERY = "t"

# без токена (нет ничего секретного / нужны снаружи): здоровье, PWA-манифест, статика сайта, OAuth-возврат от Google
PUBLIC_PREFIXES = ("/assets/", "/icon-", "/apple-touch-icon", "/favicon")
PUBLIC_EXACT = {"/api/health", "/manifest.json", "/api/google/callback", "/sw.js", "/robots.txt"}
# только с самого компьютера, даже с токеном: мастер первого запуска и его API (пишут config.yaml, перезапускают процесс)
LOCAL_ONLY_PREFIXES = ("/api/setup/", "/setup")
# откуда браузеру можно слать запросы к API (Origin): сам сайт (тот же host) + dev-сервер Vite
DEV_ORIGINS = {"http://localhost:5173", "http://127.0.0.1:5173"}


def _load_or_create() -> str:
    try:
        t = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if len(t) >= 32:
            return t
    except FileNotFoundError:
        pass
    t = secrets.token_urlsafe(32)
    TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_FILE.write_text(t, encoding="utf-8")
    try:
        TOKEN_FILE.chmod(0o600)
    except Exception:  # Windows
        pass
    log.info("Создан токен доступа к API с других устройств: %s", TOKEN_FILE)
    return t


_TOKEN: str | None = None


def token() -> str:
    global _TOKEN
    if _TOKEN is None:
        _TOKEN = _load_or_create()
    return _TOKEN


def rotate() -> str:
    """Новый токен (старые ссылки/куки перестают работать)."""
    global _TOKEN
    TOKEN_FILE.unlink(missing_ok=True)
    _TOKEN = None
    return token()


# В Docker браузер хоста приходит из сети моста (172.x), а не с loopback — «свой компьютер» там определяется токеном,
# ссылку с ним контейнер печатает в лог при старте (как Jupyter).
IN_DOCKER = bool(os.getenv("ASSISTANT_DOCKER"))


def is_loopback(request: Request) -> bool:
    host = (request.client.host if request.client else "") or ""
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host in ("localhost", "testclient")


def is_local(request: Request) -> bool:
    """«Сам компьютер»: loopback, а в Docker — любой клиент с верным токеном."""
    if is_loopback(request):
        return True
    return IN_DOCKER and _token_ok(request)


def _token_ok(request: Request) -> bool:
    p = _presented(request)
    return bool(p) and hmac.compare_digest(p, token())


def _presented(request: Request) -> str | None:
    return (request.headers.get(HEADER) or request.cookies.get(COOKIE)
            or request.query_params.get(QUERY) or None)


def is_authorized(request: Request) -> bool:
    return is_loopback(request) or _token_ok(request)


def _host_ok(request: Request) -> bool:
    """Защита от DNS-rebinding: чужой домен evil.example может резолвиться в 127.0.0.1, и тогда браузер жертвы
    придёт к нам с loopback-адреса (= «свой», без токена), но с Host: evil.example. Принимаем только адреса,
    по которым сайт реально открывают: IP, localhost, имя этого ПК, Tailscale MagicDNS (*.ts.net)."""
    host = (request.headers.get("host") or "").split(":")[0].strip("[]").lower()
    if not host:
        return True  # HTTP/1.0-клиенты и скрипты без Host — не браузер, rebinding им не грозит
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith((".ts.net", ".local", ".localhost", ".internal")):
        return True
    if host == "testserver" and os.getenv("ASSISTANT_TEST"):
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    import socket
    return host == socket.gethostname().lower()


def _origin_ok(request: Request) -> bool:
    """Защита от CSRF: чужой сайт может отправить <form> (multipart/text-plain) без CORS-preflight.
    Меняющие запросы принимаем только со своего origin (Origin == схема+Host) или без Origin (скрипты, curl, клиенты)."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return True
    if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
        return False
    origin = request.headers.get("origin")
    if not origin:
        return True
    if origin in DEV_ORIGINS:
        return True
    host = request.headers.get("host", "")
    return origin.lower() in (f"http://{host}".lower(), f"https://{host}".lower())


def _is_public(path: str) -> bool:
    if path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES):
        return True
    # сам сайт (SPA) отдаём всем: это статический бандл без данных; данные тянутся через /api и уже проверяются
    return not path.startswith("/api/") and not path.startswith("/media/") and not path.startswith(LOCAL_ONLY_PREFIXES)


class AuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        token()  # создаём ключ сразу при старте, чтобы data/api_token был на месте до первого захода с телефона

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(("/api/", "/media/")) or path.startswith(LOCAL_ONLY_PREFIXES):
            # rebinding опасен только там, где доверяем адресу клиента (loopback без токена); удалённым и так нужен токен
            if is_loopback(request) and not _host_ok(request):
                log.warning("Отказано %s %s: чужой Host %r (DNS-rebinding?)", request.method, path, request.headers.get("host"))
                return JSONResponse({"detail": "Откройте сайт по IP-адресу или localhost"}, status_code=421)
            if not _origin_ok(request):
                log.warning("Отказано %s %s: чужой Origin %r (CSRF?)", request.method, path, request.headers.get("origin"))
                return JSONResponse({"detail": "Запрос с чужого сайта отклонён"}, status_code=403)
        if path.startswith(LOCAL_ONLY_PREFIXES) and not is_local(request):
            return JSONResponse({"detail": "Мастер настройки доступен только с самого компьютера"}, status_code=403)
        if not _is_public(path) and not is_authorized(request):
            log.warning("Отказано %s %s с %s (нет токена)", request.method, path, request.client.host if request.client else "?")
            return JSONResponse({"detail": "Нет доступа. Откройте сайт по ссылке/QR из ⚙ Настроек → «с телефона»."}, status_code=401)
        response = await call_next(request)
        # первый заход с телефона по ссылке с ?t=… → запоминаем в cookie и убираем токен из адресной строки
        q = request.query_params.get(QUERY)
        if q and not is_loopback(request) and hmac.compare_digest(q, token()) and not path.startswith("/api/"):  # noqa: E501
            clean = request.url.remove_query_params(QUERY)
            response = RedirectResponse(str(clean), status_code=303)
            response.set_cookie(COOKIE, token(), max_age=365 * 86400, httponly=True, samesite="lax", path="/")
        return response
