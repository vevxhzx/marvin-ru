"""Ревью A «API и безопасность» — часть 1: защита эндпоинтов и секреты в ответах.

Проверяет роуты, перенесённые в `core/api/routers/*` (Фаза 7), и обвязку в
`core/api/app.py` / `core/api/auth.py`:

* удалённый клиент без ключа не читает и не меняет чувствительные `/api/*` (401),
* «только с этого компьютера» маршруты (`/api/phone*`, `/api/setup*`) отклоняются
  даже С валидным ключом (403),
* секреты из config.yaml маскируются в ответах и не попадают в `/api/status`,
* обходы каталога (traversal) не читают файлы вне `web/site`.

Фикстура `fresh_db` (tests/test_core) гоняет всё на временной БД в tmp_path;
config подменяется на временный файл через JARVIS_CONFIG — `config.yaml` и
`data/jarvis.db` на запись не открываются.
"""
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402
from tests.test_core import fresh_db  # noqa: E401,F401  (autouse: временная БД)

# Чувствительные GET — чужой клиент без ключа должен получать 401.
REMOTE_GET_401 = [
    "/api/diagnose",          # самодиагностика (бывш. «/diag»)
    "/api/status",
    "/api/state",
    "/api/settings",
    "/api/dashboard",
    "/api/runs",
    "/api/runs/report",
    "/api/backups",
    "/api/tg/miniapp",
    "/api/chat/history",
    "/api/pc/organize/log",
    "/api/pc/organize/preview",
    "/api/finance/summary",
    "/api/export/all.json",
    "/api/orders",
    "/api/boards",
    "/api/people",
    "/api/notes",
    "/api/tasks",
    "/api/events",
    "/api/google/status",
    "/api/google/connect",
    "/api/events/stream",     # SSE
    "/api/cards/nope.png",
]

# Меняющие состояние POST/PUT — тоже 401 снаружи без ключа.
REMOTE_WRITE_401 = [
    ("POST", "/api/chat", {"text": "привет"}),
    ("PUT", "/api/settings", {"changes": {"persona.style": "neutral"}}),
    ("POST", "/api/backup", None),
    ("POST", "/api/backups/restore", {"name": "backup-x.db"}),
    ("POST", "/api/pc/launch", {"restart": False}),
    ("POST", "/api/game", {"on": True}),
    ("POST", "/api/google/disconnect", None),
    ("POST", "/api/finance/transactions", {"amount": 100}),
    ("POST", "/api/orders", {"title": "x"}),
    ("POST", "/api/undo", None),
    ("POST", "/api/tg/logout", None),
    ("PUT", "/api/ui-prefs", {"prefs": {"theme": "dark"}}),
]

# Только с самого компьютера — даже с валидным ключом (403).
LOCAL_ONLY = [
    ("GET", "/api/phone", None),            # в ссылках зашит ключ доступа
    ("POST", "/api/phone/rotate", None),    # ротация ключа
    ("GET", "/api/setup/state", None),
    ("GET", "/setup", None),
]


def _client(remote: bool = False):
    from fastapi.testclient import TestClient
    from core.api.app import app
    return TestClient(app, client=("192.168.1.50", 5555) if remote else ("127.0.0.1", 5555),
                      base_url="http://testserver")


def _headers():
    from core.api import auth
    return {"X-Auth-Token": auth.token()}


# Маркер файла `<корень репозитория>/config.example.yaml`: в собранном бандле
# web/site его нет (проверено grep'ом), поэтому по нему видно, утек ли файл.
_REPO_FILE_MARKER = "name_latin"


def _raw_get(path: str, remote: bool = False, timeout: float = 20.0):
    """Сырой ASGI-GET с произвольным scope['path'] → (status, body).

    TestClient/httpx нормализует dot-сегменты в URL ещё до отправки, поэтому
    обходы каталога иначе не воспроизвести. Uvicorn же разбирает сырую строку
    запроса и делает только `unquote`, БЕЗ нормализации `..`
    (uvicorn/protocols/http/httptools_impl.py:256-264) — в scope['path'] до
    приложения остаётся ровно '/../../config.example.yaml'.
    """
    import asyncio

    from core.api.app import app

    host = "192.168.1.50" if remote else "127.0.0.1"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii", "replace"),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": (host, 5555),
        "server": ("testserver", 80),
    }
    state = {"status": 0, "body": b"", "calls": 0}

    async def receive(*_a, **_k):
        # первый вызов — пустое тело запроса, дальше ждём «отключения» клиента
        state["calls"] += 1
        if state["calls"] == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        if message["type"] == "http.response.start":
            state["status"] = message["status"]
        elif message["type"] == "http.response.body":
            state["body"] += message.get("body", b"")

    async def run():
        await app(scope, receive, send)

    asyncio.run(asyncio.wait_for(run(), timeout))
    return state["status"], state["body"]


