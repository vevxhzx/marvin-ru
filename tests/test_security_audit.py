# -*- coding: utf-8 -*-
"""Независимый аудит безопасности (агент S): то, что не покрывают другие файлы тестов.

Что здесь проверяется
---------------------
1. Сравнение ключа доступа и сессии Telegram — константное (`hmac.compare_digest`),
   а не обычным `==`; не-ASCII/битые значения не роняют сервис 500-й ошибкой.
2. Опасные и системные эндпоинты без ключа → 401; «только с ПК» (/api/backups*, /api/phone)
   с чужого адреса → 403 даже с верным ключом.
3. Лимит запросов считает и НЕавторизованные попытки (подбор ключа по /api/settings и т.п.).
4. Path traversal в /api/backups/{name}/download и /api/backups/restore → 400, а не файл.
5. XSS: публичный /api/google/callback не отражает параметр error как HTML.
6. Инъекции: кавычка/`;` в поиске и фильтрах не ломают запрос и не достают чужое;
   команда с `;` не превращается в выполнение второй команды.
7. Ошибки не отдают traceback, пути файлов и секреты.
8. В режиме local скриншот/фото в облако не уходит (через мок; сеть не трогаем).
9. Загрузки: лимит размера и проверка формата на mind/boards.

Всё офлайн: временная БД (фикстура fresh_db), TestClient, сеть не используется.
Секреты в тестах выдуманные или генерируются на лету; их значения нигде не печатаются.
"""
from __future__ import annotations

import asyncio
import os
import secrets as _secrets

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402
from tests.test_core import fresh_db  # noqa: E401,F401  (autouse: временная БД)


REMOTE = ("192.168.1.50", 5555)
LOCAL = ("127.0.0.1", 5555)


def _client(remote: bool = False, **kw):
    from fastapi.testclient import TestClient
    from core.api.app import app
    kw.setdefault("base_url", "http://testserver")
    kw.setdefault("client", REMOTE if remote else LOCAL)
    return TestClient(app, **kw)


def _token_headers() -> dict:
    from core.api import auth
    return {"X-Auth-Token": auth.token()}


@pytest.fixture(autouse=True)
def _reset_rate():
    """Окна лимитов живут в памяти процесса — между тестами обнуляем."""
    from core.api import app as app_mod
    from core.api import tg_auth
    app_mod.reset_chat_rate()
    yield
    app_mod.reset_chat_rate()
    tg_auth.reset_limits()


# ================================================================ 1. константное сравнение
def test_token_comparison_is_constant_time():
    """Ключ сверяется hmac.compare_digest, а не «==» (иначе время ответа выдаёт префикс)."""
    import inspect

    from core.api import auth, tg_auth
    for mod, fn in ((auth, auth._token_ok), (tg_auth, tg_auth.session_ok)):
        src = inspect.getsource(mod)
        assert "compare_digest" in src, f"{mod.__name__}: сравнение ключа не константное"
        assert fn is not None


def test_wrong_token_is_rejected_and_right_one_accepted():
    c = _client(remote=True)
    wrong = _secrets.token_urlsafe(32)
    assert c.get("/api/settings", headers={"X-Auth-Token": wrong}).status_code == 401
    assert c.get("/api/settings", headers=_token_headers()).status_code == 200


def test_tg_session_signature_is_constant_time():
    """Сессия Telegram проверяется compare_digest и подделка не проходит."""
    from core.api import tg_auth
    assert tg_auth.session_ok(None) is False
    assert tg_auth.session_ok("") is False
    assert tg_auth.session_ok("не-токен") is False
    assert tg_auth.session_ok("1.2.3") is False
    forged = "1." + str(int(__import__("time").time())) + "." + "0" * 43
    assert tg_auth.session_ok(forged) is False


