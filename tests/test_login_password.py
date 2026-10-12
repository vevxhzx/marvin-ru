"""Вход по паролю для облачного инстанса (мама): POST /api/login.

Без настроенного server.password эндпоинта как бы нет (404), с паролем —
неверный даёт 401, верный ставит сессионную куку assistant_session,
по которой открываются чувствительные маршруты. Перебор ограничен
общим лимитом чувствительных маршрутов (429).
"""

import os

os.environ.setdefault("ASSISTANT_TEST", "1")

from tests.test_core import fresh_db  # noqa: E402,F401  (autouse-фикстура на временную БД)


def _client(remote=True):
    from fastapi.testclient import TestClient

    from core.api.app import app

    return TestClient(
        app, client=("192.168.1.50", 5555) if remote else ("127.0.0.1", 5555), base_url="http://testserver"
    )


def _set_password(monkeypatch, value):
    """Настроенный пароль сервера (config.yaml: server.password)."""
    from core import config

    monkeypatch.setattr(config.cfg.server, "password", value, raising=False)


def test_login_disabled_without_password(monkeypatch):
    _set_password(monkeypatch, "")
    c = _client()
    assert c.post("/api/login", json={"password": "что-угодно"}).status_code == 404
    assert c.post("/api/login", json={"password": ""}).status_code == 404


def test_health_reports_auth_mode(monkeypatch):
    _set_password(monkeypatch, "")
    assert _client().get("/api/health").json()["auth"] == "token"
    _set_password(monkeypatch, "мам-пароль")
    assert _client().get("/api/health").json()["auth"] == "password"


def test_login_wrong_password_rejected(monkeypatch):
    _set_password(monkeypatch, "мам-пароль")
    c = _client()
    assert c.get("/api/status").status_code == 401
    assert c.post("/api/login", json={"password": "не-то"}).status_code == 401
    assert c.get("/api/status").status_code == 401


def test_login_correct_sets_cookie_and_opens_api(monkeypatch):
    from core.api import auth

    _set_password(monkeypatch, "мам-пароль")
    c = _client()
    r = c.post("/api/login", json={"password": "мам-пароль"})
    assert r.status_code == 200 and r.json().get("ok") is True
    ck = r.headers["set-cookie"].lower()
    assert f"{auth.COOKIE}=" in ck and "httponly" in ck
    assert c.get("/api/status").status_code == 200


def test_login_bruteforce_rate_limited(monkeypatch):
    from core.api.app import RateLimitMiddleware, reset_chat_rate

    _set_password(monkeypatch, "мам-пароль")
    monkeypatch.setattr(RateLimitMiddleware, "AUTH_RATE_LIMIT", 5)
    reset_chat_rate()
    try:
        c = _client()
        for _ in range(5):
            assert c.post("/api/login", json={"password": "не-то"}).status_code == 401
        r = c.post("/api/login", json={"password": "не-то"})
        assert r.status_code == 429
    finally:
        reset_chat_rate()
