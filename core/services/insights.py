"""Аналитика и «умные» подсказки: прогноз кассы, подписки, стрик, дни рождения, дайджест недели, связи заметок.

Всё считается локально по базе. LLM (локальная) — только для еженедельного дайджеста мыслей.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import or_
from sqlmodel import select

from ..config import TZ
from ..db import Memory, Note, Task, Transaction, cached, get_setting, session, set_setting
from . import calendar, finance, regime
from .finance import money
from .plural import days as _days_word

log = logging.getLogger("jarvis.insights")


def now_tz() -> datetime:
    """«Сейчас» в часовом поясе владельца (``config.TZ``, по умолчанию Europe/Moscow).

    tzinfo убираем: в базе даты лежат без него, а в коде они сравниваются с ``datetime.now()``.
    Единый источник «сегодня» — от него считаются прогноз, ряд графика и подписи на сайте,
    иначе при сервере в другом часовом поясе график уезжал бы на день.
    """
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(TZ or "Europe/Moscow")).replace(tzinfo=None)
    except Exception:  # pragma: no cover — нет tzdata
        log.debug("zoneinfo %s недоступен, берём локальное время сервера", TZ)
        return datetime.now()


# ---------------------------------------------------------------- прогноз кассы

# Пессимистичный сценарий: те же ожидаемые оплаты по заказам, но клиенты платят с задержкой.
# Реалистичный — оплата приходит к ожидаемой дате (как раньше). Константа, чтобы сценарий был
# объяснимым и настраиваемым, а не «магической» случайной цифрой.
PESSIMISTIC_DELAY_DAYS = 14


def _project(balance: float, per_day: float, sched: dict, days: int, now: datetime):
    """Прогон баланса по дням: ежедневные переменные траты + события из расписания дня."""
    points, cur, low, low_day = [], balance, balance, now.date()
    for i in range(days + 1):
        d = (now + timedelta(days=i)).date()
        items = sched.get(d, [])
        if i > 0:
            cur -= per_day
            cur += sum(a for _, a in items)
        if cur < low:
            low, low_day = cur, d
        points.append({"date": d.isoformat(), "balance": round(cur), "events": [{"title": t, "amount": a} for t, a in items]})
    return points, low, low_day


def _scenario(balance: float, per_day: float, sched: dict, days: int, now: datetime,
              expected_income: float = 0.0, delay_days: int | None = None) -> dict:
    points, low, low_day = _project(balance, per_day, sched, days, now)
    out = {"points": points, "low": round(low), "low_date": low_day.isoformat(),
           "ok": low >= 0, "per_day": round(per_day), "expected_income": round(expected_income)}
    if delay_days is not None:
        out["delay_days"] = delay_days
    return out


def _clone_sched(sched: dict) -> dict:
    return defaultdict(list, {k: list(v) for k, v in sched.items()})


def _spend_rows(days: int = 30) -> tuple[list[tuple[datetime, float]], int | None]:
    """Переменные траты за окно: [(дата, сумма)] и дней в окне (None — считаем по всем данным).

    Фильтры уехали в SQL: раньше тянулись ВСЕ колонки ВСЕХ операций за 30 дней (до 100 тысяч
    строк), чтобы в Python отбросить лишние. Дата берётся по datetime.now(), как раньше в
    finance.list_transactions, — иначе на сервере в другом часовом поясе окно поехало бы.

    Считается активный «режим жизни» (services/regime.py): если он есть и включён, окно — это
    его период (с начала по «сегодня»/по дату конца), а не «последние 30 дней».
    """
    cw = regime.count_window(days)
    since = cw[0] if cw else datetime.now() - timedelta(days=days)
    with session() as s:
        q = (select(Transaction.date, Transaction.amount)
             .where(Transaction.date >= since, Transaction.kind == "expense",
                    or_(Transaction.category.is_(None), Transaction.category != "Долги"),
                    or_(Transaction.note.is_(None), Transaction.note.notlike("%(авто)%"))))
        if cw:
            q = q.where(Transaction.date < cw[1])
        rows = s.exec(q.order_by(Transaction.date.desc()).limit(100_000)).all()
    return [(d, float(a)) for d, a in rows], (cw[2] if cw else None)


def cash_forecast(days: int = 30, pessimistic_delay_days: int | None = None) -> dict:
    """Баланс по дням на N дней вперёд.

    Учитывает регулярные платежи/доходы, ожидаемые оплаты по заказам CRM и средние переменные
    траты в день. Возвращает два сценария: ``realistic`` (оплаты по заказам к ожидаемой дате) и
    ``pessimistic`` (те же оплаты сдвинуты на ``pessimistic_delay_days``, по умолчанию
    ``PESSIMISTIC_DELAY_DAYS``). Верхнеуровневые поля (points/low/low_date/ok/…) — это
    реалистичный сценарий, как и раньше (обратная совместимость).

    Результат кэшируется на несколько секунд (core.db.cached): прогноз считает десятки
    запросов, а страница зовёт его и сама, и через cash_forecast_text(). Любая запись в базу
    кэш сразу сбрасывает — цифры не устаревают.
    """
    return cached(f"forecast:{days}:{pessimistic_delay_days}",
                  lambda: _cash_forecast(days, pessimistic_delay_days))


def _cash_forecast(days: int = 30, pessimistic_delay_days: int | None = None) -> dict:
    now = now_tz()
    balance = finance.total_balance()
    rec = finance.list_recurring()
    # средние переменные траты в день (без авто и долгов): по окну режима жизни, если он
    # считается, иначе — как раньше, по последним 30 дням
    txs, win_days = _spend_rows(30)
    if win_days:
        span = max(1, win_days)
    else:
        first = min((d for d, _ in txs), default=now - timedelta(days=30))
        span = max(7, (now - first).days) if txs else 30
    per_day = sum(a for _, a in txs) / span if txs else 0.0
    # события регулярных платежей/доходов: количество повторов считаем от горизонта, а не
    # константой — недельная подписка за 90 дней встречается ~13 раз, а не 6 (P2 ревью B).
    # 7 дней — минимальный период (weekly), дальше цикл обрывается по горизонту.
    max_repeats = max(6, days // 7 + 2)
    sched_base: dict[date, list[tuple[str, float]]] = defaultdict(list)
    for r in rec:
        d = r.next_date
        for _ in range(max_repeats):
            if d.date() > (now + timedelta(days=days)).date():
                break
            sched_base[d.date()].append((r.title, r.amount if r.kind == "income" else -r.amount))
            d = finance._next_date(r.day, r.period, d)
    # ожидаемые оплаты по заказам (фриланс): остаток по незакрытым заказам на дату дедлайна
    expected_total, tax_total = 0.0, 0.0
    income_events: list[tuple[datetime, str, float]] = []
    try:
        from . import orders, pulse
        rate = pulse.tax_rate()   # налог самозанятого (режим фрилансера); 0 — не считаем
        for e in orders.expected_income(days):
            net = e["amount"] * (1 - rate)
            income_events.append((e["date"], f"ожидается: {e['title']}", net))
            expected_total += net
            tax_total += e["amount"] - net
    except Exception as e:  # pragma: no cover
        log.debug("expected income: %s", e)
    delay = PESSIMISTIC_DELAY_DAYS if pessimistic_delay_days is None else max(0, int(pessimistic_delay_days))
    horizon = (now + timedelta(days=days)).date()
    sched_real, sched_pess = _clone_sched(sched_base), _clone_sched(sched_base)
    # сценарии отличаются только датой поступления ожидаемых оплат по заказам
    pess_expected = 0.0
    for dt, title, net in income_events:
        sched_real[dt.date()].append((title, net))          # orders.expected_income уже в горизонте
        pd = dt + timedelta(days=delay)
        if pd.date() <= horizon:
            sched_pess[pd.date()].append((title, net))
            pess_expected += net
    points, low, low_day = _project(balance, per_day, sched_real, days, now)
    scenarios = {
        "realistic": _scenario(balance, per_day, sched_real, days, now, expected_income=expected_total, delay_days=0),
        "pessimistic": _scenario(balance, per_day, sched_pess, days, now, expected_income=pess_expected, delay_days=delay),
    }
    incomes = [r for r in rec if r.kind == "income"]
    next_income = min((r.next_date for r in incomes), default=None)
    days_to_income = (next_income.date() - now.date()).days if next_income else None
    # сколько можно тратить в день, чтобы к зарплате не уйти ниже нуля
    reserved = sum(r.amount for r in rec if r.kind == "expense" and next_income and r.next_date < next_income)
    safe_per_day = ((balance - reserved) / max(1, days_to_income)) if days_to_income else None
    return {"points": points, "per_day": round(per_day), "low": round(low), "low_date": low_day.isoformat(),
            "next_income": next_income.isoformat() if next_income else None, "days_to_income": days_to_income,
            "safe_per_day": round(safe_per_day) if safe_per_day is not None else None,
            "expected_income": round(expected_total), "expected_tax": round(tax_total),
            "ok": low >= 0, "scenarios": scenarios, "regime": regime.info()}


def _tx_balance_delta(t: Transaction, debt_only: set[str]) -> float:
    """Насколько операция меняет ОБЩИЙ баланс (``finance.total_balance``).

    Перевод между своими счетами и платежи по «чисто долговым» счетам общий баланс не трогают.
    Раньше они попадали в ряд как траты — и график рисовал фальшивый пик перед «сегодня».
    """
    if t.account and t.account not in debt_only:
        d = float(t.amount) if t.kind == "income" else -float(t.amount)
    else:
        d = 0.0
    if t.kind == "transfer" and t.to_account and t.to_account not in debt_only:
        d += float(t.amount)
    return d


def _tx_event(t: Transaction, delta: float) -> dict:
    """Событие дня для подсказки графика: что именно с балансом сделал этот день."""
    if t.kind == "transfer":
        return {"title": f"Перевод {money(t.amount)}: {t.account} → {t.to_account}", "amount": round(delta)}
    title = t.note or t.category or ("Доход" if t.kind == "income" else "Трата")
    return {"title": title, "amount": round(delta)}


def cash_series(days: int = 30) -> dict:
    """Ряд «касса на N дней» для графика: прошлое — по реальным операциям, будущее — прогноз.

    Каждая точка — **баланс на конец дня** (не дневная дельта). ``delta`` — изменение баланса
    за этот день, ``events`` — операции дня (прошлое) или запланированные поступления/списания
    (будущее), чтобы подсказка могла объяснить скачок. Последняя точка прошлого совпадает с
    ``finance.total_balance()`` — единым источником баланса; ``today`` — единый источник даты.
    Кэш — тот же, что у прогноза (core.db.cached): ряд зовут страница графика и дашборд.
    """
    return cached(f"series:{int(days or 30)}", lambda: _cash_series(days))


def _cash_series(days: int = 30) -> dict:
    horizon = max(7, min(int(days or 30), 365))
    hist = max(30, min(horizon, 90))
    now = now_tz()
    today = now.date()
    balance = finance.total_balance()

    accs = finance.list_accounts()
    debt_only = {a.name for a in accs if a.kind == "debt_only"}

    # операции за окно истории + 1 день (нужен день ДО первой точки, чтобы у неё тоже был delta)
    by_day: dict[date, list[Transaction]] = defaultdict(list)
    for t in finance.list_transactions(hist + 2, 100_000):
        if t.date:
            by_day[t.date.date()].append(t)

    spent = income = 0.0
    # «в среднем в день» по окну режима жизни, если он считается; без режима — по истории ряда
    cw = regime.count_window(hist)
    avg_from = cw[0].date() if cw else today - timedelta(days=hist)
    avg_to = cw[1].date() if cw else today + timedelta(days=1)
    avg_div = cw[2] if cw else hist
    for d, items in by_day.items():
        if d < avg_from or d >= avg_to:
            continue
        for t in items:
            if t.kind == "income":
                income += float(t.amount)
            elif t.kind == "expense":
                spent += float(t.amount)

    # баланс на конец прошедшего дня = текущий баланс − всё, что случилось ПОСЛЕ него.
    # Идём от сегодня к прошлому: на каждом шаге «after» — сумма изменений за более поздние дни.
    # Раньше шли от прошлого к сегодня, из-за чего в точку попадал баланс на НАЧАЛО дня —
    # ряд уезжал на сутки и не сходился с карточками (это и был «пик перед сегодня»).
    points: list[dict] = []
    after = 0.0
    for i in range(0, hist + 1):
        d = today - timedelta(days=i)
        day = by_day.get(d) or []
        delta = sum(_tx_balance_delta(t, debt_only) for t in day)
        points.append({"date": d.isoformat(), "balance": round(balance - after), "kind": "past",
                       "delta": round(delta), "events": [_tx_event(t, _tx_balance_delta(t, debt_only)) for t in day][:8]})
        after += delta
    points.reverse()

    fc = cash_forecast(horizon)
    prev = points[-1]["balance"]
    for p in fc["points"][1:]:
        points.append({"date": p["date"], "balance": p["balance"], "kind": "future",
                       "delta": round(p["balance"] - prev),
                       "events": p.get("events") or []})
        prev = p["balance"]

    fut = [p for p in points if p["kind"] == "future"]
    low = min((p["balance"] for p in fut), default=balance)
    low_date = next((p["date"] for p in fut if p["balance"] == low), today.isoformat())
    runway = next((i + 1 for i, p in enumerate(fut) if p["balance"] <= 0), None)
    return {"points": points, "horizon_days": horizon, "history_days": hist, "today": today.isoformat(),
            "avg_day_spent": round(spent / avg_div), "avg_day_income": round(income / avg_div),
            "avg_days": avg_div,
            "runway_days": runway, "min_balance": round(low), "min_date": low_date,
            "balance": round(balance), "scenarios": fc.get("scenarios"), "regime": regime.info()}


def cash_forecast_text() -> str:
    f = cash_forecast(30)
    parts = [f"Сейчас **{money(f['points'][0]['balance'])}**, тратите в среднем **{money(f['per_day'])}** в день."]
    rg = f.get("regime") or {}
    if rg.get("counted"):
        # честная пометка: среднее посчитано по режиму, а не по всей истории
        parts.insert(0, f"Режим: {rg['label']} — средние считаю по нему, а не по всей истории.")
    if f["days_to_income"] is not None:
        parts.append(f"До ближайшего дохода {f['days_to_income']} {_days_word(f['days_to_income'])} — безопасно тратить до **{money(f['safe_per_day'])}** в день.")
    if f.get("expected_income"):
        parts.append(f"Плюс по заказам ожидается **{money(f['expected_income'])}**" + (f" уже за вычетом налога ~{money(f['expected_tax'])}" if f.get("expected_tax") else "") + " (учтено в прогнозе).")
    if not f["ok"]:
        d = datetime.fromisoformat(f["low_date"])
        parts.append(f"⚠️ При текущем темпе **{d:%d.%m}** уйдёте в минус ({money(f['low'])}). Стоит притормозить.")
    else:
        parts.append(f"Минимум за месяц — {money(f['low'])}, в минус не уходите. Держитесь, сэр.")
    # второй сценарий — только если он реально отличается (иначе не засоряем ответ)
    sc = (f.get("scenarios") or {})
    real, pess = sc.get("realistic") or {}, sc.get("pessimistic") or {}
    if pess and real and (pess.get("low") != real.get("low") or pess.get("ok") != real.get("ok")):
        delay_days = pess.get("delay_days", 0) or 0
        d = datetime.fromisoformat(pess["low_date"])
        if not pess.get("ok"):
            parts.append(f"Пессимистично (оплаты по заказам сдвинуты на ~{delay_days} {_days_word(delay_days)}): к **{d:%d.%m}** минимум {money(pess['low'])} — лучше иметь запас.")
        else:
            parts.append(f"Пессимистично (с задержкой оплат на ~{delay_days} {_days_word(delay_days)}): минимум {money(pess['low'])} — тоже в плюсе.")
    return " ".join(parts)


# ---------------------------------------------------------------- подписки: повторяющиеся списания
def detect_subscriptions() -> list[dict]:
    """Одинаковые суммы с той же заметкой/категорией раз в ~месяц, которых нет в регулярных."""
    # четыре нужных поля, а не все колонки операций за 120 дней; фильтр «авто» — в SQL
    since = datetime.now() - timedelta(days=120)
    with session() as s:
        rows = s.exec(select(Transaction.amount, Transaction.note, Transaction.category, Transaction.date)
                      .where(Transaction.date >= since, Transaction.kind == "expense",
                             or_(Transaction.note.is_(None), Transaction.note.notlike("%(авто)%")))
                      .order_by(Transaction.date.desc()).limit(100_000)).all()
    known = {(r.title or "").lower() for r in finance.list_recurring(active_only=False)}
    groups: dict[tuple, list] = defaultdict(list)
    for amount, note, category, when in rows:
        key = (round(amount), re.sub(r"[^\w]+", " ", (note or category or "").lower()).strip()[:24])
        groups[key].append((category, when))
    out = []
    for (amount, name), items in groups.items():
        if len(items) < 2 or not name:
            continue
        ds = sorted(when for _, when in items)
        gaps = [(b - a).days for a, b in zip(ds, ds[1:])]
        if not gaps or not all(24 <= g <= 37 for g in gaps):
            continue
        if any(name in k or k in name for k in known if k):
            continue
        out.append({"name": name, "amount": amount, "times": len(items), "last": ds[-1].isoformat(), "yearly": amount * 12,
                    "category": items[-1][0]})
    out.sort(key=lambda x: -x["amount"])
    return out


# ---------------------------------------------------------------- стрик ведения
def streak() -> dict:
    """Сколько дней подряд что-то записывали (траты/задачи/заметки/события)."""
    with session() as s:
        # только даты: раньше тянулись все колонки Memory (текст заметки!) ради одного поля
        stamps = s.exec(select(Memory.created_at)
                        .where(Memory.created_at >= datetime.now() - timedelta(days=400),
                               Memory.channel != "system")).all()
    days = {d.date() for d in stamps}
    today = date.today()
    cur, d = 0, today
    if today not in days:
        d = today - timedelta(days=1)   # сегодня ещё не записывали — стрик пока держится со вчера
    while d in days:
        cur += 1; d -= timedelta(days=1)
    best_saved = int(get_setting("streak_best", "0") or 0)
    if cur > best_saved:
        set_setting("streak_best", str(cur)); best_saved = cur
    return {"current": cur, "best": best_saved, "today_done": today in days,
            "days": sorted(x.isoformat() for x in days if x >= today - timedelta(days=371))}


def activity_heatmap(weeks: int = 26) -> list[dict]:
    """Количество записей по дням для тепловой карты."""
    since = datetime.now() - timedelta(weeks=weeks)
    with session() as s:
        # как и в streak(): одной колонкой с датой, а не целыми строками журнала
        stamps = s.exec(select(Memory.created_at)
                        .where(Memory.created_at >= since, Memory.channel != "system")).all()
    counts: dict[str, int] = defaultdict(int)
    for d in stamps:
        counts[d.date().isoformat()] += 1
    return [{"date": k, "count": v} for k, v in sorted(counts.items())]


# ---------------------------------------------------------------- дни рождения
BDAY_RX = re.compile(r"\b(др|день\s+рождени\w*|днюх\w*|birthday)\b", re.I)


def upcoming_birthdays(days: int = 7) -> list[dict]:
    """Ежегодные события с «др/день рождения» в названии в ближайшие N дней."""
    now = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for e in calendar.list_events(now, now + timedelta(days=days + 1), limit=200):
        # только ежегодные: «др мамы каждый год 14 марта». Разовое «иду на др 12-го» — обычный план, не праздник
        if e.repeat == "yearly" and BDAY_RX.search(e.title):
            out.append({"id": e.id, "title": e.title, "date": e.start.isoformat(), "in_days": (e.start.date() - now.date()).days,
                        "who": re.sub(r"^\W*(др|день\s+рождения|днюха)\W*", "", e.title, flags=re.I).strip() or e.title})
    return out


# ---------------------------------------------------------------- связи между заметками
async def related_notes(note_id: int, limit: int = 4) -> list[dict]:
    """Связи заметки из таблицы Relation (эмбеддинги отобрали кандидатов, нейронка решила, крестик — убрал).
    Если для заметки ещё не считали — считаем сейчас (одна заметка = один запрос к модели)."""
    from . import relations
    key = f"note:{note_id}"
    if relations.enabled() and key in relations.pending(10_000):
        try:
            await relations.compute(key)
        except Exception as e:
            log.warning("related_notes(%s): %s", note_id, e)
    return relations.related(key, limit)


# ---------------------------------------------------------------- еженедельный дайджест мыслей
WEEKLY_PROMPT = """Ты — личный ассистент. Ниже заметки и ссылки человека за неделю, а также его незакрытые задачи.
Сделай короткий воскресный обзор по-русски, дружелюбно и с лёгкой иронией (обращение «{owner}»), формат:

