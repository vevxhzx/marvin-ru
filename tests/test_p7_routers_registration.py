"""ФАЗА 7 — инварианты подключения роутов по доменам (шаги 7.1–7.4).

Логику роутов не проверяем — она покрыта обычными тестами. Здесь только СКЕЛЕТ:
перенесённые роутеры подключены, все пути/методы на месте, дублей нет и —
главное — подключение стоит ДО catch-all SPA, иначе `{path:path}` перехватит
все `/api/*` и сайт перестанет открываться (см. `reviews/P7_refactor.md` §4.2).

Состояние на шаг 7.4: `finance` (42 роута), `orders` (22), `boards` (17),
`people` (15), `tasks` (15). `/api/events/stream` (SSE) пока в `app.py` — см.
`test_events_stream_still_in_app`.

Тест дешёвый: БД не трогается, только объект `app`.
"""
import os

import pytest

os.environ["ASSISTANT_TEST"] = "1"

from core.api.app import app  # noqa: E402

# Полный список путей/методов finance.py (42 строки шага 7.0, `reviews/P7_refactor.md` §3).
FINANCE_ROUTES = [
    ("POST", "/api/finance/import"),
    ("GET", "/api/insights/forecast"),
    ("GET", "/api/insights/subscriptions"),
    ("GET", "/api/insights/streak"),
    ("GET", "/api/insights/birthdays"),
    ("GET", "/api/insights/weekly"),
    ("GET", "/api/missed"),
    ("GET", "/api/snapshot/month.png"),
    ("GET", "/api/finance/summary"),
    ("GET", "/api/finance/daily"),
    ("GET", "/api/finance/forecast"),
    ("GET", "/api/finance/transactions"),
    ("POST", "/api/finance/transactions"),
    ("PUT", "/api/finance/transactions/{tx_id}"),
    ("DELETE", "/api/finance/transactions/{tx_id}"),
    ("POST", "/api/finance/categories"),
    ("PUT", "/api/finance/categories/{cid}"),
    ("DELETE", "/api/finance/categories/{cid}"),
    ("GET", "/api/finance/budgets"),
    ("GET", "/api/finance/categories"),
    ("GET", "/api/finance/accounts"),
    ("POST", "/api/finance/accounts/balance"),
    ("POST", "/api/finance/accounts"),
    ("PUT", "/api/finance/accounts/{aid}"),
    ("DELETE", "/api/finance/accounts/{aid}"),
    ("GET", "/api/finance/debts"),
    ("POST", "/api/finance/debts"),
    ("POST", "/api/finance/debts/{debt_id}/pay"),
    ("GET", "/api/finance/debts/{debt_id}/payments"),
    ("PUT", "/api/finance/debts/{debt_id}"),
    ("DELETE", "/api/finance/debts/{debt_id}"),
    ("GET", "/api/finance/recurring"),
    ("POST", "/api/finance/recurring"),
    ("PUT", "/api/finance/recurring/{rid}"),
    ("DELETE", "/api/finance/recurring/{rid}"),
    ("GET", "/api/finance/goals"),
    ("POST", "/api/finance/goals"),
    ("PUT", "/api/finance/goals/{gid}"),
    ("DELETE", "/api/finance/goals/{gid}"),
    ("POST", "/api/finance/goals/{gid}/put"),
    ("GET", "/api/finance/techniques"),
    ("GET", "/api/export/{what}.{fmt}"),
]

# Полный список путей/методов orders.py (22 роута шага 7.2 — `core/api/app.py` до переноса).
# `/api/crm/orders/*` из `core/crm/router.py` — отдельный роутер, он тут не участвует.
ORDERS_ROUTES = [
    ("GET", "/api/orders/suggest"),
    ("GET", "/api/orders/clients"),
    ("POST", "/api/orders/clients"),
    ("PUT", "/api/orders/clients/{cid}"),
    ("DELETE", "/api/orders/clients/{cid}"),
    ("GET", "/api/orders"),
    ("GET", "/api/orders/stats"),
    ("GET", "/api/orders/timer"),
    ("GET", "/api/orders/pomodoro"),
    ("GET", "/api/orders/freelance"),
    ("PUT", "/api/orders/freelance"),
    ("GET", "/api/orders/pulse"),
    ("PUT", "/api/orders/pomodoro"),
    ("POST", "/api/orders/timer"),
    ("DELETE", "/api/orders/timer"),
    ("POST", "/api/orders"),
    ("GET", "/api/orders/{oid}"),
    ("POST", "/api/orders/{oid}/time"),
    ("POST", "/api/orders/{oid}/time/from-screen"),
    ("PUT", "/api/orders/{oid}"),
    ("DELETE", "/api/orders/{oid}"),
    ("POST", "/api/orders/{oid}/payments"),
]

