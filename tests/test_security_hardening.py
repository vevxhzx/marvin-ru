"""Укрепление безопасности и приватности (пункты 1–9 доработки).

Что проверяется:
  1. лимит запросов к чату для не-loopback клиентов (429 с JSON) и его выключение настройкой;
  2. `POST /api/backups/restore` и скачивание бэкапа — только с самого компьютера;
  3. в `/api/settings` секрет отдаётся только как «задан»/«не задан», без кусков ключа;
  4. секреты из окружения (CLOUD_API_KEY, GOOGLE_*, ASSISTANT_API_TOKEN) важнее config.yaml;
  5. обезличивание перед облаком включено по умолчанию, в том числе в режиме cloud;
  6. размер тела запроса ограничен (413 с JSON, а не чтение мегабайтов в память);
  7. потолок SSE-подписчиков на адрес (старые отвязываются);
  8. лимит попыток Telegram-входа нельзя обойти подстановкой X-Forwarded-For;
  9. CORS-preflight отвечает до авторизации, авторизация от этого не слабеет.

Всё офлайн: временная БД (fixture `fresh_db` из tests/test_core) и временные config.yaml.
Секреты в тестах только выдуманные или сгенерированные на лету — их значения нигде не печатаются.
"""
from __future__ import annotations

import asyncio
import json as _json
import os
import secrets as _secrets
from types import SimpleNamespace

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402
from tests.test_core import fresh_db  # noqa: E401,F401  (autouse: временная БД)


def _client(remote: bool = False, **kw):
    from fastapi.testclient import TestClient
    from core.api.app import app
    kw.setdefault("base_url", "http://testserver")
    kw.setdefault("client", ("192.168.1.50", 5555) if remote else ("127.0.0.1", 5555))
    return TestClient(app, **kw)


def _app_mod():
    from core.api import app as app_mod   # модуль core/api/app.py (не объект FastAPI)
    return app_mod


@pytest.fixture(autouse=True)
def _clean_chat_rate():
    """Лимит чата живёт в памяти процесса — между тестами сбрасываем, чтобы не влиять друг на друга."""
    _app_mod().reset_chat_rate()
    yield
    _app_mod().reset_chat_rate()


# ---------------------------------------------------------------- 1. лимит запросов к чату
def test_chat_rate_limit_blocks_remote_client():
    mod = _app_mod()
    c = _client(remote=True)
    codes = [c.post("/api/chat", json={"text": "привет"}).status_code for _ in range(mod.CHAT_RATE_LIMIT + 1)]
    # до лимита — обычный отказ за отсутствием ключа (авторизация не ослаблена), после — 429
    assert codes[:-1] == [401] * mod.CHAT_RATE_LIMIT, f"до лимита ожидались 401, получено {set(codes[:-1])}"
    assert codes[-1] == 429
    r = c.post("/api/chat", json={"text": "привет"})
    assert r.status_code == 429
    body = r.json()
    assert "detail" in body and "минут" in body["detail"], "429 должен приходить с понятным JSON"
    assert r.headers.get("retry-after")
    # стрим — под тем же лимитом
    assert c.post("/api/chat/stream", json={"text": "привет"}).status_code == 429
    # чужие пути лимит не трогает
    assert c.get("/api/tasks").status_code == 401


def test_chat_rate_limit_skips_loopback():
    """Свой ПК (loopback) — без лимита: 35 запросов подряд не дают ни одного 429."""
    mod = _app_mod()
    c = _client()
    for _ in range(mod.CHAT_RATE_LIMIT + 5):
        # тело намеренно битое: запрос не доходит до мозга, но проходит через middleware
        r = c.post("/api/chat", content=b"\x00" + "не json".encode(),
                   headers={"content-type": "application/json"})
        assert r.status_code == 422, f"loopback не должен попадать под лимит, получено {r.status_code}"


def test_chat_rate_limit_can_be_switched_off(monkeypatch):
    """api.rate_limit_chat: false — лимит выключается (по умолчанию он включён, это защита)."""
    mod = _app_mod()
    monkeypatch.setattr(mod.cfg, "api", SimpleNamespace(rate_limit_chat=False), raising=False)
    c = _client(remote=True)
    codes = [c.post("/api/chat", json={"text": "x"}).status_code for _ in range(mod.CHAT_RATE_LIMIT + 5)]
    assert 429 not in codes, "при api.rate_limit_chat: false лимит не должен срабатывать"