def _cfg_get(dotpath: str):
    from core import config
    # значения из реально загруженного config.yaml — ищем их в ответах, но НИКОГДА не печатаем
    node = config.cfg
    for part in dotpath.split("."):
        node = getattr(node, part, None)
        if node is None:
            return ""
    return str(node or "")


def _leaks_secret(text: str) -> bool:
    """Есть ли в ответе целиком хотя бы один известный секрет (значения не логируются)."""
    needles = [SECRET_TOKEN, SECRET_GOOGLE, "CLOUDsuperSECRETkeyVALUE", "GEMsuperSECRETkeyVALUE",
               _cfg_get("telegram.token"), _cfg_get("google.client_secret"),
               _cfg_get("brain.cloud.api_key"), _cfg_get("brain.gemini.api_key")]
    return any(n and n in text for n in needles)


@pytest.mark.parametrize("path", REMOTE_GET_401)
def test_remote_get_without_key_401(path):
    assert _client(remote=True).get(path).status_code == 401


@pytest.mark.parametrize("method,path,body", REMOTE_WRITE_401)
def test_remote_write_without_key_401(method, path, body):
    r = _client(remote=True).request(method, path, json=body)
    assert r.status_code == 401, f"{method} {path} без ключа отдал {r.status_code}"


@pytest.mark.parametrize("method,path,body", LOCAL_ONLY)
def test_local_only_rejects_remote_even_with_token(method, path, body):
    r = _client(remote=True).request(method, path, json=body, headers=_headers())
    assert r.status_code == 403, f"{path} с ключа снаружи — {r.status_code}, а нужен 403"


def test_public_surface_is_tiny():
    """Публично только /api/health и манифест; данные — только с ключом."""
    c = _client(remote=True)
    assert c.get("/api/health").status_code == 200
    assert c.get("/manifest.json").status_code == 200
    assert c.get("/api/tasks").status_code == 401
    assert c.get("/media/x.png").status_code == 401


def test_loopback_can_work_without_key():
    c = _client()
    assert c.get("/api/tasks").status_code == 200
    assert c.get("/api/settings").status_code == 200


# ---------------- секреты в ответах ----------------
SECRET_TOKEN = "777000123456:AAFsuperSECRETtokenVALUE"
SECRET_GOOGLE = "GOCSPX-superSECRETgoogleVALUE"

SECRET_CONFIG = f"""setup:
  done: true
telegram:
  token: '{SECRET_TOKEN}'
  owner_id: 1
brain:
  mode: local
  ollama:
    url: 'http://127.0.0.1:11434'
    model: ''
  cloud:
    api_key: 'CLOUDsuperSECRETkeyVALUE'
  gemini:
    api_key: 'GEMsuperSECRETkeyVALUE'
google:
  client_id: '123.apps.googleusercontent.com'
  client_secret: '{SECRET_GOOGLE}'
"""


