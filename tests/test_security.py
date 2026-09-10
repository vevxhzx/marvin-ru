"""Безопасность API и инструментов. Все проверки офлайн, с временной БД (fixture из test_core)."""
import asyncio
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402
from tests.test_core import fresh_db  # noqa: E402,F401  (autouse-фикстура)


def _client(remote: bool):
    """TestClient с адресом «удалённого» клиента: starlette подставляет host='testclient', а нам нужен не-loopback."""
    from fastapi.testclient import TestClient
    from core.api.app import app
    c = TestClient(app, client=("192.168.1.50", 5555) if remote else ("127.0.0.1", 5555))
    return c


def test_api_open_from_localhost():
    c = _client(remote=False)
    assert c.get("/api/health").status_code == 200
    assert c.get("/api/tasks").status_code == 200


def test_api_requires_token_from_lan():
    c = _client(remote=True)
    assert c.get("/api/health").status_code == 200          # публично: без данных
    r = c.get("/api/tasks")
    assert r.status_code == 401
    r = c.post("/api/chat", json={"text": "потратил 700 на такси", "channel": "web"})
    assert r.status_code == 401, "чужое устройство не должно исполнять команды"
    r = c.put("/api/settings", json={"changes": {"telegram.token": "1:x"}})
    assert r.status_code == 401
    # с токеном в заголовке — можно
    from core.api import auth
    assert c.get("/api/tasks", headers={"X-Auth-Token": auth.token()}).status_code == 200
    # неверный токен — нельзя
    assert c.get("/api/tasks", headers={"X-Auth-Token": "wrong"}).status_code == 401


def test_token_link_sets_cookie_and_strips_query():
    from core.api import auth
    c = _client(remote=True)
    r = c.get(f"/?t={auth.token()}", follow_redirects=False)
    assert r.status_code == 303 and auth.COOKIE in r.cookies
    assert "t=" not in r.headers["location"]
    # дальше — по cookie
    assert c.get("/api/tasks").status_code == 200


def test_setup_wizard_local_only():
    from core.api import auth
    c = _client(remote=True)
    assert c.get("/api/setup/state", headers={"X-Auth-Token": auth.token()}).status_code == 403
    assert c.get("/setup", headers={"X-Auth-Token": auth.token()}).status_code == 403
    assert _client(remote=False).get("/api/setup/state").status_code == 200


def test_phone_links_only_from_pc():
    from core.api import auth
    c = _client(remote=True)
    assert c.get("/api/phone", headers={"X-Auth-Token": auth.token()}).status_code == 403


def test_rotate_invalidates_old_token(tmp_path, monkeypatch):
    from core.api import auth
    monkeypatch.setattr(auth, "TOKEN_FILE", tmp_path / "tok")
    monkeypatch.setattr(auth, "_TOKEN", None)
    old = auth.token()
    c = _client(remote=True)
    assert c.get("/api/tasks", headers={"X-Auth-Token": old}).status_code == 200
    new = auth.rotate()
    assert new != old
    assert c.get("/api/tasks", headers={"X-Auth-Token": old}).status_code == 401
    assert c.get("/api/tasks", headers={"X-Auth-Token": new}).status_code == 200


def test_docker_mode_token_counts_as_local(monkeypatch):
    from core.api import auth
    monkeypatch.setattr(auth, "IN_DOCKER", True)
    c = _client(remote=True)
    assert c.get("/api/setup/state").status_code == 403
    assert c.get("/api/setup/state", headers={"X-Auth-Token": auth.token()}).status_code == 200


# ---------------- F2: аргументы инструментов от LLM ----------------
def test_tool_negative_amount_rejected_not_flipped():
    from core.tools.registry import run_tool
    from core.services import finance
    r = run_tool("add_expense", {"amount": -700})
    assert "не выполнен" in r and "больше нуля" in r
    assert finance.summary(1)["spent"] == 0, "раньше -700 молча превращалось в трату 700"


