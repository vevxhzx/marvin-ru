"""Ревью E «Надёжность» — часть 3: обработка ошибок, секреты в логах, зависания.

Проверяем на временной БД (фикстура `fresh_db` из tests/test_core):
  * неизвестный путь API и кривое JSON-тело не роняют сервер;
  * `PRAGMA busy_timeout` выставлен, «запертая» база не убивает процесс;
  * в логах (data/server.log, data/voice.log) нет ключей и токенов;
  * нет `time.sleep` в async-роутах, есть (находка) блокирующий I/O в async-роутах;
  * на размер тела запроса нет лимита (находка).

Тесты с пометкой xfail фиксируют НАЙДЕННУЮ проблему: падают до исправления,
при исправлении дают XPASS (надо переписать тест и убрать находку из отчёта).
"""
from __future__ import annotations

import asyncio
import inspect
import os
import re
import sqlite3
import time
from pathlib import Path

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402
from tests.test_core import fresh_db  # noqa: E401,F401  (autouse: временная БД)

ROOT = Path(__file__).resolve().parent.parent


def _client(**kw):
    from fastapi.testclient import TestClient
    from core.api.app import app
    kw.setdefault("base_url", "http://testserver")
    kw.setdefault("client", ("127.0.0.1", 5555))
    return TestClient(app, **kw)


# ---------------------------------------------------------------- неожиданные входы
def test_unknown_api_path_does_not_crash_server():
    c = _client()
    r = c.get("/api/definitely-missing-route")
    assert r.status_code in (200, 404), f"неожиданный статус {r.status_code}"
    # сервер жив после мусорного запроса
    assert c.get("/api/health").status_code == 200


# FINDING P2 закрыт: SPA catch-all отдаёт 404 на неизвестный GET /api/* (core/api/app.py::spa).
def test_unknown_api_path_should_be_404():
    c = _client()
    assert c.get("/api/definitely-missing-route").status_code == 404


def test_unknown_api_path_wrong_method():
    c = _client()
    r = c.post("/api/definitely-missing-route", json={})
    assert r.status_code in (404, 405), f"неожиданный статус {r.status_code}"
    assert r.status_code != 500


def test_broken_json_body_is_rejected_not_500():
    c = _client()
    r = c.post("/api/tasks", content=b'{"title": "x', headers={"content-type": "application/json"})
    assert r.status_code == 422, f"кривое JSON-тело → {r.status_code}"
    r2 = c.post("/api/chat", content=b"\x00\x01\xff not json", headers={"content-type": "application/json"})
    assert r2.status_code == 422
    assert c.get("/api/health").status_code == 200


def test_validation_error_on_wrong_types():
    c = _client()
    r = c.post("/api/tasks", json={"title": {"nested": "obj"}})
    assert r.status_code == 422


# ---------------------------------------------------------------- SQLite
def test_pragma_busy_timeout_set(fresh_db):
    from core import db
    with db.engine.connect() as conn:
        assert conn.execute(__import__("sqlalchemy").text("PRAGMA busy_timeout")).scalar() == 5000
        assert str(conn.execute(__import__("sqlalchemy").text("PRAGMA journal_mode")).scalar()).lower() == "wal"


def test_locked_database_does_not_kill_server(fresh_db):
    """Другой процесс держит write-блок: запрос отвечает ошибкой (5xx), сервер продолжает работать."""
    from core import db
    dbfile = db.engine.url.database
    c = _client(raise_server_exceptions=False)
    blocker = sqlite3.connect(dbfile)
    try:
        blocker.execute("BEGIN EXCLUSIVE")
        t0 = time.time()
        r = c.post("/api/tasks", json={"title": "блокировка"}, timeout=60)
        waited = time.time() - t0
        assert r.status_code >= 500, f"ожидалась ошибка 5xx при locked-базе, получено {r.status_code}"
        assert waited >= 4.0, f"запрос не ждал busy_timeout ({waited:.1f} с) — busy_timeout не работает?"
    finally:
        try:
            blocker.rollback()
        except Exception:
            pass
        blocker.close()
    # процесс жив и база снова доступна
    assert c.get("/api/tasks").status_code == 200
    assert c.get("/api/health").status_code == 200


