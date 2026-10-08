"""Ревью A «API и безопасность» — часть 2: коды ответов, идемпотентность, GET-мутации,
паритет декораторов после разбиения `core/api/app.py` → `core/api/routers/*`.

Фикстура `fresh_db` (tests/test_core) — всё на временной БД в tmp_path,
`data/jarvis.db` не открывается.

Тесты со `xfail` — это ПОДТВЕРЖДЁННЫЕ находки ревью: они падают на текущем коде
и перестанут падать после исправления (strict=False → xpass, когда починят).
"""
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402
from tests.test_core import fresh_db  # noqa: E401,F401  (autouse: временная БД)


def _client():
    from fastapi.testclient import TestClient
    from core.api.app import app
    return TestClient(app, client=("127.0.0.1", 5555), base_url="http://testserver")


# ============================ 1. 404 на несуществующий ресурс ============================
NOT_FOUND = [
    ("GET", "/api/orders/999", None),
    ("DELETE", "/api/orders/999", None),
    ("GET", "/api/boards/999", None),
    ("GET", "/api/boards/999/text", None),
    ("DELETE", "/api/boards/999", None),
    ("GET", "/api/boards/for-order/999", None),
    ("GET", "/api/people/999", None),
    ("PUT", "/api/people/999", {"name": "X"}),
    ("PUT", "/api/relations/999", {"status": "yes"}),
    ("GET", "/api/tasks/999", None),
    ("DELETE", "/api/tasks/999", None),
    ("GET", "/api/aims/999", None),
    ("PUT", "/api/aims/999", {"title": "Цель"}),
    ("POST", "/api/milestones/999/done", None),
    ("PUT", "/api/notes/999", {}),
    ("DELETE", "/api/notes/999", None),
    ("PUT", "/api/links/999", {}),
    ("DELETE", "/api/links/999", None),
    ("PUT", "/api/facts/999", {"text": "x"}),
    ("POST", "/api/facts/999/forget", None),
    ("DELETE", "/api/lessons/999", None),
    ("PUT", "/api/events/999", {"title": "встреча", "start": "2026-10-05T10:00:00"}),
    ("DELETE", "/api/events/999", None),
    ("POST", "/api/events/999/done", {"done": True}),
    ("DELETE", "/api/finance/transactions/999", None),
    ("DELETE", "/api/finance/categories/999", None),
    ("DELETE", "/api/finance/accounts/999", None),
    ("DELETE", "/api/finance/debts/999", None),
    ("DELETE", "/api/finance/recurring/999", None),
    ("DELETE", "/api/finance/goals/999", None),
]


@pytest.mark.parametrize("method,path,body", NOT_FOUND)
def test_missing_resource_404(method, path, body):
    r = _client().request(method, path, json=body)
    assert r.status_code == 404, f"{method} {path} -> {r.status_code} (ожидали 404)"


# P2 закрыт: несуществующая фин-сущность теперь 404 и на PUT — сервис кидает finance.FinanceNotFound
# (наследник HTTPException + FinanceError), а не FinanceError → 400 (core/services/finance.py).
@pytest.mark.parametrize("path,body", [
    ("/api/finance/transactions/999", {"amount": 10}),
    ("/api/finance/categories/999", {"name": "X"}),
    ("/api/finance/accounts/999", {"name": "X"}),
    ("/api/finance/debts/999", {"title": "X"}),
    ("/api/finance/recurring/999", {"title": "X"}),
])
def test_finance_put_missing_404(path, body):
    r = _client().put(path, json=body)
    assert r.status_code == 404, f"PUT {path} -> {r.status_code} (ожидали 404)"


# P2 закрыт: роут отдаёт 404 для несуществующего долга (core/api/routers/finance.py).
def test_debt_payments_missing_404():
    assert _client().get("/api/finance/debts/999/payments").status_code == 404