**Темы недели** — 2–3 главные темы одной строкой каждая.
**Стоит превратить в задачу** — 1–3 мысли, которые звучат как дело, но задачей не стали (цитируй кратко).
**Забросили** — 1–2 задачи, которые висят дольше всего (если есть).
**Одна мысль** — короткое наблюдение или мотивирующий подкол в конце.

Не выдумывай того, чего нет в данных. Если заметок мало — так и скажи, коротко."""


def _weekly_prompt() -> str:
    from ..brain.persona import OWNER
    return WEEKLY_PROMPT.replace("{owner}", OWNER or "друг")


async def weekly_digest() -> str | None:
    from ..brain import llm
    since = datetime.now() - timedelta(days=7)
    with session() as s:
        notes = s.exec(select(Note).where(Note.created_at >= since).order_by(Note.created_at)).all()
        from ..db import Link
        links = s.exec(select(Link).where(Link.created_at >= since)).all()
        open_tasks = s.exec(select(Task).where(Task.done == False).order_by(Task.created_at)).all()  # noqa: E712
        done_week = s.exec(select(Task).where(Task.done == True, Task.done_at != None, Task.done_at >= since)).all()  # noqa: E711,E712
    if not notes and not links:
        return None
    data = ["ЗАМЕТКИ:"] + [f"- [{n.created_at:%a}] {n.title or ''}: {n.text[:200]}" for n in notes]
    data += ["ССЫЛКИ:"] + [f"- {l.title or l.url} ({', '.join(filter(None, [l.comment, l.tags]))})" for l in links[:15]]
    data += ["ОТКРЫТЫЕ ЗАДАЧИ (старые первыми):"] + [f"- {t.title} (с {t.created_at:%d.%m})" for t in open_tasks[:12]]
    data += [f"ВЫПОЛНЕНО ЗА НЕДЕЛЮ: {len(done_week)}"]
    from . import pulse
    tail = "".join("\n" + x for x in pulse.weekly_block())   # цифры фриланса — отдельными строками, модели не доверяем их пересказывать
    root = f"✨ **ИТОГИ НЕДЕЛИ** · по {datetime.now():%d.%m}"
    if not await llm.ollama_available() and llm.MODE == "cloud" and llm.cloud_enabled():
        try:
            txt = await llm.cloud_chat(_weekly_prompt(), "\n".join(data))
            if txt:
                return root + "\n" + txt.strip() + tail
        except Exception as e:
            log.warning("weekly digest (cloud) failed: %s", e)
    if not await llm.ollama_available():
        # без LLM — простой вариант
        tags: dict[str, int] = defaultdict(int)
        for n in notes:
            for t in filter(None, n.tags.split(",")):
                tags[t] += 1
        top = ", ".join(k for k, _ in sorted(tags.items(), key=lambda kv: -kv[1])[:3]) or "без тегов"
        return (f"{root}\n{len(notes)} заметок, {len(links)} ссылок, закрыто задач — {len(done_week)}.\n"
                f"Темы: {top}. Открытых задач: {len(open_tasks)}" + (f", самая старая — «{open_tasks[0].title}»." if open_tasks else ".") + tail)
    try:
        out = await llm.ollama_chat([{"role": "system", "content": _weekly_prompt()}, {"role": "user", "content": "\n".join(data)}], temperature=0.5)
        txt = (out.get("content") or "").strip()
        return (root + "\n" + txt + tail) if txt else None
    except Exception as e:
        log.warning("weekly digest failed: %s", e)
        return None


# ---------------------------------------------------------------- лимиты: вечерний статус
def budget_alerts() -> list[str]:
    """Категории, где перешли 80% / 100% лимита (сообщаем один раз на порог в месяц)."""
    out = []
    month = datetime.now().strftime("%Y-%m")
    for b in finance.budgets():
        for thr, label in ((1.0, "over"), (0.8, "warn")):
            if b["pct"] >= thr:
                key = f"budget_alert:{month}:{b['id']}:{label}"
                if get_setting(key):
                    break
                set_setting(key, "1")
                if label == "over":
                    out.append(f"🚨 «{b['name']}»: лимит {money(b['budget'])} исчерпан — потрачено {money(b['spent'])}. Дальше только сила воли, сэр.")
                else:
                    out.append(f"⚠️ «{b['name']}»: {b['pct'] * 100:.0f}% лимита ({money(b['spent'])} из {money(b['budget'])}), а месяц прошёл на {b['pace'] * 100:.0f}%.")
                break
    return out


def subscriptions_nudge() -> str | None:
    """Раз в месяц: найденные подписки, о которых ассистент ещё не говорил."""
    subs = detect_subscriptions()
    if not subs:
        return None
    told = set(filter(None, (get_setting("subs_told", "") or "").split("|")))
    new = [s for s in subs if s["name"] not in told]
    if not new:
        return None
    set_setting("subs_told", "|".join(told | {s["name"] for s in new}))
    lines = ["🔁 **Похоже на подписки** (списываются каждый месяц, но в регулярных их нет):"]
    lines += [f"— {s['name']} · **{money(s['amount'])}**/мес ({s['times']} раз, ~{money(s['yearly'])} в год)" for s in new[:5]]
    lines.append("Скажите «регулярный <название> <сумма>» — добавлю в обязательные, или «отмени подписку» — напомню отменить.")
    return "\n".join(lines)


# ---------------------------------------------------------------- «протокол Чистый лист»
def archive_done_tasks(days: int = 30) -> int:
    """Убрать из выдачи выполненные задачи старше N дней (пометкой project='archive' — ничего не удаляем)."""
    cutoff = datetime.now() - timedelta(days=days)
    n = 0
    with session() as s:
        for t in s.exec(select(Task).where(Task.done == True, Task.done_at != None, Task.done_at < cutoff)).all():  # noqa: E711,E712
            if t.project != "archive":
                t.project = "archive"; s.add(t); n += 1
        s.commit()
    return n