# ---------------------------------------------------------------- 2. бэкапы — только с ПК
def test_backups_restore_and_download_are_local_only():
    from core.api import auth
    tok = {"X-Auth-Token": auth.token()}
    name = {"name": "backup-nope.db"}          # выдуманное имя: до настоящего восстановления не доходит
    # снаружи даже с валидным ключом — 403 (операция только с самого компьютера)
    assert _client(remote=True).post("/api/backups/restore", json=name, headers=tok).status_code == 403
    assert _client(remote=True).get("/api/backups/backup-nope.db/download", headers=tok).status_code == 403
    # снаружи без ключа — обычный 401, как у остальных чувствительных маршрутов
    assert _client(remote=True).post("/api/backups/restore", json=name).status_code == 401
    assert _client(remote=True).get("/api/backups/backup-nope.db/download").status_code == 401
    # с самого ПК запрос доходит до роута (имя не найдено → ошибка валидации, база не трогается)
    r = _client().post("/api/backups/restore", json=name)
    assert r.status_code in (400, 404, 422), f"локальный restore дошёл до роута с {r.status_code}"


# ---------------------------------------------------------------- 3. маска секрета в /api/settings
def test_settings_secret_mask_is_only_set_state(tmp_path, monkeypatch):
    from core import config
    secret = "QA77" + _secrets.token_urlsafe(16)   # выдуманный ключ; его значение не печатаем
    p = tmp_path / "config.yaml"
    p.write_text("setup:\n  done: true\n"
                 "assistant:\n  name: 'Марвин'\n"
                 f"telegram:\n  token: '{secret}'\n  owner_id: 1\n"
                 "brain:\n  mode: local\n"
                 "google:\n  client_id: 'x'\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG", str(p))

    data = config.read_settings()
    items = {i["key"]: i for i in data["items"]}
    tok = items["telegram.token"]
    assert tok["secret"] and tok["set"] is True
    assert tok["value"] == "задан", "секрет должен отдаваться только как «задан» — без кусков ключа"
    dump = _json.dumps(data, ensure_ascii=False)
    assert secret not in dump and "QA77" not in dump, "/api/settings выдал кусок секрета"
    # незаполненный секрет — «не задан», а обычные поля показываются как есть
    assert items["google.client_secret"]["value"] == "не задан" and items["google.client_secret"]["set"] is False
    assert items["assistant.name"]["value"] == "Марвин"
    # фронт шлёт полученную маску обратно — настоящий ключ не затирается
    assert config.write_settings({"telegram.token": tok["value"],
                                  "google.client_secret": items["google.client_secret"]["value"]}) == []
    assert secret in p.read_text(encoding="utf-8"), "маска вместо значения стёрла настоящий токен"


# ---------------------------------------------------------------- 4. секреты из окружения
def test_env_overrides_config_for_secrets(tmp_path, monkeypatch):
    from core import config
    names = ("CLOUD_API_KEY", "GOOGLE_CLIENT_SECRET", "GOOGLE_CLIENT_ID", "ASSISTANT_API_TOKEN", "JARVIS_API_TOKEN")
    for n in names:
        monkeypatch.delenv(n, raising=False)     # вдруг заданы в системе — тест должен быть детерминирован
    p = tmp_path / "config.yaml"
    p.write_text("brain:\n  mode: local\n  cloud:\n    api_key: 'file-key'\n"
                 "google:\n  client_id: 'file-id'\n"
                 "voice:\n  pc:\n    api_token: 'file-token'\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG", str(p))

    node = config._load()
    assert node.brain.cloud.api_key == "file-key" and node.google.client_id == "file-id"

    vals = {n: _secrets.token_urlsafe(16) for n in names}   # значения — только на лету, в код/логи не идут
    for n, v in vals.items():
        monkeypatch.setenv(n, v)
    node = config._load()
    assert node.brain.cloud.api_key == vals["CLOUD_API_KEY"]
    assert node.google.client_secret == vals["GOOGLE_CLIENT_SECRET"]
    assert node.google.client_id == vals["GOOGLE_CLIENT_ID"]
    assert node.voice.pc.api_token == vals["ASSISTANT_API_TOKEN"]
    # /api/settings читает файл, а не окружение: значений там по-прежнему нет
    dump = _json.dumps(config.read_settings(), ensure_ascii=False)
    assert all(v not in dump for v in vals.values())


