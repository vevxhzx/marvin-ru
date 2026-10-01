"""ФАЗА 7 — инварианты подключения роутов по доменам (шаг 7.1, `core/api/routers/finance.py`).

Логику роутов не проверяем — она покрыта обычными тестами. Здесь только СКЕЛЕТ:
перенесённый роутер подключён, все 42 пути/метода на месте, дублей нет и —
главное — подключение стоит ДО catch-all SPA, иначе `{path:path}` перехватит
все `/api/*` и сайт перестанет открываться (см. `reviews/P7_refactor.md` §4.2).

Тест дешёвый: БД не трогается, только объект `app`.
"""
import os

import pytest

os.environ["ASSISTANT_TEST"] = "1"

from core.api.app import app  # noqa: E402

# Полный список путей/методов finance.py (43 строки шага 7.0, `reviews/P7_refactor.md` §3).
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


@pytest.mark.parametrize("method,path", FINANCE_ROUTES)
def test_route_matches(method, path):
    """Путь+метод матчатся на уровне роутинга: ни 404 «роут не найден», ни 405."""
    from starlette.routing import Match

    concrete = (path.replace("{tx_id}", "1").replace("{cid}", "1").replace("{aid}", "1")
                .replace("{debt_id}", "1").replace("{rid}", "1").replace("{gid}", "1")
                .replace("{what}.{fmt}", "transactions.csv"))
    scope = {"type": "http", "method": method, "path": concrete, "root_path": "", "headers": []}
    matched = [p for r, (p, _m) in _flat(app.router.routes, []) if r.matches(scope)[0] is Match.FULL]
    # catch-all SPA `/{path:path}` тоже матчится на GET — важно, чтобы выигрывал
    # именно наш роут, т.е. он зарегистрирован раньше catch-all
    assert matched and matched[0] == path, f"{method} {concrete} матчится на {matched}, а не на {path}"


def test_finance_router_has_exactly_42_routes():
    from core.api.routers.finance import router

    got = sorted((r.path, tuple(sorted(r.methods))) for r in router.routes)
    want = sorted((p, (m,)) for m, p in FINANCE_ROUTES)
    assert len(got) == 42
    assert got == want


def test_finance_routes_registered_on_app():
    have = set(_all_routes())
    missing = [(m, p) for m, p in FINANCE_ROUTES if (p, (m,)) not in have]
    assert not missing, f"роуты finance потеряны при подключении: {missing}"


def test_no_duplicate_method_and_path():
    seen = [r for r in _all_routes()]
    assert len(seen) == len(set(seen)), "появились дубли (путь, метод)"


def test_registered_before_spa_catchall():
    """Инвариант §4.2: `_register_routers(app)` — ДО статики и catch-all `{path:path}`.

    Иначе SPA перехватит `/api/*` (он матчится первым) и сайт отдаст HTML вместо JSON.
    """
    routes = app.router.routes
    finance_idx = next(
        (i for i, r in enumerate(routes)
         if type(r).__name__ == "_IncludedRouter"
         and any(getattr(x, "path", "").startswith("/api/finance") for x in r.original_router.routes)),
        None,
    )
    assert finance_idx is not None, "core/api/routers/finance.py не подключён к app"
    after = [getattr(r, "path", "") for r in routes[finance_idx + 1:]]
    assert not [p for p in after if p.startswith("/api/")], (
        f"после finance зарегистрированы API-роуты {after} — порядок подключения нарушен")
    assert any(p in ("/{path:path}", "/") for p in after) or any(p == "/assets" for p in after), (
        "статика/catch-all должны регистрироваться после роутов по доменам")
