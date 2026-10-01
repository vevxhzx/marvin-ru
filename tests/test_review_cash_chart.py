"""ЧАСТЬ 1Г — ряд «касса на 30 дней» (`insights.cash_series`).

Ответ на вопрос владельца «что рисуется»: точка = **баланс на конец дня**, а не дневная дельта.
Дельта хранится отдельным полем `delta` (= balance[i] − balance[i−1]) и подписана в подсказке.

Здесь же проверяется причина фальшивого пика перед «сегодня»: перевод между своими счетами и
платёж по «чисто долговому» счёту не меняют общий баланс, но раньше попадали в ряд как траты.

Тесты идут на временной БД (tmp_path), настоящая data/*.db не открывается.
"""
import os
from datetime import date, datetime, timedelta

import pytest

os.environ["ASSISTANT_TEST"] = "1"

from core import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlmodel import create_engine
    from sqlalchemy import event
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


def _ago(days: int, hour: int = 12) -> datetime:
    """Дата «N дней назад» в 12:00 — чтобы не соскальзывало через полночь."""
    base = datetime.now().replace(hour=hour, minute=0, second=0, microsecond=0)
    return base - timedelta(days=days)


ACC = "Основной"   # счёт, которым оперируем в тестах (db.init_db() создаёт свои)


def _past(s: dict) -> list[dict]:
    return [p for p in s["points"] if p["kind"] == "past"]


def _future(s: dict) -> list[dict]:
    return [p for p in s["points"] if p["kind"] == "future"]


def _invariants(s: dict) -> None:
    """Общие для любых демо-данных проверки: ряд — баланс на конец дня."""
    pts = s["points"]
    assert pts[0]["date"] < pts[-1]["date"]
    # сумма дельт == изменение баланса от первого дня до последнего
    assert sum(p["delta"] for p in pts[1:]) == pts[-1]["balance"] - pts[0]["balance"]
    # delta точки = изменение баланса к предыдущей точке
    for prev, cur in zip(pts, pts[1:]):
        assert abs(cur["delta"] - (cur["balance"] - prev["balance"])) <= 1


# ------------------------------------------------------------------ что рисуется

def test_series_is_balance_at_end_of_day():
    from core.services import finance, insights
    finance.set_balance(ACC, 10_000)
    finance.add_transaction(1_500, "expense", account=ACC, note="кофе", date=_ago(2))
    finance.add_transaction(9_000, "income", account=ACC, note="зарплата", date=_ago(1))

    s = insights.cash_series(30)
    past = _past(s)
    # последняя точка прошлого = сегодня и совпадает с единым источником баланса
    assert past[-1]["date"] == s["today"] == date.today().isoformat()
    assert past[-1]["balance"] == round(finance.total_balance()) == 17_500
    # баланс на конец дня: зарплата, пришедшая вчера, уже внутри баланса за вчера,
    # а в балансе за 2 дня назад её ещё нет — и ровно на этом дне delta = +9 000
    assert past[-2]["balance"] == 17_500 and past[-2]["delta"] == 9_000   # день зарплаты
    assert past[-3]["balance"] == 8_500 and past[-3]["delta"] == -1_500   # день траты на 1 500
    _invariants(s)


def test_first_point_also_has_delta():
    """У самой первой точки есть дельта: день ДО неё тоже попадает в выборку операций."""
    from core.services import finance, insights
    finance.set_balance(ACC, 10_000)
    finance.add_transaction(700, "expense", account=ACC, note="обед", date=_ago(31))
    finance.add_transaction(300, "expense", account=ACC, note="кофе", date=_ago(30))

    s = insights.cash_series(30)
    first = s["points"][0]
    assert first["date"] == (date.today() - timedelta(days=s["history_days"])).isoformat()
    assert first["delta"] == -300               # операция ровно на первой точке видна в её delta
    # операция ДО окна уже учтена в балансе первой точки (она случилась раньше конца этого дня)
    assert first["balance"] == round(finance.total_balance()) == 9_000


