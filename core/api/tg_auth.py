"""Вход через Telegram Mini App — второй способ авторизации рядом с QR-ключом (auth.py).

Как это работает
----------------
Telegram открывает сайт во встроенном браузере и передаёт странице `initData` — строку, подписанную HMAC-SHA256
ключом, производным от токена бота. Мы проверяем подпись, что внутри именно владелец (user.id == telegram.owner_id),
что подпись свежая (auth_date не старше TG_MAX_AGE), и выдаём короткоживущую сессию: cookie с подписанным нами же
токеном (HMAC от секрета сервера), сроком на TG_SESSION_DAYS. Сам initData никуда не сохраняется.

Что защищает
------------
- Подделать initData без токена бота нельзя (HMAC). Токен бота лежит только в config.yaml на ПК.
- Чужой пользователь Telegram, открывший ту же ссылку, получит валидный initData, но с чужим user.id → 403.
- Перехваченный initData бесполезен спустя TG_MAX_AGE (по умолчанию 10 минут) — и в любом случае даёт только
  сессию владельца, если это его initData.
- Сессия — не мастер-ключ: это отдельный подписанный токен с датой выпуска. «Новый ключ доступа» в настройках
  меняет серверный секрет → все Telegram-сессии сразу недействительны (как и QR-куки).
- Cookie: HttpOnly, Secure (через Funnel всегда HTTPS), SameSite=None только там, где сайт открыт в webview
  Telegram (иначе Lax). Secure ставим всегда, когда запрос пришёл по HTTPS.
- Через Tailscale Funnel запросы приходят на ПК с 127.0.0.1 (с прокси на этом же ПК). auth.is_loopback это учитывает:
  если есть заголовки X-Forwarded-For / X-Forwarded-Proto — клиент внешний, «своим компьютером» не считается,
  и без ключа/сессии ничего не отдаётся.
- Мастер настройки (/setup) и /api/phone (ссылки с мастер-ключом) для внешних клиентов закрыты всегда — даже
  с валидной Telegram-сессией: это операции «с самого компьютера».
- Брутфорс: провальные попытки логина по IP ограничены (TG_LOGIN_BURST за TG_LOGIN_WINDOW секунд), каждая
  пишется в лог без секретов.

Ничего из этого не требует внешних библиотек: hmac, hashlib, json, time из стандартной библиотеки.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
from collections import defaultdict, deque
from typing import Any
from urllib.parse import parse_qsl

from fastapi import Request

from ..config import DATA_DIR, cfg

log = logging.getLogger("assistant.tgauth")

TG_MAX_AGE = 10 * 60             # initData считаем свежим 10 минут
TG_SESSION_DAYS = 30             # сессия из Telegram живёт 30 дней, потом Telegram молча выдаст новый initData
TG_LOGIN_BURST = 8               # не больше 8 неудачных логинов…
TG_LOGIN_WINDOW = 10 * 60        # …за 10 минут с одного адреса
SESSION_COOKIE = "assistant_tg"
SECRET_FILE = DATA_DIR / "session_secret"

_SECRET: bytes | None = None
_fails: dict[str, deque] = defaultdict(deque)


# ------------------------------------------------------------------ серверный секрет сессий
def _secret() -> bytes:
    """Отдельный от api_token секрет: им подписываем сессии. Ротация api_token («новый ключ») ротирует и его."""
    global _SECRET
    if _SECRET is None:
        try:
            s = SECRET_FILE.read_bytes().strip()
            if len(s) < 32:
                raise ValueError
        except (FileNotFoundError, ValueError):
            s = secrets.token_bytes(32)
            SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
            SECRET_FILE.write_bytes(s)
            try:
                SECRET_FILE.chmod(0o600)
            except Exception:  # Windows
                pass
        _SECRET = s
    return _SECRET


def rotate_secret() -> None:
    """Все Telegram-сессии — недействительны. Вызывается из auth.rotate()."""
    global _SECRET
    SECRET_FILE.unlink(missing_ok=True)
    _SECRET = None
    _secret()


# ------------------------------------------------------------------ проверка initData
def verify_init_data(init_data: str, bot_token: str, max_age: int = TG_MAX_AGE, now: float | None = None) -> dict[str, Any]:
    """Возвращает распарсенные поля initData, если подпись верна и данные свежие. Иначе ValueError с причиной
    (короткой, без секретов — её можно показать пользователю и записать в лог)."""
    if not bot_token:
        raise ValueError("бот не настроен")
    if not init_data or len(init_data) > 8192:
        raise ValueError("нет данных Telegram")
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=False)
    data = dict(pairs)
    received = data.pop("hash", None)
    if not received or len(received) != 64:
        raise ValueError("нет подписи")
    # data-check-string: все поля кроме hash, отсортированы, key=value через \n
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received.lower()):
        raise ValueError("подпись не совпала")
    try:
        auth_date = int(data.get("auth_date", "0"))
    except ValueError:
        raise ValueError("нет даты") from None
    ts = now if now is not None else time.time()
    if auth_date <= 0 or ts - auth_date > max_age or auth_date - ts > 60:
        raise ValueError("данные устарели — откройте приложение заново")
    try:
        user = json.loads(data.get("user") or "{}")
    except json.JSONDecodeError:
        raise ValueError("битые данные пользователя") from None
    if not isinstance(user, dict) or "id" not in user:
        raise ValueError("нет пользователя")
    data["user"] = user
    return data


def owner_id() -> int:
    try:
        return int(cfg.telegram.owner_id or 0)
    except (TypeError, ValueError):
        return 0


# ------------------------------------------------------------------ сессии
def issue_session(user_id: int, now: float | None = None) -> str:
    """Токен сессии: <uid>.<issued>.<hmac>. Ничего секретного внутри; подделать без серверного секрета нельзя."""
    issued = int(now if now is not None else time.time())
    body = f"{user_id}.{issued}"
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:43]
    return f"{body}.{sig}"


def session_ok(token: str | None, now: float | None = None) -> bool:
    if not token or token.count(".") != 2 or len(token) > 120:
        return False
    uid_s, issued_s, sig = token.split(".")
    body = f"{uid_s}.{issued_s}"
    expected = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:43]
    if not hmac.compare_digest(expected, sig):
        return False
    try:
        uid, issued = int(uid_s), int(issued_s)
    except ValueError:
        return False
    ts = now if now is not None else time.time()
    if issued > ts + 60 or ts - issued > TG_SESSION_DAYS * 86400:
        return False
    return uid != 0 and uid == owner_id()


def session_from(request: Request) -> bool:
    return session_ok(request.cookies.get(SESSION_COOKIE))


# ------------------------------------------------------------------ защита от перебора
def _client_key(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "?")[:64]


def login_allowed(request: Request, now: float | None = None) -> bool:
    ts = now if now is not None else time.time()
    q = _fails[_client_key(request)]
    while q and ts - q[0] > TG_LOGIN_WINDOW:
        q.popleft()
    return len(q) < TG_LOGIN_BURST


def login_failed(request: Request, reason: str, now: float | None = None) -> None:
    ts = now if now is not None else time.time()
    key = _client_key(request)
    _fails[key].append(ts)
    log.warning("Вход через Telegram отклонён (%s): %s", key, reason)


def reset_limits() -> None:  # для тестов
    _fails.clear()


# ------------------------------------------------------------------ вход
def login(request: Request, init_data: str) -> tuple[str, dict[str, Any]]:
    """Полная проверка + выпуск сессии. ValueError — отказ (причина безопасна для показа)."""
    if not login_allowed(request):
        raise ValueError("слишком много попыток — подождите 10 минут")
    token = (getattr(cfg.telegram, "token", "") or "").strip()
    try:
        data = verify_init_data(init_data, token)
    except ValueError as e:
        login_failed(request, str(e))
        raise
    uid = int(data["user"]["id"])
    oid = owner_id()
    if not oid or uid != oid:
        login_failed(request, f"чужой пользователь id={uid}")
        raise ValueError("этот бот отвечает только своему владельцу")
    log.info("Вход через Telegram: владелец подтверждён")
    return issue_session(uid), data