def test_tool_blank_title_rejected():
    from core.tools.registry import run_tool
    from core.services import tasks
    from core.db import session, Note
    from sqlmodel import select
    assert "не хватает" in run_tool("add_task", {"title": "   "})
    assert tasks.list_tasks() == []
    assert "не хватает" in run_tool("add_note", {"text": " \n "})
    with session() as s:
        assert s.exec(select(Note)).all() == []


def test_tool_days_range_and_missing_required():
    from core.tools.registry import run_tool
    assert "от 1 до" in run_tool("finance_summary", {"days": -5})
    assert "от 1 до" in run_tool("finance_summary", {"days": 99999999})
    r = run_tool("set_balance", {"account": "Т-Банк"})
    assert "не хватает обязательных полей: balance" in r and "Traceback" not in r and "positional" not in r


def test_tool_coercion_and_extra_fields():
    from core.tools.registry import run_tool, validate_args
    # строка с пробелами/запятой → число; лишние поля отбрасываются; title обрезается
    a = validate_args("add_expense", {"amount": "1 200,50", "note": "такси", "hallucinated": 1})
    assert a == {"amount": 1200.5, "note": "такси"}
    a = validate_args("add_event", {"title": "x" * 5000, "start": "2026-09-12T10:00"})
    assert len(a["title"]) == 300
    assert "нужно число" in run_tool("add_expense", {"amount": True})
    assert "нужно число" in run_tool("add_expense", {"amount": "много"})
    # баланс счёта может быть отрицательным, а нулевой платёж по долгу — допустим
    assert "Баланс" in run_tool("set_balance", {"account": "Т-Банк", "balance": -5000})
    assert "добавлен" in run_tool("add_debt", {"title": "Ипотека", "total": 100000, "payment": 0})


# ---------------- F4: open_app не подставляет имя в командную строку ----------------
def test_open_app_never_uses_shell(monkeypatch):
    from core.pc import actions
    calls = []
    monkeypatch.setattr(actions.subprocess, "Popen", lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(actions, "_start_menu_apps", lambda: {})
    monkeypatch.setattr(actions, "_APPS_CACHE", (0.0, {}))
    r = actions.open_app('calc" & shutdown /s /t 0 & "')
    assert "Не похоже на имя программы" in r
    assert calls == []
    r = actions.open_app("несуществующая_программа_xyz")
    assert "Не нашёл" in r
    assert all(not k.get("shell") for _, k in calls)


# ---------------- F5: бэкап включает картинки ----------------
def test_backup_copies_media(tmp_path, monkeypatch):
    from core.services import scheduler, brain_notes
    from core import config
    media = tmp_path / "media"; (media / "notes").mkdir(parents=True)
    (media / "notes" / "1.jpg").write_bytes(b"jpeg")
    monkeypatch.setattr(brain_notes, "MEDIA_DIR", media)
    monkeypatch.setattr(scheduler, "DB_PATH", tmp_path / "t.db")
    import sqlite3; sqlite3.connect(tmp_path / "t.db").close()
    monkeypatch.setattr(scheduler.cfg.backup, "dir", str(tmp_path / "backups"))
    monkeypatch.setattr(scheduler.cfg.backup, "enabled", True)
    monkeypatch.setattr(scheduler.cfg.backup, "extra_dir", "", raising=False)
    dst = scheduler.backup_db()
    assert dst and dst.exists()
    assert (tmp_path / "backups" / "media" / "notes" / "1.jpg").read_bytes() == b"jpeg"
    # повторный запуск ничего не копирует заново
    assert scheduler._sync_media(tmp_path / "backups" / "media") == 0


# ---------------- F6: превью ссылок не ходит во внутреннюю сеть ----------------
@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8765/api/settings", "http://localhost/", "http://[::1]/", "http://192.168.1.1/",
    "http://10.0.0.5/", "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd", "ftp://example.com/",
    "http://router.local/",
])
def test_preview_blocks_private_urls(url):
    from core.services import brain_notes
    assert brain_notes._is_public_http_url(url) is False
    meta = asyncio.run(brain_notes.fetch_preview(url))
    assert meta["title"] is None and meta.get("excerpt") in (None, "")


