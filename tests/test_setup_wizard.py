# -*- coding: utf-8 -*-
"""Мастер первой установки: API `/api/setup/*` для страницы `core/api/setup.html`.

Контракт здесь задаёт НЕ тест, а сама страница: её JS вызывает 11 адресов, и пока
в коде не было ни одного из них, первый запуск у любого нового человека упирался
в 100% нерабочий мастер (см. `core/api/app.py::spa` — редирект на /setup, пока
`setup_done()` ложно). Первый тест в файле вытаскивает адреса прямо из HTML и
сверяет их с таблицей роутинга: правка страницы без правки API (или наоборот)
уронит сборку.

Что ещё проверяем: мастер доступен только с localhost (правила — `core/api/auth.py`),
секреты наружу не уходят и в лог не пишутся, ответы честные (никакого «готово»
без реальной проверки), а повтор любого запроса безвреден.

Боевой config.yaml не трогаем: фикстура `cfg_file` уводит настройки во временный
файл через `JARVIS_CONFIG` (тот же приём, что в `tests/test_review_a_access.py`).
БД — временная (`fresh_db` из tests/test_core, подключается импортом ниже).
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from tests.test_core import fresh_db  # noqa: F401  (autouse: временная БД, не боевая data/)

from core.config import ROOT
from core.api.app import app
from core.api.routers import setup as setup_api

HTML = ROOT / "core" / "api" / "setup.html"

SECRET_TOKEN = "777000123456:AAFsuperSECRETtokenVALUE"
SECRET_CLOUD = "sk-or-v1-superSECRETcloudVALUE"
SECRET_GEMINI = "AIzaSy-superSECRETgeminiVALUE"


# ============================ 0. контракт страница → API ============================
def _html_calls() -> list[tuple[str, str]]:
    """Адреса, которые мастер реально вызывает: api('МЕТОД', '/api/setup/…')."""
    text = HTML.read_text(encoding="utf-8")
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"api\('(GET|POST|PUT|DELETE)',\s*'([^']*)'", text):
        out.append((m.group(1), m.group(2)))
    return out


def _routes() -> set[tuple[str, str]]:
    """(метод, путь) всех подключённых роутов: разворачиваем include_router."""
    out: set[tuple[str, str]] = set()

    def walk(routes):
        for r in routes:
            if type(r).__name__ == "_IncludedRouter":
                walk(r.original_router.routes)
                continue
            path = getattr(r, "path", None)
            if path is None:
                continue
            for method in getattr(r, "methods", None) or []:
                out.add((method, path))

    walk(app.router.routes)
    return out


WIZARD_CALLS = _html_calls()


def test_wizard_page_calls_at_least_ten_setup_addresses():
    """Страница зовёт 10+ адресов /api/setup/* — если это перестало быть правдой,
    значит страницу переписали и тест ниже (контракт) надо перечитать руками."""
    assert len(WIZARD_CALLS) >= 10
    assert all(p.startswith("/api/setup/") for _, p in WIZARD_CALLS)


@pytest.mark.parametrize("method,path", WIZARD_CALLS)
def test_every_address_from_the_page_exists(method, path):
    """Каждый адрес, который зовёт страница, есть в таблице роутинга с тем же методом.

    Адрес с конкатенацией (`'/api/setup/ollama/pull/' + S.model`) сверяем по префиксу.
    """
    have = _routes()
    if method in have and any(m == method and p.startswith(path) for m, p in have):
        return
    raise AssertionError(f"страница зовёт {method} {path}, а такого роута нет")


def test_no_setup_route_is_dead_code():
    """Обратная сторона контракта: каждый роут мастера зовётся страницей."""
    called = {p for _, p in WIZARD_CALLS}
    dead = sorted(p for m, p in _routes() if p.startswith("/api/setup/") and not any(c.startswith(p) for c in called))
    assert not dead, f"роуты мастера, которых не зовёт страница: {dead}"


def test_setup_router_registered_before_spa_and_before_system():
    """Инвариант `core/api/routers/__init__.py`: домен подключается ДО `system`
    (который должен остаться последним) и до catch-all SPA `/{path:path}`
    (иначе SPA перехватит `/api/setup/*` и отдаст HTML вместо JSON)."""
    routes = app.router.routes
    setup_idx = system_idx = spa_idx = None
    for i, r in enumerate(routes):
        if type(r).__name__ != "_IncludedRouter":
            if getattr(r, "path", None) in ("/{path:path}", "/"):
                spa_idx = i if spa_idx is None else spa_idx
            continue
        paths = [getattr(x, "path", "") for x in r.original_router.routes]
        if any(p.startswith("/api/setup/") for p in paths):
            setup_idx = i
        if any(p == "/api/health" for p in paths):
            system_idx = i
    assert setup_idx is not None, "core/api/routers/setup.py не подключён к app"
    assert system_idx is not None
    assert setup_idx < system_idx, "setup должен подключаться раньше system"
    assert setup_idx < spa_idx, "setup должен подключаться раньше catch-all SPA"


# ============================ 1. безопасность: только свой компьютер ============================
def _client(remote: bool = False) -> TestClient:
    return TestClient(app, client=("192.168.1.50", 5555) if remote else ("127.0.0.1", 5555),
                      base_url="http://testserver")


def _headers() -> dict:
    from core.api import auth
    return {"X-Auth-Token": auth.token()}


REMOTE_CALLS = [
    ("GET", "/api/setup/state", None),
    ("GET", "/api/setup/hardware", None),
    ("GET", "/api/setup/ollama", None),
    ("POST", "/api/setup/ollama/pull", {"model": "qwen2.5:3b"}),
    ("GET", "/api/setup/ollama/pull/qwen2.5:3b", None),
    ("GET", "/api/setup/providers", None),
    ("POST", "/api/setup/check/cloud", {"provider": "groq", "api_key": SECRET_CLOUD}),
    ("POST", "/api/setup/check/telegram", {"token": SECRET_TOKEN}),
    ("POST", "/api/setup/telegram/owner", {"token": SECRET_TOKEN}),
    ("POST", "/api/setup/save", {"changes": {"brain.mode": "local"}}),
    ("POST", "/api/setup/restart", None),
]


@pytest.mark.parametrize("method,path,body", REMOTE_CALLS)
def test_setup_api_rejected_from_other_machine_even_with_token(method, path, body):
    """Мастер пишет config.yaml, качает модели и перезапускает ядро — с телефона
    (даже с ключом из ⚙ Настроек) недоступен: 403 (auth.py, LOCAL_ONLY_EARLY_PREFIXES)."""
    r = _client(remote=True).request(method, path, json=body, headers=_headers())
    assert r.status_code == 403, f"{method} {path} снаружи — {r.status_code}, а нужен 403"


@pytest.mark.parametrize("method,path,body", REMOTE_CALLS)
def test_setup_api_from_other_machine_without_token_is_not_served(method, path, body):
    """Без ключа снаружи — тоже не отдаём (401/403), и уж точно не 200."""
    r = _client(remote=True).request(method, path, json=body)
    assert r.status_code in (401, 403), f"{method} {path} без ключа — {r.status_code}"


@pytest.mark.parametrize("method,path,body", REMOTE_CALLS)
def test_setup_api_available_from_localhost(method, path, body):
    """С localhost мастер работает: не 401/403 (плохое тело даёт 400/422 — это ОК)."""
    r = _client().request(method, path, json=body)
    assert r.status_code not in (401, 403), f"{method} {path} с localhost — {r.status_code}"
    assert r.status_code < 500, f"{method} {path} упал: {r.status_code} {r.text[:200]}"


def test_docker_token_counts_as_local(monkeypatch):
    """В Docker браузер приходит с адреса моста, а не с loopback — там «свой компьютер»
    определяется ключом (auth.IN_DOCKER), и мастер должен открыться."""
    from core.api import auth
    monkeypatch.setattr(auth, "IN_DOCKER", True)
    assert _client(remote=True).get("/api/setup/state", headers=_headers()).status_code == 200
    assert _client(remote=True).get("/api/setup/state").status_code == 403


# ============================ фикстуры: временный config.yaml ============================
@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    """Копия боевого шаблона настроек во временный файл: write_settings/edit работают
    по-настоящему, но config.yaml хозяина не трогаем."""
    p = tmp_path / "config.yaml"
    shutil.copy(ROOT / "config.example.yaml", p)
    monkeypatch.setenv("JARVIS_CONFIG", str(p))
    return p


@pytest.fixture
def secret_cfg_file(tmp_path, monkeypatch):
    """Временный config.yaml с заведомо секретными значениями."""
    p = tmp_path / "config.yaml"
    shutil.copy(ROOT / "config.example.yaml", p)
    text = p.read_text(encoding="utf-8")
    text = text.replace('token: ""', f'token: "{SECRET_TOKEN}"', 1)
    text = text.replace('api_key: ""', f'api_key: "{SECRET_CLOUD}"', 1)
    p.write_text(text, encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG", str(p))
    return p


@pytest.fixture
def mock_http(monkeypatch):
    """Подмена всех HTTP-клиентов мастера на httpx.MockTransport: сеть в тестах не нужна."""
    state = {"requests": [], "handler": None}

    def set_handler(fn):
        state["handler"] = fn

    def async_client(timeout=10.0, proxy=None):
        transport = httpx.MockTransport(state["handler"] or (lambda req: httpx.Response(500)))
        state["requests"].append(("async", timeout, proxy))
        return httpx.AsyncClient(transport=transport, trust_env=False)

    def sync_client(timeout=10.0, proxy=None):
        transport = httpx.MockTransport(state["handler"] or (lambda req: httpx.Response(500)))
        state["requests"].append(("sync", timeout, proxy))
        return httpx.Client(transport=transport, trust_env=False)

    monkeypatch.setattr(setup_api, "_local_client", async_client)
    monkeypatch.setattr(setup_api, "_sync_client", sync_client)
    monkeypatch.setattr(setup_api, "_cloud_client", async_client)
    monkeypatch.setattr(setup_api, "_proxy_client", async_client)
    return state


# ============================ 2. /state — честная картина ============================
def test_state_before_wizard_is_not_done(cfg_file):
    r = _client().get("/api/setup/state")
    assert r.status_code == 200
    body = r.json()
    assert body["done"] is False, "до мастера setup.done == false"
    assert isinstance(body["settings"], dict)
    assert "assistant.name" in body["settings"]
    assert body["settings"]["assistant.name"]["value"] == "Марвин"


def test_state_settings_shape_matches_what_the_page_reads(cfg_file):
    """Страница читает `settings[k].value` (а если значения нет — `settings[k]`)."""
    body = _client().get("/api/setup/state").json()
    for k, v in body["settings"].items():
        assert isinstance(k, str)
        assert isinstance(v, dict) and "value" in v, f"{k}: ожидался {{'value': …}}"


def test_state_reports_secret_keys_as_flags_only(secret_cfg_file):
    """Секреты наружу не уходят: ни в settings, ни отдельным полем — только «задан/не задан»."""
    r = _client().get("/api/setup/state")
    body = r.json()
    assert SECRET_TOKEN not in r.text and SECRET_CLOUD not in r.text
    assert "telegram.token" not in body["settings"], "секрет в settings быть не должен даже маской"
    assert body["keys"]["telegram.token"] is True
    assert body["keys"]["brain.cloud.api_key"] is True
    assert all(isinstance(v, bool) for v in body["keys"].values())


def test_state_reports_local_model_truthfully(cfg_file, mock_http):
    """«Какая модель скачана» — живая проверка Ollama, а не значение из настроек."""
    mock_http["handler"] = lambda req: httpx.Response(
        200, json={"models": [{"name": "qwen2.5:3b"}, {"name": "nomic-embed-text:latest"}]})
    body = _client().get("/api/setup/state").json()
    o = body["ollama"]
    assert o["running"] is True
    assert "qwen2.5:3b" in o["models"]
    assert o["embed_ready"] is True, "модель эмбеддингов есть — поиск по смыслу будет работать"


def test_state_survives_dead_ollama(cfg_file):
    """Ollama не запущена — /state всё равно отвечает (страница ждёт его на шаге 3)."""
    body = _client().get("/api/setup/state").json()
    assert body["ollama"]["running"] is False
    assert body["ollama"]["models"] == []


# ============================ 3. /hardware — честно о машине ============================
def test_hardware_reports_real_machine(cfg_file):
    import psutil
    r = _client().get("/api/setup/hardware")
    assert r.status_code == 200
    body = r.json()
    hw, rec = body["hardware"], body["recommend"]
    assert hw["ram_gb"] == round(psutil.virtual_memory().total / 2 ** 30, 1), "RAM выдумана"
    assert isinstance(hw["notes"], list) and isinstance(hw["ollama"], bool)
    assert hw["gpu"] == "" or isinstance(hw["gpu"], str)
    assert rec["mode"] in ("local", "hybrid", "cloud")
    assert isinstance(rec["why"], str) and rec["why"]
    assert rec["model"] and isinstance(rec["all"], list) and rec["all"]


def test_hardware_model_cards_have_every_field_the_page_shows(cfg_file):
    """Страница рисует по каждой карточке: id, title, min_vram, size_gb — и гасит карточку,
    если min_vram больше, чем effective_vram (рисует «не влезет в вашу память»)."""
    rec = _client().get("/api/setup/hardware").json()["recommend"]
    for m in rec["all"]:
        assert {"id", "title", "min_vram", "size_gb"} <= set(m), m
        assert isinstance(m["min_vram"], (int, float))
    assert rec["effective_vram"] >= 0


# ============================ 4. /ollama и скачивание ============================
def test_ollama_info_separates_installed_and_running(cfg_file, mock_http):
    mock_http["handler"] = lambda req: httpx.Response(200, json={"models": [{"name": "gemma3:4b"}]})
    body = _client().get("/api/setup/ollama").json()
    assert body["running"] is True
    assert body["models"] == ["gemma3:4b"]


def test_ollama_info_when_not_running(cfg_file, mock_http):
    def boom(req):
        raise httpx.ConnectError("connection refused")
    mock_http["handler"] = boom
    body = _client().get("/api/setup/ollama").json()
    assert body == {**body, "running": False, "models": []}


NDJSON = b'{"status":"pulling manifest"}\n' \
         b'{"status":"downloading a","total":2048,"completed":1024}\n' \
         b'{"status":"downloading a","total":2048,"completed":2048}\n' \
         b'{"status":"success"}\n'


def test_pull_reports_progress_and_finishes(cfg_file, mock_http):
    seen = {}

    def handler(req):
        if req.url.path.endswith("/api/pull"):
            return httpx.Response(200, content=NDJSON)
        return httpx.Response(200, json={"models": []})

    mock_http["handler"] = handler
    r = _client().post("/api/setup/ollama/pull", json={"model": "qwen2.5:3b"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    deadline = time.monotonic() + 15
    status = {}
    while time.monotonic() < deadline:
        status = _client().get("/api/setup/ollama/pull/qwen2.5:3b").json()
        if status["status"] in ("success", "error"):
            break
        time.sleep(0.05)
    assert status["status"] == "success", status
    assert status["total"] == 2048 and status["done"] == 2048, status
    assert seen  # (заполняется ниже, если прогресс читался)


def test_pull_of_downloaded_model_is_a_noop(cfg_file, mock_http):
    """Идемпотентность: уже скачанную модель не тянем заново (и не жжём интернет)."""
    def handler(req):
        if req.url.path.endswith("/api/pull"):
            raise AssertionError("повторно качать уже скачанную модель нельзя")
        return httpx.Response(200, json={"models": [{"name": "qwen2.5:3b"}]})

    mock_http["handler"] = handler
    r = _client().post("/api/setup/ollama/pull", json={"model": "qwen2.5:3b"})
    assert r.status_code == 200
    assert r.json() == {**r.json(), "ok": True, "already": True}


def test_pull_downloads_in_a_thread_not_in_the_event_loop(cfg_file, mock_http):
    """Скачивание на 5–10 минут не должно вставать в event loop (проектный
    паттерн — asyncio.to_thread, см. core/api/routers/chat.py)."""
    where = {}

    def handler(req):
        if req.url.path.endswith("/api/pull"):
            where["thread"] = threading.current_thread().name
            return httpx.Response(200, content=NDJSON)
        return httpx.Response(200, json={"models": []})

    mock_http["handler"] = handler
    _client().post("/api/setup/ollama/pull", json={"model": "qwen3:4b"})
    deadline = time.monotonic() + 15
    while "thread" not in where and time.monotonic() < deadline:
        time.sleep(0.05)
    assert where.get("thread"), "скачивание не началось"
    assert where["thread"] != threading.current_thread().name


def test_pull_error_is_honest(cfg_file, mock_http):
    def handler(req):
        if req.url.path.endswith("/api/pull"):
            return httpx.Response(404, json={"error": "model not found"})
        return httpx.Response(200, json={"models": []})

    mock_http["handler"] = handler
    _client().post("/api/setup/ollama/pull", json={"model": "нет-такой:0b"})
    deadline = time.monotonic() + 15
    st = {}
    while time.monotonic() < deadline:
        st = _client().get("/api/setup/ollama/pull/нет-такой:0b").json()
        if st["status"] in ("success", "error"):
            break
        time.sleep(0.05)
    assert st["status"] == "error" and st["error"], st


def test_pull_status_of_unknown_model_is_not_an_error(cfg_file):
    """Страница опрашивает прогресс сразу после старта; «не скачивали» — не 500."""
    r = _client().get("/api/setup/ollama/pull/never-pulled:1b")
    assert r.status_code == 200
    assert r.json()["status"] == "idle"


@pytest.mark.parametrize("model", ["", "   ", "../../etc/passwd", "a b", "x" * 200])
def test_pull_rejects_junk_model_names(cfg_file, model):
    r = _client().post("/api/setup/ollama/pull", json={"model": model})
    assert r.status_code in (400, 422), f"{model!r} -> {r.status_code}"


# ============================ 5. /providers ============================
def test_providers_list(cfg_file):
    r = _client().get("/api/setup/providers")
    assert r.status_code == 200
    ids = [p["id"] for p in r.json()]
    assert ids == ["groq", "openrouter", "nvidia", "deepseek", "gemini", "custom"], ids
    for p in r.json():
        assert p["title"] and "key_url" in p
        assert p["free"] in (True, False, None)
        assert isinstance(p["configured"], bool)


def test_providers_never_return_keys(secret_cfg_file):
    r = _client().get("/api/setup/providers")
    assert SECRET_CLOUD not in r.text and SECRET_TOKEN not in r.text


# ============================ 6. /check/cloud ============================
def test_check_cloud_ok(cfg_file, mock_http):
    mock_http["handler"] = lambda req: httpx.Response(200, json={"data": [{"id": "gpt-oss-120b"}]})
    r = _client().post("/api/setup/check/cloud", json={"provider": "groq", "api_key": SECRET_CLOUD})
    body = r.json()
    assert body["ok"] is True and body["detail"]
    assert SECRET_CLOUD not in r.text


def test_check_cloud_rejects_bad_key_in_russian(cfg_file, mock_http):
    mock_http["handler"] = lambda req: httpx.Response(401, json={"error": {"message": "Invalid API Key"}})
    body = _client().post("/api/setup/check/cloud", json={"provider": "groq", "api_key": SECRET_CLOUD}).json()
    assert body["ok"] is False
    assert "ключ" in body["detail"].lower()
    assert SECRET_CLOUD not in json.dumps(body, ensure_ascii=False)


def test_check_cloud_without_key(cfg_file):
    body = _client().post("/api/setup/check/cloud", json={"provider": "groq", "api_key": ""}).json()
    assert body["ok"] is False and "ключ" in body["detail"].lower()


def test_check_cloud_network_error_suggests_proxy(cfg_file, mock_http):
    def boom(req):
        raise httpx.ConnectError("blocked")
    mock_http["handler"] = boom
    body = _client().post("/api/setup/check/cloud", json={"provider": "groq", "api_key": SECRET_CLOUD}).json()
    assert body["ok"] is False
    assert "прокси" in body["detail"].lower() or "vpn" in body["detail"].lower()
    assert body.get("need_proxy") is True


def test_check_cloud_unknown_provider(cfg_file):
    body = _client().post("/api/setup/check/cloud", json={"provider": "выдумка", "api_key": "x"}).json()
    assert body["ok"] is False and "провайдер" in body["detail"].lower()


def test_check_cloud_custom_needs_base_url(cfg_file):
    body = _client().post("/api/setup/check/cloud", json={"provider": "custom", "api_key": "x"}).json()
    assert body["ok"] is False and "адрес" in body["detail"].lower()


def test_check_cloud_falls_back_to_chat_when_no_models_endpoint(cfg_file, mock_http):
    """Свой сервер может не отдавать /models — тогда проверяем настоящим коротким запросом."""
    calls = []

    def handler(req):
        calls.append(req.url.path)
        if req.url.path.endswith("/models"):
            return httpx.Response(404)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ок"}}]})

    mock_http["handler"] = handler
    body = _client().post("/api/setup/check/cloud",
                          json={"provider": "custom", "api_key": "k", "base_url": "http://127.0.0.1:1234/v1"}).json()
    assert body["ok"] is True, body
    assert any(p.endswith("/chat/completions") for p in calls)


def test_check_gemini(cfg_file, mock_http):
    mock_http["handler"] = lambda req: httpx.Response(200, json={"models": [{"name": "models/gemini-2.5-flash"}]})
    body = _client().post("/api/setup/check/cloud", json={"provider": "gemini", "api_key": SECRET_GEMINI}).json()
    assert body["ok"] is True, body
    assert SECRET_GEMINI not in json.dumps(body, ensure_ascii=False)


def test_check_cloud_does_not_leak_key_into_log(cfg_file, mock_http, caplog):
    mock_http["handler"] = lambda req: httpx.Response(200, json={"data": []})
    with caplog.at_level(logging.INFO):
        _client().post("/api/setup/check/cloud", json={"provider": "groq", "api_key": SECRET_CLOUD})
    assert SECRET_CLOUD not in caplog.text


# ============================ 7. /check/telegram и /telegram/owner ============================
def _tg_body(method_ok=True, **extra):
    body = {"ok": method_ok, "result": {"id": 1, "username": "marvin_test_bot", "is_bot": True}}
    body.update(extra)
    return body


def test_check_telegram_ok(cfg_file, mock_http):
    mock_http["handler"] = lambda req: httpx.Response(200, json=_tg_body())
    r = _client().post("/api/setup/check/telegram", json={"token": SECRET_TOKEN})
    body = r.json()
    assert body["ok"] is True
    assert body["username"] == "marvin_test_bot", "страница ставит ссылку t.me/username"
    assert SECRET_TOKEN not in r.text


def test_check_telegram_bad_token(cfg_file, mock_http):
    mock_http["handler"] = lambda req: httpx.Response(401, json={"description": "Unauthorized"})
    body = _client().post("/api/setup/check/telegram", json={"token": SECRET_TOKEN}).json()
    assert body["ok"] is False
    assert SECRET_TOKEN not in json.dumps(body, ensure_ascii=False)


def test_check_telegram_empty_and_broken_token(cfg_file):
    for token, why in (("", "пусто"), ("не-токен", "без двоеточия")):
        body = _client().post("/api/setup/check/telegram", json={"token": token}).json()
        assert body["ok"] is False, why


def test_check_telegram_network_error_asks_for_proxy(cfg_file, mock_http):
    def boom(req):
        raise httpx.ConnectError("unreachable")
    mock_http["handler"] = boom
    body = _client().post("/api/setup/check/telegram", json={"token": SECRET_TOKEN}).json()
    assert body["ok"] is False
    assert body.get("need_proxy") is True
    assert SECRET_TOKEN not in json.dumps(body, ensure_ascii=False)


def test_check_telegram_never_writes_token_to_log(cfg_file, mock_http, caplog):
    """httpx логирует каждый запрос на INFO, а адрес Bot API содержит токен —
    мастер обязан это резать (иначе токен бота осядет в logs/*.log)."""
    mock_http["handler"] = lambda req: httpx.Response(200, json=_tg_body())
    with caplog.at_level(logging.INFO):
        _client().post("/api/setup/check/telegram", json={"token": SECRET_TOKEN})
    assert SECRET_TOKEN not in caplog.text
    assert "bot" in caplog.text, "проверка бессмысленна, если httpx вообще не логирует"


def test_telegram_owner_waits_for_first_message(cfg_file, mock_http):
    calls = []

    def handler(req):
        calls.append((req.url.path, req.method))
        if req.url.path.endswith("/getMe"):
            return httpx.Response(200, json=_tg_body())
        if req.url.path.endswith("/sendMessage"):
            return httpx.Response(200, json={"ok": True, "result": {}})
        if req.url.path.endswith("/getUpdates"):
            return httpx.Response(200, json={"ok": True, "result": [
                {"update_id": 5, "message": {"from": {"id": 4242, "is_bot": False, "first_name": "Андрей"},
                                             "chat": {"id": 4242}, "text": "/start"}}]})
        return httpx.Response(404)

    mock_http["handler"] = handler
    r = _client().post("/api/setup/telegram/owner", json={"token": SECRET_TOKEN})
    body = r.json()
    assert body["ok"] is True, body
    assert body["owner_id"] == 4242
    assert body["name"] == "Андрей"
    assert any(p.endswith("/sendMessage") for p, _ in calls), "бот должен ответить вам в Telegram"
    assert SECRET_TOKEN not in r.text


def test_telegram_owner_reports_no_message(cfg_file, monkeypatch):
    monkeypatch.setattr(setup_api, "OWNER_WAIT_SEC", 0.3)
    body = _client().post("/api/setup/telegram/owner", json={"token": SECRET_TOKEN}).json()
    assert body["ok"] is False and body["detail"]


# ============================ 8. /save ============================
WIZARD_SAVE = {
    "assistant.name": "Марвин",
    "assistant.name_latin": "marvin",
    "owner.name": "Сэр",
    "persona.style": "swag",
    "brain.mode": "hybrid",
    "brain.ollama.model": "qwen2.5:3b",
    "brain.cloud.provider": "groq",
    "brain.cloud.api_key": SECRET_CLOUD,
    "brain.vision.where": "cloud",
    "setup.done": True,
}


def test_save_writes_config_and_reports_restart_keys(cfg_file):
    r = _client().post("/api/setup/save", json={"changes": WIZARD_SAVE})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    text = cfg_file.read_text(encoding="utf-8")
    assert "Марвин" in text and SECRET_CLOUD in text, "настройки должны лечь в config.yaml"
    # честный ответ: что применится сразу, что — только после перезапуска
    assert "brain.ollama.model" in body["restart"]
    assert "telegram.token" in body["restart"]
    assert "persona.style" not in body["restart"], "характер применяется на лету"
    assert body["done"] is True


def test_save_never_echoes_secrets(cfg_file):
    r = _client().post("/api/setup/save", json={"changes": {"telegram.token": SECRET_TOKEN,
                                                             "brain.cloud.api_key": SECRET_CLOUD,
                                                             "setup.done": True}})
    assert r.status_code == 200
    assert SECRET_TOKEN not in r.text and SECRET_CLOUD not in r.text


def test_save_rejects_unknown_and_non_scalar_keys(cfg_file):
    r = _client().post("/api/setup/save", json={"changes": {"server.password": "hack"}})
    assert r.status_code == 400, "мастер не должен писать чужие ключи (особенно пароль)"
    r2 = _client().post("/api/setup/save", json={"changes": {"assistant.name": {"hack": 1}}})
    assert r2.status_code == 400


def test_save_is_idempotent(cfg_file):
    first = _client().post("/api/setup/save", json={"changes": WIZARD_SAVE})
    text1 = cfg_file.read_text(encoding="utf-8")
    second = _client().post("/api/setup/save", json={"changes": WIZARD_SAVE})
    assert first.status_code == second.status_code == 200
    assert second.json()["changed"] == [] or set(second.json()["changed"]) <= set(WIZARD_SAVE)
    assert cfg_file.read_text(encoding="utf-8") == text1, "повторное сохранение не должно ломать файл"


def test_save_of_masked_secret_does_not_wipe_it(secret_cfg_file):
    """Страница может вернуть то, что получила («задан»/«•••») — маска не должна затереть ключ."""
    _client().post("/api/setup/save", json={"changes": {"telegram.token": "задан", "brain.cloud.api_key": "•••"}})
    text = secret_cfg_file.read_text(encoding="utf-8")
    assert SECRET_TOKEN in text and SECRET_CLOUD in text


# ============================ 9. /restart ============================
@pytest.fixture
def restart_state(monkeypatch):
    """Чистое состояние перезапуска и подменённые «убить процесс» / «spawn» — pytest не убьём."""
    monkeypatch.setattr(setup_api, "_RESTART_RESULT", None)
    calls = {"spawn": 0, "exit": 0}
    monkeypatch.setattr(setup_api, "_spawn_relauncher", lambda *a, **k: calls.__setitem__("spawn", calls["spawn"] + 1) or True)
    monkeypatch.setattr(setup_api, "_schedule_exit", lambda *a, **k: calls.__setitem__("exit", calls["exit"] + 1))
    monkeypatch.setattr(setup_api, "_supervisor", lambda: "start.bat")
    monkeypatch.delenv("ASSISTANT_TEST", raising=False)
    monkeypatch.delenv("JARVIS_TEST", raising=False)
    return calls


def test_restart_is_honest_and_idempotent(restart_state):
    first = _client().post("/api/setup/restart").json()
    assert first["ok"] is True
    assert first.get("manual") is not True
    assert restart_state["spawn"] + restart_state["exit"] >= 1
    second = _client().post("/api/setup/restart").json()
    assert second["already"] is True, "второй клик не должен плодить процессы"
    assert restart_state["spawn"] == first.get("_spawns", restart_state["spawn"])
    assert second["how"] == first["how"]


def test_restart_refuses_to_kill_the_test_process(restart_state):
    """Под тестами (ASSISTANT_TEST=1) ядро не перезапускаем — честно говорим «вручную»."""
    import os
    os.environ["ASSISTANT_TEST"] = "1"
    try:
        body = _client().post("/api/setup/restart").json()
    finally:
        os.environ.pop("ASSISTANT_TEST", None)
    assert body["ok"] is False
    assert body["manual"] is True and body["detail"]


def test_restart_without_launcher_says_manual(monkeypatch):
    """Запуск не через run.py (uvicorn/wsgi/тест) — перезапуск себе не вернуть:
    говорим правду, а не изображаем перезапуск."""
    monkeypatch.setattr(setup_api, "_RESTART_RESULT", None)
    monkeypatch.setattr(setup_api, "_relaunch_argv", lambda: None)
    monkeypatch.delenv("ASSISTANT_TEST", raising=False)
    monkeypatch.delenv("JARVIS_TEST", raising=False)
    body = _client().post("/api/setup/restart").json()
    assert body["ok"] is False and body["manual"] is True


# ============================ 10. мастер и редирект /setup ============================
def test_redirect_to_setup_stops_after_wizard(cfg_file):
    """КРИТИЧНО: до мастера любой путь редиректится на /setup, после — перестаёт."""
    c = _client()
    r = c.get("/", follow_redirects=False)
    assert r.status_code in (302, 307), f"до мастера ждали редирект на /setup, получили {r.status_code}"
    assert r.headers["location"].endswith("/setup")
    c.post("/api/setup/save", json={"changes": {"brain.mode": "hybrid", "setup.done": True}})
    r2 = c.get("/", follow_redirects=False)
    assert r2.status_code == 200, f"после мастера / отдал {r2.status_code} (редирект на /setup не должен срабатывать)"


def test_wizard_page_is_served_locally(cfg_file):
    r = _client().get("/setup", follow_redirects=False)
    assert r.status_code == 200
    assert "/api/setup/state" in r.text