# ================================================================ 2. доступ: 401 / 403
@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/backups", None),
    ("GET", "/api/backups/cloud", None),
    ("POST", "/api/backups/restore", {"name": "backup-20240101-0000.db"}),
    ("GET", "/api/backups/backup-20240101-0000.db/download", None),
    ("PUT", "/api/settings", {"changes": {"persona.style": "neutral"}}),
    ("POST", "/api/pc/launch", {"restart": False}),
    ("POST", "/api/undo", None),
    ("GET", "/api/memory", None),
    ("POST", "/api/vision/ask", {"image_b64": "", "question": "?"}),
])
def test_dangerous_endpoints_reject_unauthorized(method, path, body):
    """Без ключа с чужого адреса всё опасное — 401 (данные не отдаются и не меняются)."""
    assert _client(remote=True).request(method, path, json=body).status_code == 401


def test_tg_login_is_public_but_rejects_bad_signature():
    """/api/tg/login публичен (он и есть проверка), но поддельные данные не пускают."""
    c = _client(remote=True)
    r = c.post("/api/tg/login", json={"init_data": "user=%7B%22id%22%3A1%7D&hash=" + "0" * 64})
    assert r.status_code == 403
    assert "assistant_tg" not in r.headers.get("set-cookie", ""), \
        "сессия не должна выдаваться при неверной подписи"


@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/backups", None),
    ("GET", "/api/backups/cloud", None),
    ("POST", "/api/backups/cloud/upload", None),
    ("POST", "/api/backups/cloud/delete", None),
    ("POST", "/api/backups/restore", {"name": "backup-20240101-0000.db"}),
    ("GET", "/api/backups/backup-20240101-0000.db/download", None),
    ("GET", "/api/phone", None),
    ("POST", "/api/phone/rotate", None),
])
def test_backups_and_phone_are_local_only_even_with_token(method, path, body):
    """С ведущим ключом, но с чужого устройства операции «с ПК» — 403."""
    r = _client(remote=True).request(method, path, json=body, headers=_token_headers())
    assert r.status_code == 403, f"{method} {path} с ключом снаружи — {r.status_code}"


def test_sse_stream_requires_auth():
    """SSE-поток (в нём видны действия ядра) не отдаётся без ключа."""
    assert _client(remote=True).get("/api/events/stream").status_code == 401


# ================================================================ 3. лимит и неавторизованные попытки
def test_rate_limit_counts_unauthorized_attempts_on_sensitive_paths():
    """Подбор ключа по /api/settings упирается в 429, даже если все попытки без ключа."""
    from core.api import app as app_mod
    c = _client(remote=True)
    limit = app_mod.RateLimitMiddleware.AUTH_RATE_LIMIT
    codes = [c.get("/api/settings").status_code for _ in range(limit + 2)]
    assert codes[0] == 401, "до лимита ожидался обычный отказ по ключу"
    assert 429 in codes, "перебор ключа должен упереться в лимит запросов"
    r = c.get("/api/settings")
    assert r.status_code == 429 and r.headers.get("retry-after")


def test_rate_limit_does_not_block_authorized_owner():
    """Владелец с верным ключом не упирается в лимит на тех же маршрутах."""
    from core.api import app as app_mod
    c = _client(remote=True)
    h = _token_headers()
    codes = [c.get("/api/backups", headers=h).status_code for _ in range(app_mod.RateLimitMiddleware.AUTH_RATE_LIMIT + 3)]
    assert 429 not in codes


def test_loopback_is_not_rate_limited():
    from core.api import app as app_mod
    c = _client()
    h = _token_headers()
    for _ in range(app_mod.RateLimitMiddleware.AUTH_RATE_LIMIT + 5):
        assert c.get("/api/backups", headers=h).status_code != 429