def test_preview_redirect_to_private_is_dropped(monkeypatch):
    """Публичный адрес, который редиректит на 127.0.0.1, не должен читаться."""
    import httpx
    from core.services import brain_notes
    monkeypatch.setattr(brain_notes, "_is_public_http_url",
                        lambda u: not any(x in u for x in ("127.0.0.1", "localhost")))

    def handler(request):
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:8765/api/settings"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text="<title>SECRET</title>")
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: real(*a, transport=transport, **{k2: v for k2, v in k.items() if k2 != "transport"}))
    meta = asyncio.run(brain_notes.fetch_preview("http://public.example/page"))
    assert meta["title"] is None


def test_preview_reads_html_via_manual_redirect(monkeypatch):
    import httpx
    from core.services import brain_notes
    monkeypatch.setattr(brain_notes, "_is_public_http_url", lambda u: True)

    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"},
                              text="<html><head><title>Привет мир</title></head><body><p>текст</p></body></html>")
    transport = httpx.MockTransport(handler)
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: real(*a, transport=transport, **k))
    meta = asyncio.run(brain_notes.fetch_preview("http://public.example/old"))
    assert meta["title"] == "Привет мир"


# ---------------- agent: инструмент отработал, модель упала → не терять результат (иначе дубли) ----------------
def test_via_ollama_keeps_actions_when_final_call_fails(monkeypatch):
    from core.brain import agent, llm
    from core.services import finance
    calls = {"n": 0}

    async def fake_chat(messages, tools=None, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"content": "", "tool_calls": [{"name": "add_expense", "arguments": {"amount": 700, "note": "такси"}}]}
        raise RuntimeError("Ollama: connection reset")

    async def _up():
        return True

    monkeypatch.setattr(llm, "ollama_chat", fake_chat)
    monkeypatch.setattr(llm, "ollama_available", _up)
    monkeypatch.setattr(llm, "MODE", "hybrid")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(agent, "_history", lambda *a, **k: [])
    r = asyncio.run(agent.via_ollama("потратил 700 на такси", "web"))
    assert r is not None and r.actions == ["add_expense"]
    assert "700" in r.text
    assert finance.summary(1)["spent"] == 700


# ---------------- CSRF и DNS-rebinding для loopback-клиентов ----------------
def test_csrf_multipart_from_foreign_origin_rejected():
    c = _client(remote=False)
    r = c.post("/api/notes/photo", files={"file": ("x.png", b"\x89PNG", "image/png")}, data={"text": "csrf"},
               headers={"origin": "https://evil.example", "host": "127.0.0.1:8765"})
    assert r.status_code == 403
    r = c.post("/api/chat", content='{"text":"задача: x","channel":"web"}'.encode(),
               headers={"content-type": "text/plain", "origin": "https://evil.example", "host": "127.0.0.1:8765"})
    assert r.status_code == 403
    r = c.post("/api/chat", json={"text": "что сегодня", "channel": "web"}, headers={"sec-fetch-site": "cross-site", "host": "127.0.0.1:8765"})
    assert r.status_code == 403


def test_same_origin_and_scriptless_requests_allowed():
    c = _client(remote=False)
    # свой сайт: Origin совпадает с Host
    r = c.get("/api/tasks", headers={"origin": "http://127.0.0.1:8765", "host": "127.0.0.1:8765"})
    assert r.status_code == 200
    r = c.post("/api/tasks", json={"title": "same-origin ok"}, headers={"origin": "http://127.0.0.1:8765", "host": "127.0.0.1:8765"})
    assert r.status_code == 200
    # dev-сервер Vite
    r = c.post("/api/tasks", json={"title": "vite ok"}, headers={"origin": "http://localhost:5173", "host": "localhost:8765"})
    assert r.status_code == 200
    # голосовой/ПК-клиент, curl: без Origin
    r = c.post("/api/tasks", json={"title": "script ok"}, headers={"host": "127.0.0.1:8765"})
    assert r.status_code == 200
    # Tailscale MagicDNS и имя ПК
    assert c.get("/api/tasks", headers={"host": "my-pc.tail1234.ts.net:8765"}).status_code == 200