# ------------------------------------------------------------------ причина пика

def test_transfer_between_own_accounts_makes_no_fake_peak():
    """Перевод своих денег с счёта на счёт не меняет общий баланс — пика быть не должно."""
    from core.services import finance, insights
    finance.set_balance(ACC, 50_000)
    finance.set_balance("Вклад", 0)
    day = _ago(3)
    finance.add_transaction(20_000, "transfer", account="Основной", to_account="Вклад", date=day)

    s = insights.cash_series(30)
    past = _past(s)
    i = next(k for k, p in enumerate(past) if p["date"] == day.date().isoformat())
    assert past[i]["balance"] == past[-1]["balance"] == 50_000
    assert past[i]["delta"] == 0
    assert all(p["balance"] == 50_000 for p in past)
    # но перевод виден событием — подсказка объясняет день, а не молчит
    assert any("Перевод" in e["title"] for e in past[i]["events"])
    _invariants(s)


def test_payment_on_debt_only_account_is_not_a_drop():
    """Платёж по «чисто долговому» счёту не уменьшает общий баланс."""
    from core.services import finance, insights
    finance.set_balance(ACC, 30_000)
    finance.add_account("Долг банку", kind="debt_only", balance=0)
    day = _ago(2)
    finance.add_transaction(5_000, "expense", category="Долги", account="Долг банку", note="рассрочка", date=day)

    s = insights.cash_series(30)
    past = _past(s)
    i = next(k for k, p in enumerate(past) if p["date"] == day.date().isoformat())
    assert past[i]["balance"] == 30_000 and past[i]["delta"] == 0
    _invariants(s)


# ------------------------------------------------------------------ границы

def test_no_transactions_is_flat_series():
    from core.services import finance, insights
    finance.set_balance(ACC, 12_345)
    s = insights.cash_series(30)
    past = _past(s)
    assert all(p["balance"] == 12_345 and p["delta"] == 0 for p in past)
    assert s["balance"] == 12_345 and s["min_balance"] >= 0 and s["runway_days"] is None
    _invariants(s)


def test_boundaries_dates_are_consecutive_and_clamped():
    from core.services import finance, insights
    finance.set_balance(ACC, 5_000)
    for days, horizon in ((1, 7), (0, 30), (30, 30), (90, 90), (999, 365)):
        s = insights.cash_series(days)
        assert s["horizon_days"] == horizon
        pts = s["points"]
        assert len(_past(s)) == s["history_days"] + 1
        assert len(_future(s)) == horizon
        assert len(pts) == s["history_days"] + 1 + horizon
        # даты идут подряд, без пропусков и дублей
        dates = [date.fromisoformat(p["date"]) for p in pts]
        assert all((b - a).days == 1 for a, b in zip(dates, dates[1:]))
        assert dates[-1] - dates[0] == timedelta(days=len(pts) - 1)


def test_month_start_boundary(monkeypatch):
    """«Сегодня» = 1-е число: ряд должен пережить переход через месяц и год."""
    from core.services import finance, insights
    finance.set_balance(ACC, 8_000)
    monkeypatch.setattr(insights, "now_tz", lambda: datetime(2026, 3, 1, 9, 30))
    s = insights.cash_series(30)
    assert s["today"] == "2026-03-01"
    pts = s["points"]
    assert pts[-1]["date"] == "2026-03-31"
    assert pts[0]["date"] == "2026-01-30"          # 30 дней назад через февраль (в феврале 28 дней)
    assert [p for p in pts if p["date"] == "2026-03-01"][0]["kind"] == "past"
    assert [p for p in pts if p["date"] == "2026-03-02"][0]["kind"] == "future"
    _invariants(s)