# ============================ 2. 422 на кривое тело ============================
BAD_BODIES = [
    ("POST", "/api/tasks", {}),                                   # нет обязательного title
    ("POST", "/api/tasks", {"title": 123}),                       # не тот тип
    ("POST", "/api/tasks", {"title": "x", "priority": 9}),        # вне диапазона
    ("POST", "/api/orders/clients", {"name": 123}),
    ("POST", "/api/chat", {}),                                    # нет text
    ("POST", "/api/notes", {"text": ""}),                         # пустая заметка
    ("POST", "/api/people", {"name": 123}),
    ("PUT", "/api/ui-prefs", {"prefs": "не-словарь"}),
    ("POST", "/api/finance/transactions", {"amount": "много"}),
    ("POST", "/api/boards", {"title": "x" * 500}),                # длиннее max_length
    ("POST", "/api/aims", {"title": "x"}),                        # короче min_length
]


@pytest.mark.parametrize("method,path,body", BAD_BODIES)
def test_bad_body_422(method, path, body):
    r = _client().request(method, path, json=body)
    assert r.status_code == 422, f"{method} {path} {body} -> {r.status_code} (ожидали 422)"


def test_malformed_json_422():
    r = _client().post("/api/tasks", content=b"{oops", headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_empty_name_is_400_by_contract():
    """POST /api/people с пустым именем — осознанный 400 с текстом, а не 422."""
    r = _client().post("/api/people", json={"name": "   "})
    assert r.status_code == 400


# P2 закрыт: SPA catch-all отдаёт 404 на неизвестный /api/* (core/api/app.py::spa).
def test_unknown_api_path_is_404_not_html():
    r = _client().get("/api/finances/summary")   # опечатка: такого роута нет
    assert r.status_code == 404, f"неизвестный /api/* путь -> {r.status_code}"
    assert "text/html" not in r.headers.get("content-type", "")


# ============================ 3. Идемпотентность платежей ============================
def _make_order(c, price=10000):
    r = c.post("/api/orders", json={"title": "Ролик для клиента", "price": price})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _payments(c, oid):
    return c.get(f"/api/orders/{oid}").json()["payments"]


def test_crm_payment_idempotent():
    """POST /api/crm/orders/{id}/payments: повтор с тем же idem_key не создаёт второй доход."""
    c = _client()
    oid = _make_order(c)
    p1 = c.post(f"/api/crm/orders/{oid}/payments", json={"amount": 5000, "idem_key": "rev-a-1"})
    p2 = c.post(f"/api/crm/orders/{oid}/payments", json={"amount": 5000, "idem_key": "rev-a-1"})
    assert p1.status_code == 200 and p2.status_code == 200, (p1.text, p2.text)
    assert len(_payments(c, oid)) == 1, "повтор с тем же idem_key создал дубль дохода"


# P1 закрыт: PaymentIn получил idem_key (core/api/schemas.py), роут пробрасывает его в
# orders.add_payment, сайт шлёт ключ из PaySheet (web/src/pages/Orders.jsx). Был xfail.
def test_api_payment_idempotent():
    c = _client()
    oid = _make_order(c)
    body = {"amount": 5000, "note": "аванс", "idem_key": "rev-a-2"}
    p1 = c.post(f"/api/orders/{oid}/payments", json=body)
    p2 = c.post(f"/api/orders/{oid}/payments", json=body)
    assert p1.status_code == 200 and p2.status_code == 200, (p1.text, p2.text)
    assert len(_payments(c, oid)) == 1, f"повтор создал дубль: {len(_payments(c, oid))} платежей"


# ============================ 4. GET не должен менять состояние ============================
@pytest.mark.xfail(reason="P2: GET /api/boards/for-order/{id}?create=true создаёт доску — GET с побочным "
                          "эффектом (кэш/прокси/предпросмотр ссылки могут создать мусорную доску)",
                   strict=False)
def test_get_board_for_order_does_not_create():
    from core.services import boards
    c = _client()
    oid = _make_order(c)
    before = len(c.get("/api/boards").json())
    c.get(f"/api/boards/for-order/{oid}", params={"create": "true"})
    assert len(c.get("/api/boards").json()) == before, "GET создал доску"


@pytest.mark.xfail(reason="P3: GET /api/orders/freelance пишет настройку (pulse.auto_enable_if_used) — "
                          "побочный эффект на чтении", strict=False)
def test_get_freelance_does_not_write_setting():
    from core.db import get_setting
    c = _client()
    _make_order(c)
    assert get_setting("freelance") is None
    assert c.get("/api/orders/freelance").status_code == 200
    assert get_setting("freelance") is None, "GET записал настройку в БД"


@pytest.mark.xfail(reason="P3: GET /api/diagnose пишет health.last_ok/at и порождает событие — "
                          "мутация состояния на GET", strict=False)
def test_get_diagnose_does_not_write(monkeypatch):
    from core.db import get_setting
    import core.services.health as health

    async def fake_diagnose():
        return {"ok": True, "items": [], "text": "ok", "at": "2026-10-01T00:00:00"}

    monkeypatch.setattr(health, "diagnose", fake_diagnose)
    assert _client().get("/api/diagnose").status_code == 200
    assert get_setting("health.last_ok") is None, "GET записал состояние в БД"


def test_get_reads_do_not_write():
    """Контроль: обычные GET-чтения не меняют данные."""
    from sqlmodel import select
    from core.db import session, Task, Event, Note
    c = _client()
    c.post("/api/tasks", json={"title": "Проверить ревью"})
    with session() as s:
        before = (len(s.exec(select(Task)).all()), len(s.exec(select(Event)).all()),
                  len(s.exec(select(Note)).all()))
    for path in ("/api/tasks", "/api/events", "/api/dashboard", "/api/orders", "/api/people",
                 "/api/finance/summary", "/api/state", "/api/missed", "/api/timeline"):
        assert c.get(path).status_code == 200, path
    with session() as s:
        after = (len(s.exec(select(Task)).all()), len(s.exec(select(Event)).all()),
                 len(s.exec(select(Note)).all()))
    assert after == before, f"GET изменили данные: {before} -> {after}"


# ============================ 5. Методы роутов после механического разбиения ============================
# Frozen-таблицы сняты с core/api/app.py ДО разбиения (commit 643132d, шаг 7.0):
# набор (метод, путь) для доменов, не покрытых tests/test_p7_routers_registration.py.
MIND_ROUTES = [
    ("GET", "/api/cards/{name}"),
    ("POST", "/api/chat"),
    ("POST", "/api/undo"),
    ("GET", "/api/chat/history"),
    ("GET", "/api/notes/{nid}/related"),
    ("GET", "/api/links/{lid}/related"),
    ("GET", "/api/graph"),
    ("GET", "/api/graph/backlinks/{kind}/{ref_id}"),
    ("GET", "/api/notes"),
    ("POST", "/api/notes"),
    ("POST", "/api/notes/photo"),
    ("POST", "/api/notes/{nid}/polish"),
    ("PUT", "/api/notes/{nid}"),
    ("DELETE", "/api/notes/{nid}"),
    ("GET", "/api/links"),
    ("POST", "/api/links"),
    ("PUT", "/api/links/{lid}"),
    ("DELETE", "/api/links/{lid}"),
    ("GET", "/api/facts"),
    ("POST", "/api/facts"),
    ("PUT", "/api/facts/{fid}"),
    ("POST", "/api/facts/{fid}/forget"),
    ("POST", "/api/facts/{fid}/restore"),
    ("POST", "/api/facts/portrait"),
    ("POST", "/api/facts/style"),
    ("PUT", "/api/facts/style"),
    ("GET", "/api/lessons"),
    ("DELETE", "/api/lessons/{lid}"),
    ("POST", "/api/facts/nightly"),
    ("GET", "/api/memory"),
    ("GET", "/api/search/semantic"),
    ("POST", "/api/search/reindex"),
]

PC_ROUTES = [
    ("POST", "/api/pc/ping"),
    ("GET", "/api/screen"),
    ("POST", "/api/pc/ack"),
    ("GET", "/api/pc/state"),
    ("POST", "/api/pc/launch"),
    ("GET", "/api/pc/organize/log"),
    ("GET", "/api/pc/organize/preview"),
    ("POST", "/api/pc/result"),
    ("POST", "/api/pc/clipboard"),
    ("POST", "/api/vision/ask"),
    ("POST", "/api/cloud/preview"),
    ("GET", "/api/voice/voices"),
    ("GET", "/api/voice/demo"),
    ("POST", "/api/voice/pick"),
]

SYSTEM_ROUTES = [
    ("GET", "/api/health"),
    ("GET", "/api/dashboard"),
    ("GET", "/api/state"),
    ("GET", "/api/presence/events"),
    ("GET", "/api/diagnose"),
    ("GET", "/api/ui-prefs"),
    ("PUT", "/api/ui-prefs"),
    ("GET", "/api/edition"),
    ("POST", "/api/edition"),
    ("GET", "/api/client/info"),
    ("GET", "/api/llm"),
    ("GET", "/api/settings"),
    ("PUT", "/api/settings"),
    ("GET", "/api/status"),
    ("GET", "/api/phone"),
    ("GET", "/api/runs"),
    ("GET", "/api/runs/report"),
    ("POST", "/api/phone/rotate"),
    ("POST", "/api/tg/login"),
    ("POST", "/api/tg/logout"),
    ("GET", "/api/tg/miniapp"),
    ("POST", "/api/game"),
    ("POST", "/api/status/small"),
    ("POST", "/api/status/lmstudio"),
    ("POST", "/api/status/gemini"),
    ("GET", "/api/google/status"),
    ("GET", "/api/google/connect"),
    ("GET", "/api/google/callback"),
    ("POST", "/api/google/sync"),
    ("POST", "/api/google/pull"),
    ("POST", "/api/google/disconnect"),
    ("POST", "/api/backup"),
    ("GET", "/api/backups"),
    ("POST", "/api/backups/restore"),
    ("GET", "/api/backups/{name:path}/download"),
]


def _router_routes(name):
    import importlib
    r = importlib.import_module(f"core.api.routers.{name}").router
    return sorted((x.path, tuple(sorted(x.methods))) for x in r.routes)


@pytest.mark.parametrize("name,want", [("mind", MIND_ROUTES), ("pc", PC_ROUTES), ("system", SYSTEM_ROUTES)])
def test_router_methods_match_pre_split(name, want):
    """Декораторы (метод+путь) совпадают с app.py до разбиения: копипаста @router.post вместо @router.get ловится."""
    got = set(_router_routes(name))
    expected = {(p, (m,)) for m, p in want}
    assert got == expected, ("расхождение с app.py до разбиения:\n"
                             f"  лишнее: {sorted(got - expected)}\n"
                             f"  потеряно: {sorted(expected - got)}")


def test_sse_stream_still_in_app_and_get():
    """/api/events/stream — GET и живёт в app.py (раньше /api/events/{event_id})."""
    import importlib
    app_mod = importlib.import_module("core.api.app")
    got = {(x.path, tuple(sorted(x.methods))) for x in app_mod.app.router.routes
           if getattr(x, "path", None) == "/api/events/stream"}
    assert ("/api/events/stream", ("GET",)) in got
    assert ("/api/events/stream", ("GET",)) not in set(_router_routes("tasks"))


def _flat_routes(routes, out=None):
    """Разворачиваем include_router (FastAPI 0.141 держит их как вложенные объекты)."""
    out = [] if out is None else out
    for r in routes:
        if type(r).__name__ == "_IncludedRouter":
            _flat_routes(r.original_router.routes, out)
            continue
        p = getattr(r, "path", None)
        if p is None:
            continue
        for m in (getattr(r, "methods", None) or []):
            out.append((m, p))
    return out


def test_no_duplicate_method_and_path():
    from core.api.app import app
    seen, dups = set(), []
    for key in _flat_routes(app.router.routes):
        if key in seen:
            dups.append(key)
        seen.add(key)
    assert not dups, f"дубли (метод, путь): {dups}"


# P1 закрыт: PUT /api/facts/style перенесён ВЫШЕ PUT /api/facts/{fid} в routers/mind.py
# (Starlette сверяет роуты по порядку регистрации). Был xfail.
def test_put_facts_style_not_shadowed():
    r = _client().put("/api/facts/style", json={"text": "Пишу коротко"})
    assert r.status_code == 200, f"PUT /api/facts/style -> {r.status_code}"
    from core.services import memory as mem
    from core.db import get_setting
    assert (get_setting(mem.STYLE_KEY) or "") == "Пишу коротко"


def test_put_facts_id_still_works():
    """Параллельный сценарий: PUT /api/facts/{fid} (числовой id) работает."""
    c = _client()
    fid = c.post("/api/facts", json={"text": "Вегетарианец"}).json()["id"]
    r = c.put(f"/api/facts/{fid}", json={"core": True})
    assert r.status_code == 200