# ---------------------------------------------------------------- секреты в логах
_LOG_PATTERNS = [
    (re.compile(r"gsk_[A-Za-z0-9]{16,}"), "groq-ключ"),
    (re.compile(r"AIza[0-9A-Za-z_-]{25,}"), "ключ Google"),
    (re.compile(r"\d{8,10}:[A-Za-z0-9_-]{35,}"), "telegram-токен"),
]


def test_log_files_contain_no_secrets():
    """data/server.log и data/voice.log: в них не должно быть значений ключей."""
    tok_file = ROOT / "data" / "api_token"
    token = tok_file.read_text(encoding="utf-8").strip() if tok_file.exists() else ""
    for name in ("server.log", "voice.log"):
        p = ROOT / "data" / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        if token:
            assert token not in text, f"{name}: внутри лежит значение data/api_token"
        for rx, what in _LOG_PATTERNS:
            assert not rx.search(text), f"{name}: похоже на {what} в логе"


def test_core_logging_does_not_print_secrets():
    """Ни один вызов log.* в core/** не выводит значений ключей/токенов.

    Из текста вызова вырезаются строковые литералы (в них бывает «ключ задан»),
    и ищется только случай, когда секрет уходит в лог аргументом.
    """
    bad = []
    call_rx = re.compile(r"log\.(?:info|warning|error|debug|exception|critical)\(")
    str_rx = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'', re.S)
    secret_rx = re.compile(r"(?:cfg\.[\w.]*token|cfg\.[\w.]*api_key|cfg\.[\w.]*password|"
                           r"\bauth\.token\(\)|\b_tok\(\)|\bCLOUD_KEY\b|\bGEMINI_KEY\b)\s*[,)]")
    for p in (ROOT / "core").rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        for m in call_rx.finditer(src):
            call = str_rx.sub('""', src[m.start():m.start() + 800])
            start = call.find("(")
            depth, end = 0, len(call)
            for i in range(start, len(call)):
                if call[i] == "(":
                    depth += 1
                elif call[i] == ")":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            call = call[:end]
            if secret_rx.search(call):
                bad.append(f"{p.relative_to(ROOT)}: {' '.join(call.split())[:160]}")
    assert not bad, "секрет в логировании:\n" + "\n".join(bad)


# FINDING P2 закрыт: в run.py больше нет log(..._tok()) — ключ пишется только в data/api_token.
def test_entry_point_does_not_log_access_key():
    src = (ROOT / "run.py").read_text(encoding="utf-8")
    rx = re.compile(r"log\.(?:info|warning|error)\([^;]{0,400}?\b_tok\(\)", re.S)
    assert not rx.search(src), "run.py логирует ключ доступа"


# ---------------------------------------------------------------- зависания / I/O
def test_no_time_sleep_in_api_package():
    """В core/api нет синхронных пауз — event loop не ставится на паузу на несколько секунд."""
    for p in (ROOT / "core" / "api").rglob("*.py"):
        src = p.read_text(encoding="utf-8")
        assert "time.sleep" not in src, f"{p.relative_to(ROOT)}: time.sleep внутри API"


@pytest.mark.xfail(reason="FINDING P2: POST /api/finance/import — async-def роут, который синхронно парсит "
                          "выписку до 25 МБ (PDF/XLSX) прямо в event loop: на время разбора сервер не отвечает "
                          "(SSE, Telegram, остальные запросы стоят)", strict=False)
def test_finance_import_does_not_block_event_loop():
    import inspect as _inspect
    from core.api.routers import finance
    # синхронный роут FastAPI выполняется в threadpool и event loop не блокирует
    assert not _inspect.iscoroutinefunction(finance.finance_import)


@pytest.mark.xfail(reason="FINDING P2: на тело запроса нет лимита — 8 МБ JSON читаются в память целиком, "
                          "только после этого падает валидация (422), а не 413", strict=False)
def test_request_body_size_is_limited():
    c = _client()
    body = b'{"title":"' + b"a" * (8 * 1024 * 1024) + b'"}'
    r = c.post("/api/tasks", content=body, headers={"content-type": "application/json"}, timeout=60)
    assert r.status_code == 413


def test_large_but_valid_request_is_handled():
    """Сервер не падает на большом теле — отвечает валидацией и продолжает работать."""
    c = _client()
    body = b'{"title":"' + b"a" * (2 * 1024 * 1024) + b'"}'
    r = c.post("/api/tasks", content=body, headers={"content-type": "application/json"}, timeout=60)
    assert r.status_code == 422  # длиннее max_length=500
    assert c.get("/api/health").status_code == 200