# ---------------------------------------------------------------- 5. анонимайзер по умолчанию включён
def test_anonymize_defaults_on_and_false_is_respected(tmp_path, monkeypatch):
    from core import config
    p = tmp_path / "config.yaml"
    p.write_text("brain:\n  mode: cloud\n", encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG", str(p))
    assert config._load().brain.gemini.anonymize is True      # ключа в файле нет — включено
    # read_settings показывает эффективное значение (дефолт), а не пустое поле
    items = {i["key"]: i for i in config.read_settings()["items"]}
    assert items["brain.gemini.anonymize"]["value"] is True
    p.write_text("brain:\n  mode: cloud\n  gemini:\n    anonymize: false\n", encoding="utf-8")
    assert config._load().brain.gemini.anonymize is False     # явный false уважается
    items = {i["key"]: i for i in config.read_settings()["items"]}
    assert items["brain.gemini.anonymize"]["value"] is False


def test_cloud_mode_anonymizes_by_default(monkeypatch):
    """Режим cloud больше не отключает обезличивание: личные данные не уходят открытым текстом."""
    from core.brain import llm
    from core.config import cfg
    captured: dict = {}

    class _R:
        status_code = 200
        text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return {"choices": [{"message": {"content": "готово"}}]}

    async def fake_post(path, body, headers, timeout=45):
        captured.clear()
        captured.update(body)
        return _R()

    async def fake_model(*a, **k):
        return "groq/llama-3.3-70b"

    monkeypatch.setattr(llm, "MODE", "cloud")
    monkeypatch.setattr(llm, "CLOUD_PROVIDER", "groq")
    monkeypatch.setattr(llm, "CLOUD_KEY", "k")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)
    monkeypatch.setattr(llm, "_cloud_post", fake_post)
    monkeypatch.setattr(llm, "resolve_cloud_model", fake_model)
    monkeypatch.setattr(cfg.brain.gemini, "anonymize", True, raising=False)

    text = "пароль от вайфая qwerty123 запомни"
    assert asyncio.run(llm.cloud_chat("sys", text)) == "готово"
    sent = captured["messages"][-1]["content"]
    assert "qwerty123" not in sent and "[скрыто]" in sent, "в режиме cloud текст ушёл открытым текстом"

    monkeypatch.setattr(cfg.brain.gemini, "anonymize", False)   # явный false — право пользователя
    assert asyncio.run(llm.cloud_chat("sys", text)) == "готово"
    assert captured["messages"][-1]["content"] == text


# ---------------------------------------------------------------- 6. лимит размера тела
def _raw_post(path: str, headers: dict, body: bytes = b"", client=("127.0.0.1", 5555)):
    """Сырой ASGI-POST: тело отправляем целиком (обычно очень короткое), а размер задаём заголовком.

    Так проверяется ранний отказ по Content-Length: приложение не должно и пытаться читать
    «9 МБ», которых в сообщении нет. Возврат — (статус, тело)."""
    import asyncio as _aio

    from core.api.app import app

    hdrs = [(k.lower().encode(), str(v).encode()) for k, v in headers.items()]
    scope = {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1", "method": "POST", "scheme": "http",
        "path": path, "raw_path": path.encode("ascii", "replace"),
        "query_string": b"", "root_path": "", "headers": hdrs,
        "client": client, "server": ("testserver", 80),
    }
    state = {"status": 0, "body": b"", "sent": False}

    async def receive(*_a, **_k):
        if not state["sent"]:
            state["sent"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        await _aio.Event().wait()

    async def send(msg):
        if msg["type"] == "http.response.start":
            state["status"] = msg["status"]
        elif msg["type"] == "http.response.body":
            state["body"] += msg.get("body", b"")

    async def run():
        await _aio.wait_for(app(scope, receive, send), timeout=15)

    _aio.run(run())
    return state["status"], state["body"]


def test_body_size_limit_json_and_multipart():
    mb = 1024 * 1024
    # JSON больше лимита — сразу 413 с понятным JSON, тело не читается
    st, body = _raw_post("/api/tasks", {"content-type": "application/json", "content-length": 9 * mb}, b"{}")
    assert st == 413 and _json.loads(body)["detail"]
    # multipart (загрузка файла в mind/boards/финансы) — отдельный, больший лимит
    st, body = _raw_post("/api/boards/1/asset",
                         {"content-type": "multipart/form-data; boundary=x", "content-length": 26 * mb})
    assert st == 413 and _json.loads(body)["detail"]
    # обычный размер доходит до валидации (не 413)
    st, _ = _raw_post("/api/tasks", {"content-type": "application/json", "content-length": 100}, b"{}")
    assert st in (400, 422), f"нормальное тело не должно отклоняться лимитом, получено {st}"


# ---------------------------------------------------------------- 7. потолок SSE-подписчиков
def test_sse_subscribers_capped_per_address():
    from starlette.requests import Request

    from core.api import _shared
    from core.api.app import SSE_MAX_PER_IP, stream

    scope = {"type": "http", "method": "GET", "path": "/api/events/stream",
             "headers": [], "query_string": b"", "client": ("10.77.0.9", 4242)}
    req = Request(scope)

    async def scenario():
        before = set(_shared._subscribers)
        gens = []
        for _ in range(SSE_MAX_PER_IP + 1):        # на один адрес больше потолка
            resp = await stream(request=req)
            gen = resp.body_iterator
            await gen.__anext__()                  # retry: 3000 — поток стартовал
            gens.append(gen)
        opened = set(_shared._subscribers) - before
        assert len(opened) == SSE_MAX_PER_IP, f"подписчиков должно быть ровно {SSE_MAX_PER_IP}, открыто {len(opened)}"
        # вытесненное (самое старое) подключение закрывается при следующем чтении
        with pytest.raises(StopAsyncIteration):
            await gens[0].__anext__()
        # остальные закрываем тестом — после этого утечки быть не должно
        for gen in gens[1:]:
            await gen.aclose()
        assert set(_shared._subscribers) == before, "после закрытия потоков подписчики остались"
        assert "10.77.0.9" not in _app_mod()._sse_by_ip

    asyncio.run(scenario())


# ---------------------------------------------------------------- 8. брутфорс Telegram-входа
def _tg_request(host: str, xff: str | None = None):
    from starlette.requests import Request
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "method": "POST", "path": "/api/tg/login",
                    "headers": headers, "query_string": b"", "client": (host, 5555)})