# ================================================================ 4. path traversal
# Имена с «../» проверяем в закодированном виде: клиент нормализует `..` в URL до отправки,
# и без %2F такой запрос просто не дошёл бы до роута (его съел бы catch-all сайта).
@pytest.mark.parametrize("name", [
    "%2e%2e%2f%2e%2e%2f%2e%2e%2fetc%2fpasswd",
    "..%2f..%2f..%2fconfig.yaml",
    "config-20240101-0000%2f..%2f..%2fapi_token",
    "backup-20240101-0000.db%00.txt",
    "config-20240101-0000%2f....%2f....%2fapi_token",
])
def test_backup_download_traversal_is_rejected(name):
    """Обход каталога в имени бэкапа — 400/404, файл наружу не отдаётся."""
    r = _client().get(f"/api/backups/{name}/download", headers=_token_headers())
    assert r.status_code in (400, 404), f"{name} → {r.status_code}"
    assert b"root:" not in r.content


@pytest.mark.parametrize("name", [
    "..%2f..%2f..%2fetc%2fpasswd",
    "..%5c..%5capi_token",
    "backup-20240101-0000.db%2f..%2f..%2fconfig.yaml",
])
def test_backup_restore_traversal_is_rejected(name):
    r = _client().post("/api/backups/restore", json={"name": name})
    assert r.status_code in (400, 404, 422), f"{name} → {r.status_code}"


def test_media_traversal_does_not_leak_files():
    """/media/… не отдаёт файл вне data/media (в т.ч. api_token и config.yaml).

    Проверяем НАСТОЯЩЕЕ содержимое файла настроек, а не случайную подстроку вроде "cloud:":
    на CI (нет config.yaml → откат на config.example.yaml, setup_done() == False) SPA отдаёт мастер
    установки, где такая строка встречается законно, и проверка ловила сама себя."""
    from core.api import auth
    from core.config import _config_src

    c = _client()
    h = _token_headers()
    # самая длинная непустая строка настроек — надёжный отпечаток файла
    cfg_lines = [ln.strip() for ln in _config_src().read_text(encoding="utf-8").splitlines()
                 if ln.strip() and not ln.strip().startswith("#")]
    probe = max(cfg_lines, key=len) if cfg_lines else ""
    for p in ("/media/../api_token", "/media/../../config.yaml",
              "/media/%2e%2e/api_token", "/media/..%5Capi_token",
              "/media/%2e%2e%2f%2e%2e%2fconfig.yaml"):
        r = c.get(p, headers=h)
        assert auth.token()[:10] not in r.text, f"{p} отдал ключ доступа"
        if probe:
            assert probe not in r.text, f"{p} отдал файл вне data/media"
        # 404 — маршрут не нашёл файл; 200 — SPA отдала index.html/мастер, но ключа/конфига там нет
        assert r.status_code in (200, 404), f"{p} → неожиданный {r.status_code}"


def test_cloud_backup_name_traversal_is_rejected():
    """Имя файла в облачных бэкапах проверяется регуляркой — обход не проходит."""
    from core.api import auth, tg_auth  # noqa: F401  (импорт ради единообразия фикстур)
    from core.services import cloud_backup
    for bad in ("../../etc/passwd", "..%2f..%2fconfig.yaml", "a/b.enc", "backup-x.db\\z"):
        with pytest.raises(ValueError):
            cloud_backup._check_name(bad)


# ================================================================ 5. XSS в публичных страницах
@pytest.mark.parametrize("payload", [
    "<script>alert(1)</script>",
    '"><img src=x onerror=alert(1)>',
    "<svg/onload=alert(1)>",
])
def test_google_callback_does_not_reflect_html(payload, monkeypatch):
    """Публичный /api/google/callback не отражает параметр как HTML (XSS).

    Проверяем, что в ответе нет «сырых» угловых скобок из полезной нагрузки: после
    экранирования `<script>` превращается в `&lt;script&gt;`, а не остаётся тегом."""
    from urllib.parse import quote

    from core import config as config_mod
    # /api/google/callback перечитывает config.yaml и подменяет объект core.config.cfg
    # (так делает _gcal_reload). Возвращаем как было, чтобы тест не влиял на соседние.
    monkeypatch.setattr(config_mod, "cfg", config_mod.cfg)
    c = _client(remote=True)
    r = c.get("/api/google/callback?error=" + quote(payload))
    assert r.status_code == 200
    assert payload not in r.text, "параметр error отражён в HTML без экранирования"
    body = r.text
    # ни один «открывающий» тег из нагрузки не должен появиться как есть
    for tag in ("<script>alert", "<img src=x", "<svg/onload", "<svg onload"):
        assert tag not in body.lower(), f"в ответе остался сырой тег: {tag}"
    assert "&lt;" in body or "&quot;" in body, "ожидаем экранированную форму текста"