def test_dns_rebinding_host_rejected():
    c = _client(remote=False)
    r = c.get("/api/tasks", headers={"host": "evil.example:8765"})
    assert r.status_code == 421
    assert c.get("/api/tasks", headers={"host": "192.168.1.20:8765"}).status_code == 200
    assert c.get("/api/tasks", headers={"host": "[::1]:8765"}).status_code == 200


# ---------------- надёжность: handle() не падает, повторные tool calls не дублируются ----------------
def test_handle_never_raises_on_bad_finance_input():
    from core.brain import agent, llm
    llm.MODE = "local"
    r = asyncio.run(agent.handle("потратил 0 на кофе", "web"))
    assert "Не записал" in r.text and r.actions == []
    r = asyncio.run(agent.handle("потратил 999999999999 на дом", "web"))
    assert "Не записал" in r.text and r.actions == []


def test_handle_survives_internal_exception(monkeypatch):
    from core.brain import agent
    def boom(*a, **k):
        raise RuntimeError("db is on fire")
    monkeypatch.setattr(agent, "rules", boom)
    r = asyncio.run(agent.handle("какая-то фраза без правил", "web"))
    assert "пошло не так" in r.text and r.via == "none"


def test_duplicate_tool_call_in_one_turn_runs_once(monkeypatch):
    from core.brain import agent, llm
    from core.services import finance
    calls = {"n": 0}

    async def fake_chat(messages, tools=None, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            tc = {"name": "add_expense", "arguments": {"amount": 300, "note": "кофе"}}
            return {"content": "", "tool_calls": [tc, dict(tc)]}   # модель прислала один и тот же вызов дважды
        return {"content": "Записал кофе 300.", "tool_calls": []}

    async def _up():
        return True
    monkeypatch.setattr(llm, "ollama_chat", fake_chat)
    monkeypatch.setattr(llm, "ollama_available", _up)
    monkeypatch.setattr(llm, "MODE", "hybrid")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(agent, "_history", lambda *a, **k: [])
    r = asyncio.run(agent.via_ollama("кофе 300 и ещё раз кофе 300", "web"))
    assert r.actions == ["add_expense"]
    assert finance.summary(1)["spent"] == 300


# ---------------- крупные суммы от LLM — только после «да» ----------------
def test_big_amount_from_llm_requires_confirmation(monkeypatch):
    from core.brain import agent, llm
    from core.services import finance

    async def fake_chat(messages, tools=None, **kw):
        return {"content": "", "tool_calls": [{"name": "add_expense", "arguments": {"amount": 150000, "note": "ноутбук"}}]}

    async def _up():
        return True
    monkeypatch.setattr(llm, "ollama_chat", fake_chat)
    monkeypatch.setattr(llm, "ollama_available", _up)
    monkeypatch.setattr(llm, "MODE", "hybrid")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(agent, "_history", lambda *a, **k: [])
    r = asyncio.run(agent.via_ollama("купил ноутбук за сто пятьдесят тысяч", "web"))
    assert "подтвердите" in r.text and finance.summary(1)["spent"] == 0
    # «нет» — ничего не записано
    r = asyncio.run(agent.handle("нет", "web"))
    assert finance.summary(1)["spent"] == 0 and "Отбой" in r.text
    # снова спросили → «да» — записано ровно один раз
    asyncio.run(agent.via_ollama("купил ноутбук за сто пятьдесят тысяч", "web"))
    r = asyncio.run(agent.handle("да", "web"))
    assert r.actions == ["add_expense"] and finance.summary(1)["spent"] == 150000
    # повторное «да» ничего не дублирует
    asyncio.run(agent.handle("да", "web"))
    assert finance.summary(1)["spent"] == 150000


def test_small_amount_from_llm_not_blocked(monkeypatch):
    from core.brain import agent, llm
    from core.services import finance
    calls = {"n": 0}

    async def fake_chat(messages, tools=None, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"content": "", "tool_calls": [{"name": "add_expense", "arguments": {"amount": 700, "note": "такси"}}]}
        return {"content": "Готово.", "tool_calls": []}

    async def _up():
        return True
    monkeypatch.setattr(llm, "ollama_chat", fake_chat)
    monkeypatch.setattr(llm, "ollama_available", _up)
    monkeypatch.setattr(llm, "MODE", "hybrid")
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(agent, "_history", lambda *a, **k: [])
    r = asyncio.run(agent.via_ollama("такси семьсот", "web"))
    assert r.actions == ["add_expense"] and finance.summary(1)["spent"] == 700


# ---------------- проактивность: вечерний обзор и тихие часы ----------------
def test_evening_review_lists_only_due_open_tasks():
    from datetime import datetime, timedelta
    from core.services import tasks
    tasks.add_task("Сдать отчёт", datetime.now().replace(hour=18, minute=0), source="test")
    tasks.add_task("Просрочено", datetime.now() - timedelta(days=2), source="test")
    tasks.add_task("Завтра", datetime.now() + timedelta(days=1), source="test")
    tasks.add_task("Без срока", None, source="test")
    done = tasks.add_task("Сделано", datetime.now(), source="test"); tasks.complete_task(done.id)
    titles = [t.title for t in tasks.evening_review()]
    assert set(titles) == {"Сдать отчёт", "Просрочено"}
    t = tasks.postpone_to_tomorrow(tasks.evening_review()[0].id)
    assert t.due.date() == (datetime.now() + timedelta(days=1)).date() and t.remind_stage == 0


def test_evening_review_sent_once_per_day_and_respects_quiet_hours(monkeypatch):
    from datetime import datetime
    from core.services import scheduler, tasks
    sent = []

    async def notify(text, buttons=None):
        sent.append(text)
    tasks.add_task("Сдать отчёт", datetime.now().replace(hour=8, minute=0), source="test")
    monkeypatch.setattr(scheduler, "_quiet_now", lambda: False)
    sch = scheduler.build(notify)
    job = sch.get_job("evening_review")
    asyncio.run(job.func())
    assert any("Сдать отчёт" in t for t in sent)
    n = len(sent)
    asyncio.run(job.func())
    assert len(sent) == n, "второй раз за день не шлём"
    # тихие часы: инициативное сообщение не уходит, напоминание о событии — уходит
    monkeypatch.setattr(scheduler, "_quiet_now", lambda: True)
    from core.db import set_setting
    set_setting(f"evening_review:{datetime.now():%Y-%m-%d}", None)
    asyncio.run(job.func())
    assert len(sent) == n


def test_quiet_hours_window(monkeypatch):
    from core.services import scheduler
    class N: quiet_from = 23; quiet_to = 8
    monkeypatch.setattr(scheduler.cfg, "notifications", N(), raising=False)
    import core.services.scheduler as m
    from datetime import datetime as real_dt
    class FakeDT(real_dt):
        h = 2
        @classmethod
        def now(cls, tz=None):
            return real_dt(2026, 9, 10, cls.h, 0)
    monkeypatch.setattr(m, "datetime", FakeDT)
    FakeDT.h = 2; assert m._quiet_now() is True
    FakeDT.h = 23; assert m._quiet_now() is True
    FakeDT.h = 12; assert m._quiet_now() is False
    FakeDT.h = 8; assert m._quiet_now() is False


def test_history_skips_stale_and_error_messages():
    from datetime import datetime, timedelta
    from core.brain import agent
    from core.db import ChatMessage, session
    with session() as s:
        s.add(ChatMessage(role="user", text="старое про отпуск", channel="web", created_at=datetime.now() - timedelta(days=2)))
        s.add(ChatMessage(role="user", text="свежее про ноутбук", channel="tg"))
        s.add(ChatMessage(role="assistant", text="Что-то пошло не так, сэр.", channel="tg"))
        s.commit()
    h = agent._history("web")
    texts = [x["text"] for x in h]
    assert "свежее про ноутбук" in texts and "старое про отпуск" not in texts
    assert not any(t.startswith("Что-то пошло не так") for t in texts)
