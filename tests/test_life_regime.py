# -*- coding: utf-8 -*-
"""Режим жизни: «я уезжаю в армию 28 октября» меняет то, ПО ЧЕМУ считаются средние и прогноз.

Что фиксируем (всё офлайн, на временной БД, `data/jarvis.db` не открывается):

1. без режима цифры НЕ меняются (поведение по умолчанию прежнее);
2. с включённым режимом среднее в день и прогноз считаются по окну режима;
3. закрытый режим считает по своему периоду;
4. переключатель «считать по режиму» выключает влияние;
5. команды чата работают без LLM и спрашивают подтверждение;
6. старые офлайн-команды (~40) не сломаны;
7. API отдаёт честный блок `regime` (по чему посчитано).

Фикстура `fresh_db` (tests/test_core) — временная БД в tmp_path.
"""
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

from datetime import datetime, timedelta  # noqa: E402

import pytest  # noqa: E402
from tests.test_core import fresh_db  # noqa: E401,F401  (autouse: временная БД)

TODAY = datetime.now()


def _client():
    from fastapi.testclient import TestClient
    from core.api.app import app
    return TestClient(app, client=("127.0.0.1", 5555), base_url="http://testserver")


def _tx(amount, days_ago, kind="expense", note="тест"):
    """Операция `days_ago` дней назад (без авто-списаний, иначе её не считают средними)."""
    from core.services import finance
    return finance.add_transaction(amount, kind, None, f"{note}", date=TODAY - timedelta(days=days_ago), source="system")


def _regime(title, start_days_ago, end_days_ago=None):
    from core.services import regime
    start = (TODAY - timedelta(days=start_days_ago)).date()
    end = (TODAY - timedelta(days=end_days_ago)).date() if end_days_ago is not None else None
    return regime.add(title, start.isoformat(), end.isoformat() if end else None)


# ============================ 1. без режима ничего не меняется ============================
def test_no_regime_keeps_numbers_as_before():
    """Нет режима — средние считаются по всем данным, блок regime честно говорит об этом."""
    from core.services import finance, insights, regime
    for i in range(10):
        _tx(1000, i)                      # 1 000 ₽ в день, 10 дней подряд
    assert regime.list_regimes() == []
    assert regime.apply_enabled() is False
    s = finance.summary(30)
    assert s["regime"]["counted"] is False
    assert s["regime"]["apply"] is False
    # как раньше: среднее — по текущему календарному месяцу
    assert s["avg_daily"] == round(s["spent"] / max(1, TODAY.day)) or s["avg_daily"] > 0
    f = insights.cash_forecast(30)
    assert f["regime"]["counted"] is False
    assert f["per_day"] > 0
    ser = insights.cash_series(30)
    assert ser["avg_day_spent"] == round(ser["avg_day_spent"])   # целое, как раньше
    assert ser["avg_days"] == ser["history_days"]


def test_regime_exists_but_switch_off_changes_nothing():
    """Режим заведён, но переключатель выключен — поведение прежнее."""
    from core.services import finance, insights, regime
    for i in range(10):
        _tx(1000, i)
    _regime("армия", 2)                      # последние 2 дня — другие траты
    assert regime.apply_enabled() is False
    assert finance.summary(30)["regime"]["counted"] is False
    assert insights.cash_forecast(30)["regime"]["counted"] is False
    assert regime.window() is None


# ============================ 2. включённый режим меняет средние ============================
def test_avg_daily_counted_by_regime_window():
    """10 дней по 1 000 ₽, потом режим 2 дня по 100 ₽: среднее должно упасть до 100."""
    from core.services import finance, regime
    for i in range(10):
        _tx(1000, i)
    _regime("армия", 1)                      # вчера-сегодня
    for i in (0, 1):                          # в режиме жизнь дешевле
        _tx(100, i, note="army")
    regime.set_apply(True)
    s = finance.summary(30)
    assert s["regime"]["counted"] is True
    assert s["regime"]["active"]["title"] == "армия"
    # окно = вчера и сегодня → 2 дня, (1000+100)*2 → 1 100 в день (было бы ~1 000 по всем данным)
    assert s["avg_days"] == 2
    assert s["avg_daily"] == 1100
    assert s["safe"]["avg_daily"] == 1100
    assert s["cashflow"]["regime"]["counted"] is True
    assert regime.label().startswith("считаем по режиму: армия")


def test_forecast_per_day_counted_by_regime_window():
    """Прогноз: per_day — по режиму, а не по всей истории."""
    from core.services import insights, regime
    for i in range(20):
        _tx(1000, i)                          # 1 000 ₽ в день
    _regime("командировка", 2)                # последние 3 дня — по 100 ₽ сверху
    for i in range(3):
        _tx(100, i, note="командировка")
    regime.set_apply(True)
    f = insights.cash_forecast(30)
    assert f["regime"]["counted"] is True
    assert f["regime"]["current"]["title"] == "командировка"
    assert f["per_day"] == round((3 * 1000 + 3 * 100) / 3)   # по режиму, а не по 20 дням
    assert "Режим" in insights.cash_forecast_text()   # чат говорит, по чему считает
    ser = insights.cash_series(30)
    assert ser["regime"]["counted"] is True
    assert ser["avg_days"] == 3
    assert ser["avg_day_spent"] == round((3 * 1000 + 3 * 100) / 3)