# Полный список путей/методов boards.py (17 роутов шага 7.2 — `core/api/app.py` до переноса).
BOARDS_ROUTES = [
    ("GET", "/api/boards"),
    ("POST", "/api/boards"),
    ("GET", "/api/boards/search"),
    ("GET", "/api/boards/for-order/{oid}"),
    ("GET", "/api/boards/{bid}"),
    ("GET", "/api/boards/{bid}/text"),
    ("PUT", "/api/boards/{bid}"),
    ("DELETE", "/api/boards/{bid}"),
    ("POST", "/api/boards/{bid}/items"),
    ("POST", "/api/boards/{bid}/frame"),
    ("POST", "/api/boards/{bid}/renumber"),
    ("PUT", "/api/boards/{bid}/items"),
    ("PUT", "/api/boards/{bid}/items/{iid}"),
    ("POST", "/api/boards/{bid}/items/delete"),
    ("PUT", "/api/boards/{bid}/sync"),
    ("POST", "/api/boards/{bid}/asset"),
    ("POST", "/api/boards/{bid}/image"),
]

# Полный список путей/методов people.py (15 роутов шага 7.3 — `core/api/app.py` до переноса):
# `/api/relations/{rid}` PUT, `/api/aims*`, `/api/milestones/*`, `/api/people*`.
# `/api/crm/clients/*` из `core/crm/router.py` — отдельный роутер, тут не участвует.
PEOPLE_ROUTES = [
    ("PUT", "/api/relations/{rid}"),
    ("GET", "/api/aims"),
    ("GET", "/api/aims/{aim_id}"),
    ("POST", "/api/aims"),
    ("PUT", "/api/aims/{aim_id}"),
    ("POST", "/api/aims/{aim_id}/milestones"),
    ("POST", "/api/milestones/{mid}/{status}"),
    ("GET", "/api/people/batch-hints"),
    ("GET", "/api/people/kinds"),
    ("DELETE", "/api/people/kinds/{kind}"),
    ("GET", "/api/people"),
    ("POST", "/api/people"),
    ("GET", "/api/people/today"),
    ("GET", "/api/people/{cid}"),
    ("PUT", "/api/people/{cid}"),
]

# Полный список путей/методов tasks.py (15 роутов шага 7.4 — `core/api/app.py` до переноса):
# `/api/events*` (6, БЕЗ SSE), `/api/tasks*` (7), `/api/focus`, `/api/timeline`.
# `GET /api/events/stream` (SSE) здесь НЕТ: он остаётся в `core/api/app.py` до шага 7.6
# (`reviews/P7_refactor.md` §3) — проверяется отдельно в `test_events_stream_still_in_app`.
TASKS_ROUTES = [
    ("GET", "/api/events"),
    ("POST", "/api/events"),
    ("PUT", "/api/events/{event_id}"),
    ("POST", "/api/events/{event_id}/done"),
    ("POST", "/api/events/{event_id}/skip"),
    ("DELETE", "/api/events/{event_id}"),
    ("GET", "/api/tasks"),
    ("GET", "/api/tasks/{task_id}"),
    ("POST", "/api/tasks"),
    ("PUT", "/api/tasks/{task_id}"),
    ("POST", "/api/tasks/{task_id}/undone"),
    ("POST", "/api/tasks/{task_id}/done"),
    ("DELETE", "/api/tasks/{task_id}"),
    ("GET", "/api/focus"),
    ("GET", "/api/timeline"),
]

DOMAIN_ROUTES = FINANCE_ROUTES + ORDERS_ROUTES + BOARDS_ROUTES + PEOPLE_ROUTES + TASKS_ROUTES