@pytest.fixture
def secret_config(tmp_path, monkeypatch):
    """Временный config.yaml с заведомо секретными значениями (настоящий не трогаем)."""
    p = tmp_path / "config.yaml"
    p.write_text(SECRET_CONFIG, encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG", str(p))
    return p


def test_settings_masks_secrets(secret_config):
    """GET /api/settings отдаёт маску, а не сырой ключ (для всех секретных ключей)."""
    r = _client().get("/api/settings")
    assert r.status_code == 200
    body = r.text
    for raw in (SECRET_TOKEN, SECRET_GOOGLE, "CLOUDsuperSECRETkeyVALUE", "GEMsuperSECRETkeyVALUE"):
        assert raw not in body, f"GET /api/settings отдал секрет целиком: {raw[:6]}…"
    # маска: первые 4 символа + … + последние 3
    assert SECRET_TOKEN[:4] + "…" in body
    assert SECRET_GOOGLE[:4] + "…" in body
    assert not _leaks_secret(body), "GET /api/settings отдал сырой секрет из config.yaml"


def test_settings_put_mask_does_not_wipe_secret(secret_config):
    """Отправка маски обратно (фронт шлёт то, что получил) не затирает настоящий ключ."""
    c = _client()
    masked = SECRET_TOKEN[:4] + "…" + SECRET_TOKEN[-3:]
    r = c.put("/api/settings", json={"changes": {"telegram.token": masked}})
    assert r.status_code == 200
    assert SECRET_TOKEN in secret_config.read_text(encoding="utf-8"), \
        "маска вместо значения стёрла настоящий токен в config.yaml"


def test_status_and_llm_do_not_leak_keys(secret_config):
    """/api/status и /api/llm — состояние без сырых ключей."""
    c = _client()
    for path in ("/api/status", "/api/llm"):
        r = c.get(path)
        assert r.status_code == 200
        assert not _leaks_secret(r.text), f"{path} отдал сырой ключ из config.yaml"


def test_diagnose_does_not_leak_keys(secret_config, monkeypatch):
    """Самодиагностика: даже если облако упало, в ответе нет ключа — только обрезанная ошибка."""
    import core.services.health as health

    async def fake_diagnose():
        return {"ok": True, "items": [], "text": "ok", "at": "2026-10-01T00:00:00"}

    monkeypatch.setattr(health, "diagnose", fake_diagnose)
    r = _client().get("/api/diagnose")
    assert r.status_code == 200
    assert not _leaks_secret(r.text), "/api/diagnose отдал сырой ключ"


def test_export_does_not_leak_config_secrets(secret_config):
    """/api/export/* выгружает БД, а не config.yaml — ключей настроек там быть не должно."""
    r = _client().get("/api/export/transactions.json")
    assert r.status_code == 200
    assert not _leaks_secret(r.text), "/api/export отдал сырой ключ из config.yaml"


# ---------------- обходы каталога ----------------
def test_media_traversal_blocked():
    """`/media/*` резолвит путь и проверяет, что он остался внутри MEDIA_DIR.

    Это эталон правильной защиты: сервер доставляет `..` в scope['path'] как есть,
    а обработчик их отсекает.
    """
    for p in ("/media/../config.example.yaml", "/media/../../config.example.yaml"):
        status, body = _raw_get(p)
        assert status == 404, f"{p} -> {status}, а нужен 404"
        assert _REPO_FILE_MARKER not in body.decode("utf-8", "replace"), \
            f"{p} отдал файл из корня репозитория"
    # снаружи /media/* вообще закрыт без ключа
    assert _raw_get("/media/../../config.example.yaml", remote=True)[0] == 401


def test_card_traversal_blocked():
    """`/api/cards/{name}` не отдаёт файлы вне кэша карточек (и не читает корень).

    Пути проверяются в сыром виде: uvicorn декодирует %2f, но `..` не схлопывает.
    """
    paths = (
        "/api/cards/../../config.example.yaml",
        "/api/cards/..%2f..%2fconfig.example.yaml",
        "/api/cards/%2e%2e%2fconfig.example.yaml",
        "/api/cards/%2e%2e/%2e%2e/config.example.yaml",
    )
    for p in paths:
        status, body = _raw_get(p)
        text = body.decode("utf-8", "replace")
        assert _REPO_FILE_MARKER not in text, f"{p} отдал файл из корня репозитория"
        # 404 от роута/спа — ок; 200 допустим только как SPA fallback (index.html)
        if status == 200:
            assert text.lstrip().lower().startswith("<!doctype html"), \
                f"{p} -> 200 не из index.html"


@pytest.mark.xfail(reason="P0: SPA catch-all в core/api/app.py (spa(): "
                          "`f = web_dist / path; if path and f.is_file()`) не проверяет "
                          "resolve() — путь '/../../config.example.yaml' читает файл корня "
                          "репозитория, путь не '/api/' → AuthMiddleware считает его публичным",
                   strict=False)
def test_spa_catchall_does_not_serve_files_outside_webdist(tmp_path, monkeypatch):
    """Catch-all `/{path:path}` должен отдавать только файлы внутри web/site.

    Сырой GET '/../../config.example.yaml' (как шлёт `curl --path-as-is`) не должен
    превращаться в чтение файла из корня репозитория: это обход и AuthMiddleware
    (путь не /api/ → публичный), и зоны статики.
    """
    cfg = tmp_path / "config.yaml"
    cfg.write_text(SECRET_CONFIG, encoding="utf-8")
    monkeypatch.setenv("JARVIS_CONFIG", str(cfg))  # setup.done=true → spa() не редиректит в /setup

    status, body = _raw_get("/../../config.example.yaml", remote=True)
    text = body.decode("utf-8", "replace")
    assert not (status == 200 and _REPO_FILE_MARKER in text), \
        f"catch-all отдал файл корня репозитория снаружи без ключа: {status}"