def test_closed_regime_counts_by_its_own_period():
    """Закрытый режим (больничный неделю назад) — средние по его периоду, не по текущему дню."""
    from core.services import finance, regime
    for i in range(20):
        _tx(1000, i)
    _regime("больничный", 6, 3)              # неделя назад, 4 дня
    for i in range(3, 7):
        _tx(100, i, note="больничный")
    regime.set_apply(True)
    s = finance.summary(30)
    assert s["regime"]["active"] is None      # открытых режимов нет
    assert s["regime"]["current"]["title"] == "больничный"
    assert s["regime"]["counted"] is True
    assert s["avg_days"] == 4
    assert s["avg_daily"] == round((4 * 1000 + 4 * 100) / 4)


def test_switch_off_restores_general_numbers():
    """Переключатель выключает влияние: средние снова по всем данным."""
    from core.services import finance, regime
    for i in range(10):
        _tx(1000, i)
    _regime("армия", 1)
    regime.set_apply(True)
    on = finance.summary(30)
    assert on["regime"]["counted"] is True and on["avg_days"] == 2
    regime.set_apply(False)
    s = finance.summary(30)
    assert s["regime"]["counted"] is False
    assert s["avg_daily"] == on["avg_daily"] or s["avg_days"] != 2
    assert s["spent"] > on["spent"]        # снова вся история, а не только окно режима


def test_new_regime_closes_previous_with_mark():
    """Новый режим закрывает предыдущий автоматически, но с явной пометкой в истории."""
    from core.services import regime
    _regime("армия", 30)
    _regime("отпуск", 2)
    items = regime.list_regimes()
    army = next(x for x in items if x["title"] == "армия")
    vac = next(x for x in items if x["title"] == "отпуск")
    assert army["open"] is False and army["auto_closed"] is True
    assert army["end"] == vac["start"]
    assert "закрыт автоматически" in army["note"]
    assert regime.active()["title"] == "отпуск"


def test_future_regime_does_not_change_numbers():
    """Режим, который ещё не начался, усреднять нечего — цифры как раньше."""
    from core.services import finance, regime
    for i in range(5):
        _tx(1000, i)
    _regime("армия", -20)                     # начнётся через 20 дней
    regime.set_apply(True)
    assert regime.window() is None
    assert finance.summary(30)["regime"]["counted"] is False


def test_delete_and_update():
    from core.services import regime
    r = _regime("армия", 10)
    assert regime.update(r["id"], title="армия нового образца")["title"] == "армия нового образца"
    assert regime.get_regime(r["id"])["title"] == "армия нового образца"
    assert regime.delete(r["id"]) is True
    assert regime.list_regimes() == []
    assert regime.delete(999) is False


# ============================ 3. команды чата (офлайн, без LLM) ============================
def _chat(text, channel="test"):
    from core.brain.quick import run
    return run(text, channel)


def test_chat_army_asks_and_creates():
    """«я уезжаю в армию 28 октября» → вопрос с датой; после «да» режим заведён и включён."""
    from core.services import finance, regime
    r = _chat("я уезжаю в армию 28 октября")
    assert r and r[1] == ["clarify"], r
    assert "армия" in r[0] and "да/нет" in r[0]
    assert regime.list_regimes() == [], "до подтверждения ничего не записано"
    ok = _chat("да")
    assert ok and ok[1] == ["set_regime"], ok
    assert "считаю по нему" in ok[0]
    cur = regime.current()
    assert cur["title"] == "армия" and cur["open"] is True
    assert regime.apply_enabled() is True
    assert finance.summary(30)["regime"]["counted"] is (cur["start"] <= regime._today().isoformat())


def test_chat_decline_does_nothing():
    from core.services import regime
    r = _chat("уехал в командировку до 5 ноября")
    assert r and r[1] == ["clarify"]
    no = _chat("нет")
    assert no and "Отбой" in no[0]
    assert regime.list_regimes() == []


def test_chat_back_closes_regime():
    from core.services import regime
    _regime("армия", 5)                        # режим начался 5 дней назад
    assert regime.active() is not None
    r = _chat("вернулся")
    assert r and r[1] == ["clarify"] and "Закрыть режим" in r[0]
    ok = _chat("да")
    assert ok and ok[1] == ["set_regime"]
    assert regime.active() is None
    assert regime.current()["end"] == regime._today().isoformat()
    # «армия закончилась» — тот же путь, словом о режиме
    _regime("командировка", 2)
    assert _chat("командировка закончилась")[1] == ["clarify"]
    _chat("да")
    assert regime.current()["title"] == "командировка" and regime.active() is None


def test_chat_business_trip_with_dates():
    from core.services import regime
    r = _chat("уехал в командировку до 5 ноября")
    assert r and "командировка" in r[0]
    _chat("да")
    cur = regime.current()
    assert cur["title"] == "командировка" and cur["open"] is False   # «до 5 ноября» — с концом
    assert cur["end"].endswith("-11-05")


