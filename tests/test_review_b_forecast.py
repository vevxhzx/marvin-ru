# -*- coding: utf-8 -*-
"""Ревью B «Деньги», часть 2 — ряд «касса» (график) и прогноз.

Проверяемые инварианты:
* точка «сегодня» ряда == ``finance.total_balance()`` (то, что показывают карточки);
* даты ряда идут подряд, без дублей и «сегодня» ровно в одном месте;
* перевод между своими счетами и «чисто долговые» счета не двигают ряд;
* удаление операции пересчитывает ряд (вчерашний день становится плоским);
* будущая часть ``/api/finance/forecast`` совпадает с ``insights.cash_forecast``;
* один источник «сегодня» и незакороченный учёт регулярных платежей.

Всё на временной БД (tmp_path): db.engine подменяется до init_db(), data/jarvis.db
не открывается. Роут ``fin_forecast`` вызывается напрямую (без HTTP-сервера).
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta

import pytest

os.environ.setdefault("ASSISTANT_TEST", "1")

from core import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlalchemy import event
    from sqlmodel import create_engine
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


M = "Наличные"          # счёт из init_db, для переводов


def _fin():
    from core.services import finance
    return finance


def _ins():
    from core.services import insights
    return insights


def _main() -> str:
    return _fin().main_account_name()


def _ago(days: int, hour: int = 12) -> datetime:
    return datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0) - timedelta(days=days)


def _route(days: int = 30) -> dict:
    """GET /api/finance/forecast — тело роута без HTTP."""
    from core.api.routers.finance import fin_forecast
    return fin_forecast(days)


def _past(p: dict) -> list[dict]:
    return [x for x in p["points"] if x["kind"] == "past"]


def _route_future(p: dict) -> list[dict]:
    return [x for x in p["points"] if x["kind"] == "future"]


# ------------------------------------------------------------------ ряд cash_series (эталон)
def _today():
    """Сегодня в часовом поясе владельца — так же, как считает сам продукт."""
    from core.services import insights as _ins
    return _ins.now_tz().date()


def test_cash_series_today_point_is_total_balance():
    f = _fin()
    f.set_balance(_main(), 10_000)
    f.add_transaction(500, "expense", "Еда", "обед", _main(), date=_ago(1))
    s = _ins().cash_series(30)
    past = _past(s)
    assert past[-1]["date"] == s["today"] == _today().isoformat()
    assert past[-1]["balance"] == round(f.total_balance()) == 9_500


def test_cash_series_dates_are_consecutive_and_unique():
    _fin().set_balance(_main(), 10_000)
    s = _ins().cash_series(30)
    dates = [p["date"] for p in _past(s)]
    assert len(dates) == len(set(dates)), "дубли дат в ряду"
    d0 = date.fromisoformat(dates[0])
    for i, ds in enumerate(dates):
        assert date.fromisoformat(ds) == d0 + timedelta(days=i), "дыра или сдвиг в датах"
    assert dates[-1] == s["today"] == _today().isoformat()
    # будущее начинается со следующего дня, без пропуска и без повтора «сегодня»
    fut = [x for x in s["points"] if x["kind"] == "future"]
    assert date.fromisoformat(fut[0]["date"]) == _today() + timedelta(days=1)


def test_cash_series_ignores_transfers_and_debt_only_accounts():
    f = _fin()
    f.set_balance(_main(), 10_000)
    f.set_balance(M, 5_000)
    f.add_account("Ипотека", kind="debt_only", balance=100_000)
    f.add_transaction(1_000, "transfer", None, None, _main(), M, date=_ago(1))
    f.add_transaction(30_000, "expense", "ЖКХ", "проценты", "Ипотека", date=_ago(2))
    s = _ins().cash_series(30)
    assert f.total_balance() == pytest.approx(15_000)      # долговой счёт снаружи
    assert all(p["balance"] == 15_000 for p in _past(s)), "перевод/долговой счёт сдвинули ряд"
    assert all(p["delta"] == 0 for p in _past(s))


def test_cash_series_recomputes_after_delete():
    f = _fin()
    f.set_balance(_main(), 10_000)
    t = f.add_transaction(500, "expense", "Еда", "обед", _main(), date=_ago(1))
    s1 = _ins().cash_series(30)
    assert _past(s1)[-1]["balance"] == 9_500
    f.delete_transaction(t.id)
    s2 = _ins().cash_series(30)
    assert _past(s2)[-1]["balance"] == 10_000
    # вчерашний день стал плоским: удалили единственную операцию окна
    y = (_today() - timedelta(days=1)).isoformat()
    y_pt = next(p for p in _past(s2) if p["date"] == y)
    assert y_pt["delta"] == 0


# ------------------------------------------------------------------ роут /api/finance/forecast
def test_route_future_points_match_insights_forecast():
    f = _fin()
    f.set_balance(_main(), 10_000)
    r = _route(30)
    fc = _ins().cash_forecast(30)
    assert r["balance"] == round(f.total_balance())
    got = [(p["date"], p["balance"]) for p in _route_future(r)]
    want = [(p["date"], p["balance"]) for p in fc["points"][1:]]
    assert got == want


# Был xfail(P1): роут шёл старой зеркальной схемой (for i in range(hist,-1,-1)) — исправлено в
# core/api/routers/finance.py::fin_forecast (порядок обхода как в insights.cash_series).
def test_route_today_point_equals_total_balance():
    f = _fin()
    f.set_balance(_main(), 10_000)
    f.add_transaction(500, "expense", "Еда", "обед", _main(), date=_ago(2))
    r = _route(30)
    assert r["balance"] == 9_500                       # поле balance — правильное
    today_pt = _past(r)[-1]
    assert today_pt["date"] == _today().isoformat()
    # а точка «сегодня» врёт на те же 500 ₽ (завышает баланс)
    assert today_pt["balance"] == round(f.total_balance()) == 9_500


# Был xfail(P1): роут считал перевод тратой — теперь дельта берётся из insights._tx_balance_delta.
def test_route_today_point_ignores_own_transfer():
    f = _fin()
    f.set_balance(_main(), 10_000)
    f.set_balance(M, 5_000)
    f.add_transaction(1_000, "transfer", None, None, _main(), M, date=_ago(1))
    r = _route(30)
    assert r["balance"] == 15_000
    s = _ins().cash_series(30)
    assert _past(r)[-1]["balance"] == _past(s)[-1]["balance"] == round(f.total_balance()) == 15_000


# Был xfail(P2): income += считал всё, что не expense — теперь только kind == "income".
def test_route_avg_day_income_ignores_transfers():
    f = _fin()
    f.set_balance(_main(), 10_000)
    f.set_balance(M, 5_000)
    f.add_transaction(1_000, "transfer", None, None, _main(), M, date=_ago(1))
    assert _route(30)["avg_day_income"] == 0


# Был xfail(P2): два источника «сегодня» — роут переведён на insights.now_tz(), как cash_series.
def test_route_and_series_share_one_today(monkeypatch):
    f = _fin()
    f.set_balance(_main(), 10_000)
    # «часовой пояс владельца впереди локального времени сервера» — ровно то, что ловит now_tz()
    monkeypatch.setattr(_ins(), "now_tz", lambda: datetime.now() + timedelta(days=1))
    s = _ins().cash_series(30)
    assert _past(_route(30))[-1]["date"] == s["today"]


# P2 закрыт: cash_forecast считает число повторов регулярных от горизонта (недельный платёж за
# 90 дней — ~13 событий, а не 6). Был xfail(strict) в core/services/insights.py.
def test_weekly_recurring_is_not_capped_at_six_occurrences():
    f = _fin()
    f.set_balance(_main(), 100_000)
    f.add_recurring("Интернет", 500, day=1, period="weekly")
    fc = _ins().cash_forecast(90)
    n = sum(1 for p in fc["points"]
            if any(e.get("title") == "Интернет" for e in (p.get("events") or [])))
    assert n >= 12, f"недельный платёж за 90 дней должен встретиться ~12 раз, встретился {n}"