# Домены и их префиксы — по ним находим подключённые `_IncludedRouter` (инвариант §4.2 п. 1).
# ⚠️ Префикс домена `tasks` — `/api/events`, а НЕ `/api/tasks`: `/api/events/stream` (SSE)
# на шаге 7.4 ещё лежит в `core/api/app.py` и уедет в `system.py` только на 7.6, а префикс
# в `DOMAINS` должен быть УНИКАЛЬНЫМ и указывать именно на роутер домена.
DOMAINS = (("finance", "/api/finance"), ("orders", "/api/orders"), ("boards", "/api/boards"),
           ("people", "/api/people"), ("tasks", "/api/events"))


def _flat(routes, out):
    """Развернуть дерево роутов: FastAPI 0.141 держит include_router как вложенный объект."""
    for r in routes:
        if type(r).__name__ == "_IncludedRouter":
            _flat(r.original_router.routes, out)
            continue
        p = getattr(r, "path", None)
        if p is None:
            continue
        out.append((r, (p, tuple(sorted(getattr(r, "methods", []) or [])))))
    return out


def _all_routes():
    return [info for _, info in _flat(app.router.routes, [])]


@pytest.mark.parametrize("method,path", DOMAIN_ROUTES)
def test_route_matches(method, path):
    """Путь+метод матчатся на уровне роутинга: ни 404 «роут не найден», ни 405."""
    from starlette.routing import Match

    concrete = (path.replace("{tx_id}", "1").replace("{cid}", "1").replace("{aid}", "1")
                .replace("{debt_id}", "1").replace("{rid}", "1").replace("{gid}", "1")
                .replace("{oid}", "1").replace("{bid}", "1").replace("{iid}", "1")
                .replace("{aim_id}", "1").replace("{mid}", "1").replace("{status}", "done")
                .replace("{kind}", "client").replace("{event_id}", "1").replace("{task_id}", "1")
                .replace("{what}.{fmt}", "transactions.csv"))
    scope = {"type": "http", "method": method, "path": concrete, "root_path": "", "headers": []}
    matched = [p for r, (p, _m) in _flat(app.router.routes, []) if r.matches(scope)[0] is Match.FULL]
    # catch-all SPA `/{path:path}` тоже матчится на GET — важно, чтобы выигрывал
    # именно наш роут, т.е. он зарегистрирован раньше catch-all
    assert matched and matched[0] == path, f"{method} {concrete} матчится на {matched}, а не на {path}"


def _router_routes(name):
    """Плоский список (path, методы) роутера домена — проверяем, что перенесено ровно нужное."""
    import importlib

    r = importlib.import_module(f"core.api.routers.{name}").router
    return sorted((x.path, tuple(sorted(x.methods))) for x in r.routes)


def test_finance_router_has_exactly_42_routes():
    got = _router_routes("finance")
    want = sorted((p, (m,)) for m, p in FINANCE_ROUTES)
    assert len(got) == 42
    assert got == want


def test_orders_router_has_exactly_22_routes():
    got = _router_routes("orders")
    want = sorted((p, (m,)) for m, p in ORDERS_ROUTES)
    assert len(got) == 22
    assert got == want


def test_boards_router_has_exactly_17_routes():
    got = _router_routes("boards")
    want = sorted((p, (m,)) for m, p in BOARDS_ROUTES)
    assert len(got) == 17
    assert got == want


def test_people_router_has_exactly_15_routes():
    got = _router_routes("people")
    want = sorted((p, (m,)) for m, p in PEOPLE_ROUTES)
    assert len(got) == 15
    assert got == want


def test_tasks_router_has_exactly_15_routes():
    got = _router_routes("tasks")
    want = sorted((p, (m,)) for m, p in TASKS_ROUTES)
    assert len(got) == 15
    assert got == want


def test_finance_routes_registered_on_app():
    have = set(_all_routes())
    missing = [(m, p) for m, p in FINANCE_ROUTES if (p, (m,)) not in have]
    assert not missing, f"роуты finance потеряны при подключении: {missing}"


def test_orders_routes_registered_on_app():
    have = set(_all_routes())
    missing = [(m, p) for m, p in ORDERS_ROUTES if (p, (m,)) not in have]
    assert not missing, f"роуты orders потеряны при подключении: {missing}"


def test_boards_routes_registered_on_app():
    have = set(_all_routes())
    missing = [(m, p) for m, p in BOARDS_ROUTES if (p, (m,)) not in have]
    assert not missing, f"роуты boards потеряны при подключении: {missing}"


def test_people_routes_registered_on_app():
    have = set(_all_routes())
    missing = [(m, p) for m, p in PEOPLE_ROUTES if (p, (m,)) not in have]
    assert not missing, f"роуты people потеряны при подключении: {missing}"