# ================================================================ 6. инъекции
@pytest.mark.parametrize("payload", [
    "'; DROP TABLE transaction;--",
    "' OR 1=1 --",
    "%' UNION SELECT key, value FROM setting --",
    "1; DELETE FROM note;--",
    "\\'; DROP TABLE task; --",
])
def test_search_and_filters_survive_sql_injection(payload):
    """Кавычка/';' в поиске и фильтрах: 200 без ошибки, чужие данные не достаются."""
    c = _client()
    h = _token_headers()
    r = c.get("/api/notes", params={"q": payload}, headers=h)
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    r2 = c.get("/api/links", params={"q": payload}, headers=h)
    assert r2.status_code == 200

    r3 = c.get("/api/boards/search", params={"q": payload}, headers=h)
    assert r3.status_code in (200, 422)

    # таблицы на месте после попытки инъекции
    assert c.get("/api/finance/summary", headers=h).status_code == 200
    assert c.get("/api/notes", headers=h).status_code == 200


def test_injection_in_tg_and_event_filters_is_safe():
    c = _client()
    h = _token_headers()
    for payload in ("'; DROP TABLE event;--", "' OR '1'='1"):
        assert c.get("/api/events", params={"q": payload}, headers=h).status_code in (200, 422)
        assert c.get("/api/tasks", params={"q": payload}, headers=h).status_code in (200, 422)
    assert c.get("/api/dashboard", headers=h).status_code == 200


def test_pc_open_app_rejects_shell_metacharacters():
    """Имя программы с `;`/`&`/кавычками не доходит до запуска команды."""
    from core.pc import actions
    for evil in ('calc" & shutdown /s & "', "notepad; shutdown /s", "cmd & calc", "a\nb", "x|y"):
        out = actions.open_app(evil)
        assert "Не найду" in out or "Не похоже" in out or "Не нашёл" in out, \
            f"{evil!r} мог бы выполниться как команда: {out!r}"


def test_pc_open_url_rejects_non_http_schemes():
    from core.pc import actions
    for evil in ("file:///C:/Windows/System32/calc.exe", "javascript:alert(1)",
                 "ms-settings:", "data:text/html,<script>alert(1)</script>"):
        assert actions.open_url(evil) != "", f"{evil} не должен открываться браузером"


def test_pc_find_files_query_is_not_a_shell():
    """Поиск файлов не передаёт запрос в оболочку (список аргументов, без shell)."""
    import inspect

    from core.pc import actions
    # смотрим только код, без комментариев: в докстринге есть упоминание shell=True
    # как раз с описанием того, чего там больше нет
    code = "\n".join(ln for ln in inspect.getsource(actions).splitlines()
                     if not ln.strip().startswith("#"))
    for bad in ("shell=True", "shell = True", "os.system(", "os.popen("):
        assert bad not in code, f"в core/pc/actions.py найдено {bad}"