def test_future_recurring_payment_appears_as_event():
    from core.db import Recurring, session
    from core.services import finance, insights
    finance.set_balance(ACC, 20_000)
    when = datetime.now() + timedelta(days=3)
    rid = finance.add_recurring("Аренда", 15_000, day=when.day, kind="expense", category="Жильё").id
    with session() as s2:                      # тесту нужна конкретная дата платежа
        rec = s2.get(Recurring, rid)
        rec.next_date = when
        s2.add(rec)
        s2.commit()

    s = insights.cash_series(30)
    fut = _future(s)
    with_ev = [p for p in fut if p["events"]]
    assert with_ev, "регулярный платёж должен попасть в события будущего"
    p = with_ev[0]
    i = fut.index(p)
    assert p["date"] == when.date().isoformat()
    # в день платежа баланс падает ровно на сумму платежа (расходов в демо-данных нет)
    assert p["balance"] == fut[i - 1]["balance"] - 15_000
    assert p["delta"] == p["balance"] - fut[i - 1]["balance"]
    _invariants(s)


def test_negative_balance_line_and_runway():
    from core.services import finance, insights
    finance.set_balance(ACC, -5_000)
    for d in range(0, 10):
        finance.add_transaction(1_000, "expense", account=ACC, category="Еда", note="еда", date=_ago(d))
    s = insights.cash_series(30)
    assert _past(s)[-1]["balance"] == round(finance.total_balance()) == -15_000
    assert s["min_balance"] < 0
    assert s["runway_days"] is not None and s["runway_days"] >= 1
    # минимум действительно достигается в будущем
    assert s["min_date"] > s["today"]
    _invariants(s)


# ------------------------------------------- несколько наборов демо-данных (пик/сходимость)

@pytest.mark.parametrize("seed", [0, 1, 2])
def test_demo_datasets_reconcile(seed):
    from core.services import finance, insights
    if seed == 0:                      # зарплата + регулярные траты
        finance.set_balance(ACC, 40_000)
        finance.set_balance("Вклад", 0)
        finance.add_transaction(60_000, "income", account=ACC, note="зарплата", date=_ago(5))
        for d in (1, 3, 8):
            finance.add_transaction(1_200 + d * 10, "expense", account=ACC, category="Еда", note="еда", date=_ago(d))
    elif seed == 1:                    # переводы и наличные
        finance.set_balance(ACC, 15_000)
        finance.set_balance("Наличные", 3_000)
        finance.set_balance("Вклад", 0)
        finance.add_transaction(5_000, "transfer", account=ACC, to_account="Наличные", date=_ago(1))
        finance.add_transaction(900, "expense", category="Транспорт", account="Наличные", note="такси", date=_ago(1))
        finance.add_transaction(25_000, "transfer", account=ACC, to_account="Вклад", date=_ago(6))
    else:                              # долг и подписка, баланс уходит в минус
        finance.set_balance(ACC, 2_000)
        finance.add_account("Долг", kind="debt_only", balance=0)
        finance.add_transaction(1_990, "expense", account=ACC, category="Подписки", note="диск", date=_ago(4))
        finance.add_transaction(3_000, "expense", category="Долги", account="Долг", note="долг", date=_ago(4))
        finance.add_transaction(1_500, "expense", account=ACC, category="Еда", note="еда", date=_ago(1))

    s = insights.cash_series(30)
    assert _past(s)[-1]["balance"] == round(finance.total_balance())
    _invariants(s)


def test_api_forecast_keeps_existing_contract():
    """Контракт /api/finance/forecast не должен поехать (существующие поля на месте)."""
    from core.services import finance, insights
    finance.set_balance(ACC, 25_000)
    s = insights.cash_series(30)
    for key in ("points", "horizon_days", "avg_day_spent", "avg_day_income", "runway_days",
                "min_balance", "min_date", "balance", "scenarios"):
        assert key in s, f"пропал ключ {key}"
    assert s["scenarios"]["realistic"]["points"][0]["balance"] == s["balance"]
    assert {"realistic", "pessimistic"} == set(s["scenarios"])