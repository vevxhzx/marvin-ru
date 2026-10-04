"""Защитные заголовки ответов API (S9): nosniff / no-referrer / DENY / Permissions-Policy на каждом ответе."""
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

from tests.test_core import fresh_db  # noqa: E402,F401  (autouse-фикстура)


def _client():
    from fastapi.testclient import TestClient
    from core.api.app import app
    return TestClient(app)


def test_security_headers_on_public_response():
    r = _client().get("/api/health")
    assert r.status_code == 200
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("referrer-policy") == "no-referrer"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("permissions-policy") == "camera=(),microphone=(),geolocation=()"


def test_security_headers_on_error_response():
    # 401 снаружи без ключа — заголовки тоже стоят (middleware, а не отдельные роуты)
    from fastapi.testclient import TestClient
    from core.api.app import app
    c = TestClient(app, client=("192.168.1.50", 5555))
    r = c.get("/api/tasks")
    assert r.status_code == 401
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