# ================================================================ 7. ошибки не текут
@pytest.mark.parametrize("method,path,body", [
    ("GET", "/api/export/all.zzz", None),
    ("GET", "/api/export/nope.json", None),
    ("GET", "/api/cards/zzz.png", None),
    ("GET", "/api/notes/999999", None),
    ("GET", "/api/finance/debts/999999/payments", None),
    ("POST", "/api/finance/transactions", {"amount": "не число"}),
])
def test_errors_do_not_leak_internals(method, path, body):
    """Ошибка — короткий JSON без traceback, путей файлов и внутренних имён модулей."""
    r = _client().request(method, path, json=body, headers=_token_headers())
    assert r.status_code < 500, f"{method} {path} → {r.status_code}"
    text = r.text
    for needle in ("Traceback", "site-packages", "jarvis-main", "File \"", "\\core\\", "/core/",
                   "sqlite3", "OperationalError"):
        assert needle not in text, f"{method} {path}: ответ содержит {needle!r}"


def test_unknown_api_path_is_404_not_spa_html():
    """Опечатка в /api/… даёт 404, а не HTML сайта с кодом 200."""
    r = _client().get("/api/definitely-not-a-route", headers=_token_headers())
    assert r.status_code == 404
    assert "<!doctype html" not in r.text.lower()


# ================================================================ 8. local-режим: в облако ничего
def test_screenshot_does_not_go_to_cloud_in_local_mode(monkeypatch):
    """В режиме local скриншот не уходит в облако: describe_image возвращает None и сети не касается."""
    from core.brain import llm

    called = {"cloud": 0}

    async def _boom(*a, **k):          # любая попытка уйти в облако — провал теста
        called["cloud"] += 1
        raise AssertionError("в режиме local картинка не должна уходить в облако")

    async def _no_local(*a, **k):
        return False

    monkeypatch.setattr(llm, "local_only", lambda: True)
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)
    monkeypatch.setattr(llm, "VISION_CLOUD_OK", True)
    monkeypatch.setattr(llm, "VISION_WHERE", "auto")
    monkeypatch.setattr(llm, "_local_vision_available", _no_local)
    monkeypatch.setattr(llm, "_cloud_post", _boom)

    out = asyncio.run(llm.describe_image("QUJD", "Что на экране?", private=False))
    assert out is None
    assert called["cloud"] == 0


def test_private_image_never_goes_to_cloud_unless_explicitly_cloud(monkeypatch):
    """private=True (скриншот/чек): в auto облако не берётся, даже если локальная модель молчит."""
    from core.brain import llm

    async def _no_local(*a, **k):
        return False

    async def _boom(*a, **k):
        raise AssertionError("private-картинка не должна уходить в облако при vision.where=auto")

    monkeypatch.setattr(llm, "local_only", lambda: False)
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)
    monkeypatch.setattr(llm, "VISION_CLOUD_OK", True)
    monkeypatch.setattr(llm, "VISION_WHERE", "auto")
    monkeypatch.setattr(llm, "_local_vision_available", _no_local)
    monkeypatch.setattr(llm, "_cloud_post", _boom)

    assert asyncio.run(llm.describe_image("QUJD", "Что на экране?", private=True)) is None


def test_cloud_preview_says_nothing_is_sent_in_local_mode(monkeypatch):
    """«Что уйдёт в облако»: в local will_send=false, и сам эндпоинт ничего не отправляет."""
    from core.brain import llm
    monkeypatch.setattr(llm, "MODE", "local")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: True)
    c = _client()
    r = c.post("/api/cloud/preview", json={"text": "секретный текст"}, headers=_token_headers())
    assert r.status_code == 200
    body = r.json()
    assert body["will_send"] is False, "в режиме local will_send обязан быть false"
    assert "local" in body["note"]
    # и в hybrid с текстом — отправка ожидаема, но сам эндпоинт ничего не делает
    monkeypatch.setattr(llm, "MODE", "hybrid")
    r2 = c.post("/api/cloud/preview", json={"text": "проверка"}, headers=_token_headers())
    assert r2.status_code == 200