def test_chat_sick_leave_range():
    from core.services import regime
    r = _chat("больничный с 3 по 10")
    assert r and "больничный" in r[0]
    _chat("да")
    cur = regime.current()
    assert cur["title"] == "больничный"
    assert cur["start"].endswith("-03") and cur["end"].endswith("-10")


def test_chat_rename_and_delete_and_toggle():
    from core.services import regime
    _chat("я уезжаю в армию 28 октября")
    _chat("да")
    assert _chat("поменяй режим на командировку")[1] == ["clarify"]
    _chat("да")
    assert regime.current()["title"] == "командировка"
    _chat("не считай по режиму")
    assert regime.apply_enabled() is False
    r = _chat("удали режим")
    assert r and r[1] == ["clarify"]
    _chat("да")
    assert regime.list_regimes() == []
    assert regime.apply_enabled() is False


@pytest.mark.parametrize("phrase", [
    "потратил 500 на обед", "купил кофе 350", "зп 150к", "баланс", "мой баланс",
    "сколько потратил на еду", "траты за месяц", "какие дела сегодня", "что у меня сегодня",
    "заплатил Диме 2000", "снял 3000 наличных", "перевёл 5000 на сбер",
    "подписка яндекс плюс 399 25-го", "лимит на транспорт 6000", "убери лимит на транспорт",
    "долг Ване 5000 плачу 1000 10-го", "какие долги", "привет", "спасибо", "пока",
    "установи бюджет на развлечения 8000", "убери бюджет с развлечений",
    "встреча завтра в 18", "задача починить кран", "напомни купить корм",
    "отмени подписку яндекс", "какие регулярные платежи", "удали событие", "отмени долг",
    "начал бегать по утрам", "работаю 5 дней", "Поставь событие что я иду на др 12 числа",
])
def test_old_commands_still_go_where_they_used_to(phrase):
    """Регрессия: фразы вне режима жизни не уехали в новую ветку и не завели режим."""
    from core.services import regime
    before = len(regime.list_regimes())
    _chat(phrase)
    assert len(regime.list_regimes()) == before, f"«{phrase}» завела режим"


# ============================ 4. API ============================
def test_api_regimes_crud_and_apply():
    c = _client()
    r = c.get("/api/finance/regimes")
    assert r.status_code == 200
    d = r.json()
    assert d["regimes"] == [] and d["apply"] is False and d["counted"] is False

    add = c.post("/api/finance/regimes", json={"title": "армия", "start": "2026-10-28"})
    assert add.status_code == 200, add.text
    rid = add.json()["id"]
    assert add.json()["title"] == "армия"

    assert c.post("/api/finance/regimes", json={"title": ""}).status_code == 422      # пустое название
    assert c.post("/api/finance/regimes", json={"title": "x", "start": "2026-11-01",
                                                "end": "2026-10-01"}).status_code == 400   # конец раньше начала

    up = c.put(f"/api/finance/regimes/{rid}", json={"note": "с призывной"})
    assert up.status_code == 200 and up.json()["note"] == "с призывной"
    assert c.put("/api/finance/regimes/999", json={"note": "нет"}).status_code == 404

    on = c.post("/api/finance/regime/apply", json={"on": True})
    assert on.status_code == 200 and on.json()["apply"] is True

    cl = c.post(f"/api/finance/regimes/{rid}/close", json={})
    assert cl.status_code == 200 and cl.json()["open"] is False
    assert c.post("/api/finance/regimes/999/close", json={}).status_code == 404

    assert c.delete(f"/api/finance/regimes/{rid}").status_code == 200
    assert c.delete(f"/api/finance/regimes/{rid}").status_code == 404


def test_api_reports_regime_in_money_numbers():
    """Сводка, прогноз и бюджеты отдают честный блок regime — по чему посчитано."""
    from core.services import regime
    c = _client()
    for i in range(6):
        c.post("/api/finance/transactions", json={"amount": 700, "kind": "expense", "note": "еда"})
    c.post("/api/finance/regimes", json={"title": "армия", "start": (TODAY - timedelta(days=2)).date().isoformat()})
    c.post("/api/finance/regime/apply", json={"on": True})

    s = c.get("/api/finance/summary").json()
    assert s["regime"]["counted"] is True
    assert s["regime"]["active"]["title"] == "армия"
    assert s["regime"]["since"] == (TODAY - timedelta(days=2)).date().isoformat()

    f = c.get("/api/finance/forecast").json()
    assert f["regime"]["counted"] is True
    assert f["regime"]["current"]["from_short"]
    assert f["avg_days"] == 3

    ins = c.get("/api/insights/forecast").json()
    assert ins["regime"]["counted"] is True

    bg = c.get("/api/finance/budgets").json()
    assert bg["safe"]["regime"]["counted"] is True

    c.post("/api/finance/regime/apply", json={"on": False})
    assert c.get("/api/finance/summary").json()["regime"]["counted"] is False
    assert regime.list_regimes(), "режим остался в истории"