def test_tasks_routes_registered_on_app():
    have = set(_all_routes())
    missing = [(m, p) for m, p in TASKS_ROUTES if (p, (m,)) not in have]
    assert not missing, f"роуты tasks потеряны при подключении: {missing}"


def test_events_stream_still_in_app():
    """SSE `/api/events/stream` на шаге 7.4 остаётся в `core/api/app.py` (§3 отчёта 7.0).

    Проверяем: (а) он вообще зарегистрирован и (б) он НЕ попал в `routers/tasks.py` —
    иначе шаг 7.6 (`system.py`) его потеряет. Уберётся на 7.6.
    """
    have = set(_all_routes())
    assert ("/api/events/stream", ("GET",)) in have, "SSE /api/events/stream куда-то потерялся"
    assert ("/api/events/stream", ("GET",)) not in set(_router_routes("tasks")), \
        "SSE /api/events/stream не должен быть в tasks.py — он уезжает в system.py на 7.6"


def test_events_stream_registered_before_event_id_and_catchall():
    """Инвариант §4.2 п. 2 + §6.1: SSE — литерал, `/api/events/{event_id}` — параметрический.

    Пока SSE лежит в `app.py` первым, конфликта нет. Этот тест — «забор» на 7.6:
    когда `/api/events/stream` переедет в `system.py` (регистрируемого ПОСЛЕ
    `tasks`), литерал начнёт конфликтовать с `/api/events/{event_id}`, и тест
    покажет это раньше, чем сломается живое обновление сайта.
    """
    from starlette.routing import Match

    flat = [info for _, info in _flat(app.router.routes, [])]

    def idx(path, method):
        hits = [i for i, (p, m) in enumerate(flat) if p == path and method in m]
        assert hits, f"{method} {path} не зарегистрирован"
        return hits[0]

    sse = idx("/api/events/stream", "GET")
    ev = idx("/api/events/{event_id}", "PUT")
    spa = idx("/{path:path}", "GET")
    assert sse < ev, f"SSE (idx {sse}) зарегистрирован позже /api/events/{{event_id}} (idx {ev})"
    assert sse < spa, f"SSE (idx {sse}) зарегистрирован позже catch-all (idx {spa})"
    # и фактический матч: GET /api/events/stream должен выигрывать у catch-all SPA
    scope = {"type": "http", "method": "GET", "path": "/api/events/stream", "root_path": "", "headers": []}
    matched = [p for r, (p, _m) in _flat(app.router.routes, []) if r.matches(scope)[0] is Match.FULL]
    assert matched[0] == "/api/events/stream", f"SSE перебит: {matched}"


def test_no_duplicate_method_and_path():
    seen = [r for r in _all_routes()]
    assert len(seen) == len(set(seen)), "появились дубли (путь, метод)"


def test_registered_before_spa_catchall():
    """Инвариант §4.2: `_register_routers(app)` — ДО статики и catch-all `{path:path}`.

    Иначе SPA перехватит `/api/*` (он матчится первым) и сайт отдаст HTML вместо JSON.

    Проверяется НЕ «последний роутер = finance», а «после ПОСЛЕДНЕГО подключённого
    роутера доменов нет ни одного `/api/*`-роута»: на шаге 7.4 последним идёт
    `tasks`, и список доменов будет расти до шага 7.6.
    """
    routes = app.router.routes
    idx = {}
    for name, prefix in DOMAINS:
        idx[name] = next(
            (i for i, r in enumerate(routes)
             if type(r).__name__ == "_IncludedRouter"
             and any(getattr(x, "path", "").startswith(prefix) for x in r.original_router.routes)),
            None,
        )
        assert idx[name] is not None, f"core/api/routers/{name}.py не подключён к app"
    # последний подключённый роутер доменов — ориентир, после него API-роутов быть не должно
    last = max(idx.values())
    after = [getattr(r, "path", "") for r in routes[last + 1:]]
    assert not [p for p in after if p.startswith("/api/")], (
        f"после роутеров доменов ({idx}) зарегистрированы API-роуты {after} — порядок подключения нарушен")
    assert any(p in ("/{path:path}", "/") for p in after) or any(p == "/assets" for p in after), (
        "статика/catch-all должны регистрироваться после роутов по доменам")