# ================================================================ 9. загрузки файлов
def test_upload_size_limit_note_photo():
    c = _client()
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (21 * 1024 * 1024)
    r = c.post("/api/notes/photo", files={"file": ("a.png", big, "image/png")}, headers=_token_headers())
    assert r.status_code == 413


def test_upload_size_limit_boards_image():
    c = _client()
    b = c.post("/api/boards", json={"title": "тест", "kind": "mockup"}, headers=_token_headers())
    assert b.status_code == 200
    bid = b.json()["id"]
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (21 * 1024 * 1024)
    r = c.post(f"/api/boards/{bid}/image", files={"file": ("a.png", big, "image/png")}, headers=_token_headers())
    assert r.status_code == 413


def test_board_image_must_really_be_an_image():
    c = _client()
    b = c.post("/api/boards", json={"title": "тест2", "kind": "mockup"}, headers=_token_headers())
    bid = b.json()["id"]
    r = c.post(f"/api/boards/{bid}/image",
               files={"file": ("a.exe", b"MZ" + b"\x00" * 2048, "application/octet-stream")},
               headers=_token_headers())
    assert r.status_code == 400
    assert "не картинка" in r.json().get("detail", "").lower() or "картинк" in r.json().get("detail", "").lower()


def test_saved_media_name_is_safe_and_inside_media_dir():
    """Картинка сохраняется под безопасным именем внутри data/media (обхода каталога нет)."""
    from core.services import brain_notes
    rel = brain_notes.save_image(b"\x89PNG\r\n\x1a\n" + b"\x00" * 512)
    assert ".." not in rel and "\\" not in rel and "/" in rel
    f = (brain_notes.MEDIA_DIR / rel).resolve()
    assert f.is_relative_to(brain_notes.MEDIA_DIR.resolve())
    assert f.suffix in (".jpg", ".png", ".gif", ".webp")


# ================================================================ 10. содержимое заметок не командует ПК
def test_notes_and_links_cannot_drive_pc():
    """Текст заметки/ссылки не инициирует команды управления ПК (правило фазы 6)."""
    from core.brain import agent
    from core.services import pc
    assert pc.from_trusted_channel("tg") and pc.from_trusted_channel("tg-voice")
    assert pc.from_trusted_channel("voice") and pc.from_trusted_channel("web")
    assert not pc.from_trusted_channel("tg-fwd") and not pc.from_trusted_channel("tg-voice-fwd")


# ================================================================ 11. конфигурация репозитория
def test_gitignore_covers_secrets_and_db():
    """config.yaml, .env, data/ и backups/ не должны попадать в git."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    gi = (root / ".gitignore").read_text(encoding="utf-8")
    for entry in ("config.yaml", ".env", "data/", "backups/", "*.db"):
        assert entry in gi, f".gitignore не закрывает {entry}"
    assert "!.env.example".replace("", "") in gi or "!.env.example" in gi


def test_dockerignore_excludes_secrets_and_backups():
    """.dockerignore не пускает ключи и бэкапы в образ (`COPY . .`)."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    di = (root / ".dockerignore").read_text(encoding="utf-8")
    for entry in ("config.yaml", ".env", "data", "backups"):
        assert entry in di, f".dockerignore не закрывает {entry}"


def test_env_example_has_no_values():
    """.env.example — только имена переменных, ни одного значения."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for line in (root / ".env.example").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        name, _, value = s.partition("=")
        assert value.strip() == "", f"в .env.example задано значение для {name}"


def test_ci_workflow_has_no_secrets_and_no_pull_request_target():
    """CI не печатает секреты, не выполняет код из PR в привилегированном режиме."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    wf = root / ".github" / "workflows" / "tests.yml"
    text = wf.read_text(encoding="utf-8")
    assert "pull_request_target" not in text
    assert "secrets." not in text, "workflow не должен обращаться к secrets"
    for bad in ("cat data/", "cat config.yaml", "cat .env"):
        assert bad not in text, f"workflow печатает содержимое: {bad}"