def test_tg_login_client_key_ignores_forwarded_from_non_proxy():
    from core.api import tg_auth
    # чужой хост прислал X-Forwarded-For — ключом остаётся реальный адрес соединения
    assert tg_auth._client_key(_tg_request("192.168.1.50", "198.51.100.7")) == "192.168.1.50"
    # прокси на этом же ПК (loopback) — его XFF доверяем
    assert tg_auth._client_key(_tg_request("127.0.0.1", "198.51.100.7")) == "198.51.100.7"
    # пустой заголовок не создаёт пустых ключей
    tg_auth.reset_limits()
    assert tg_auth.login_allowed(_tg_request("10.20.30.40")) is True
    assert len(tg_auth._fails) == 0, "заход без провала не должен оставлять пустой слот в _fails"
    # попытки старше окна выкидываются вместе с опустевшим ключом
    old = 1_000_000.0
    tg_auth.login_failed(_tg_request("10.20.30.40"), "тест", now=old)
    assert tg_auth.login_allowed(_tg_request("10.20.30.40"), now=old + tg_auth.TG_LOGIN_WINDOW + 1) is True
    assert len(tg_auth._fails) == 0, "истёкший ключ должен удаляться, а не копиться"


def test_tg_login_xff_spoof_does_not_get_new_slots():
    """Подстановка X-Forwarded-For не даёт новых «слотов»: все провалы считаются по реальному адресу."""
    from core.api import tg_auth
    tg_auth.reset_limits()
    c = _client(remote=True)
    try:
        for i in range(tg_auth.TG_LOGIN_BURST):
            r = c.post("/api/tg/login", json={"init_data": ""}, headers={"X-Forwarded-For": f"198.51.100.{i}"})
            assert r.status_code == 403 and "попыток" not in r.json()["detail"], "лимит не должен сработать раньше"
        # восьмая попытка с новым «чистым» адресом в заголовке всё равно блокируется
        r = c.post("/api/tg/login", json={"init_data": ""}, headers={"X-Forwarded-For": "198.51.100.99"})
        assert r.status_code == 403 and "попыток" in r.json()["detail"], "XFF позволил обойти лимит попыток"
    finally:
        tg_auth.reset_limits()


# ---------------------------------------------------------------- 9. порядок middleware / CORS
def test_cors_preflight_answered_before_auth():
    c = _client(remote=True)   # без ключа: префлайт не должен получать 401
    r = c.options("/api/chat", headers={"origin": "http://localhost:5173",
                                        "access-control-request-method": "POST",
                                        "access-control-request-headers": "content-type"})
    assert r.status_code == 200, f"preflight от dev-стенда получил {r.status_code}"
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    # чужой origin заголовков CORS не получает
    r2 = c.options("/api/chat", headers={"origin": "http://evil.example",
                                         "access-control-request-method": "POST"})
    assert "access-control-allow-origin" not in r2.headers
    # авторизация от перестановки не ослабла: обычный запрос с чужого сайта — 403 (CSRF), без ключа — 401
    assert c.post("/api/chat", json={"text": "x"},
                  headers={"origin": "http://evil.example"}).status_code == 403
    assert c.post("/api/chat", json={"text": "x"}).status_code == 401
