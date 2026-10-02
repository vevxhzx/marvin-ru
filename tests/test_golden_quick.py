# -*- coding: utf-8
"""GOLDEN-набор фраз для rules() — регрессия парсинга и ИИ-логики (ревью, часть C).

Запуск одной командой:
    .venv\\Scripts\\python.exe -m pytest tests/test_golden_quick.py -q

Что проверяем: куда уходит фраза (действие) и что реально записалось в БД
(сумма / дата / категория / заголовок). Тест фиксирует ТЕКУЩЕЕ поведение как ожидаемое;
известные расхождения с «правильным» поведением НЕ ломают тест — они описаны в reviews/review_C.md
и помечены в таблице комментарием KNOWN.

Формат таблицы GOLDEN (список кортежей, легко расширять):
    (фраза, ожидаемое_действие, ожидания_по_БД)

  ожидаемое_действие:
    "add_expense" и т.п. — строка через "," из Reply.actions;
    None  — правила не сработали, фраза уходит в модель (LLM);
    ""    — ответ без действий.

  ключи словаря ожиданий (все неупомянутые таблицы обязаны остаться БЕЗ изменений):
    tx        — {"k":kind,"a":amount,"c":категория,"d":дата,"n":заметка(подстрока|None),"to":счёт_назначения}
    task      — {"t":заголовок(подстрока),"due":спека_даты|None}   (новая задача)
    task_upd  — [{"t":...,"due":...}]  (правка уже существующей задачи с тем же заголовком)
    ev        — {"t":заголовок,"s":спека_даты|("win",минуты)}
    debt      — {"t":заголовок,"r":остаток,"p":платёж,"pd":день_платежа}
    rec       — {"t":заголовок,"a":сумма,"d":день,"k":kind}
    rec_upd   — [{"t":...,"active":False}]
    note/fact — подстрока текста
    acc_new   — [{"t":имя,"b":баланс}]  (новый счёт)
    budget    — [("Категория", лимит)]
    reply     — подстрока ответа

  спеки дат (разрешаются во время прогона от текущего момента):
    "today" / "y12"                     — сегодня / вчера 12:00 (для трат)
    "d1_18:00", "d0_10:00", "d2_10:00"  — завтра/сегодня/послезавтра в HH:MM
    "h19:00"                            — сегодня в 19:00, если время ещё не прошло, иначе завтра
    "wd4_11:00"                         — ближайшая пятница в 11:00 (0=пн…6=вс)
    "wd1_10:00~"                        — ближайший вторник в 10:00 (без явного времени в фразе)
    "dl_wd4"                            — дедлайн: ближайшая пятница 23:59
    "sun2359"                           — конец этой недели (вс) 23:59
    "eom2359"                           — последний день текущего месяца 23:59
    "d25_2359"                          — 25-е число (этого месяца, если ещё не прошло) 23:59
    "anch9_25_19:00"                    — 25 сентября в 19:00 (дата >14 дней назад → следующий год)
    ("win", 20)                         — ≈ now+20 минут (окно ±1 мин)

Фразы «потратил 0 на обед» и «потратил 1000000000000000 на еду» сюда НЕ включены:
agent.rules() на них бросает FinanceError (см. reviews/review_C.md, находка P3-2).
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("ASSISTANT_TEST", "1")

from dateutil.relativedelta import relativedelta  # noqa: E402
from sqlalchemy import event  # noqa: E402
from sqlmodel import create_engine, select  # noqa: E402

from core import db  # noqa: E402
from core.brain.dates import parse_amount, parse_datetime, parse_datetime_ex, task_due  # noqa: E402


# ------------------------------------------------------------------ фиксур: временная БД, data/ не трогаем
@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    # Стартовые лимиты. Их нет в сиде (все категории с budget=0), иначе «убери лимит»
    # пишет 0 в уже нулевое поле: дельты нет, и проверка не видит, что команда
    # вообще отработала. Снимаем — до снапшота, на сами кейсы не влияет.
    with db.session() as s:
        for _nm, _b in (("Транспорт", 3000.0), ("Развлечения", 5000.0)):
            _c = s.exec(select(db.Category).where(db.Category.name == _nm)).first()
            if _c is not None:
                _c.budget = _b
        s.commit()
    # Golden проверяет СЛОЙ ПРАВИЛ (работает офлайн и без LLM — правило проекта: ~40 команд без модели).
    # Судья и модель решают неоднозначность по живой qwen/groq: их ответы пляшут от запуска к
    # запуску, и набор превращается в флаки. Выключаем и то и другое — поведение детерминировано.
    # Что делает живая модель на этих фразах — отдельная запись в reviews/review_C.md.
    from core.services import judge as _judge
    from core.brain import llm as _llm

    async def _no_false(*a, **k):
        return False

    async def _no_none(*a, **k):
        return None

    async def _no_empty(*a, **k):
        return ""

    monkeypatch.setattr(_judge, "enabled", lambda: False)
    monkeypatch.setattr(_llm, "ollama_available", _no_false)
    monkeypatch.setattr(_llm, "embed_available", _no_false)
    monkeypatch.setattr(_llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(_llm, "gemini_enabled", lambda: False)
    monkeypatch.setattr(_llm, "ollama_chat", _no_none)
    monkeypatch.setattr(_llm, "cloud_tools_chat", _no_none)
    monkeypatch.setattr(_llm, "cloud_chat", _no_none)
    monkeypatch.setattr(_llm, "gemini_chat", _no_none)
    monkeypatch.setattr(_llm, "small_chat", _no_empty)
    yield


TRACK = {"tx": db.Transaction, "task": db.Task, "ev": db.Event, "debt": db.Debt,
         "rec": db.Recurring, "note": db.Note, "fact": db.Fact, "acc": db.Account, "cat": db.Category}


def _snap():
    out = {}
    for name, cls in TRACK.items():
        with db.session() as s:
            rows = s.exec(select(cls)).all()
        out[name] = {r.id: {c.name: getattr(r, c.name) for c in cls.__table__.columns} for r in rows}
    return out


_WD_NAMES = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1, "wed": 2, "weds": 2,
             "wednesday": 2, "thu": 3, "thur": 3, "thurs": 3, "thursday": 3, "fri": 4,
             "friday": 4, "sat": 5, "saturday": 5, "sun": 6, "sunday": 6}


def _hm(s) -> tuple[int, int]:
    """'18:00' / '2359' / '10:00~' → (час, минута)."""
    s = str(s).rstrip("~")
    if ":" in s:
        h, m = s.split(":", 1)
    elif len(s) == 4 and s.isdigit():
        h, m = s[:2], s[2:]
    else:
        raise AssertionError(f"не разобрано время: {s!r}")
    return int(h), int(m)


def _resolve(spec, t0: datetime):
    """Спека даты → datetime (или None)."""
    if spec is None or isinstance(spec, datetime):
        return spec
    if isinstance(spec, (tuple, list)):                       # ("win", 20) — ≈ now+20 минут
        if len(spec) >= 2 and spec[0] == "win":
            return t0 + timedelta(minutes=float(spec[1]))
        raise AssertionError(f"неизвестная спека даты: {spec!r}")
    spec = str(spec)
    if spec == "today":
        return t0
    if spec == "yesterday":
        return t0 - timedelta(days=1)
    if spec == "tomorrow":
        return t0 + timedelta(days=1)
    if spec == "y12":
        return (t0 - timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
    if spec == "sun2359":
        return (t0 + timedelta(days=6 - t0.weekday())).replace(hour=23, minute=59, second=0, microsecond=0)
    if spec == "eom2359":
        last = (t0.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)
        return last.replace(hour=23, minute=59, second=0, microsecond=0)
    if spec == "d25_2359":
        base = t0.replace(day=1) if t0.day <= 25 else (t0.replace(day=1) + relativedelta(months=1))
        return base.replace(day=25, hour=23, minute=59, second=0, microsecond=0)
    if spec.startswith("win"):                                 # win72h / win61m / win120m / win7d@15:00
        rest = spec[3:]
        if "@" in rest:
            dpart, tpart = rest.split("@", 1)
            h, m = _hm(tpart)
            return (t0 + timedelta(days=int(dpart[:-1]))).replace(hour=h, minute=m, second=0, microsecond=0)
        if len(rest) > 1 and rest[:-1].isdigit() and rest[-1] in "hmd":
            n = float(rest[:-1])
            if rest[-1] == "h":
                return t0 + timedelta(hours=n)
            if rest[-1] == "m":
                return t0 + timedelta(minutes=n)
            return t0 + timedelta(days=n)
        return t0                                               # голый "win"
    if "@" in spec:            # Wed@10:00 / tomorrow@10:00 / 05@10:00 / 09-25@10:00 / 2027-09-25@10:00
        head, _, tail = spec.partition("@")
        h, m = _hm(tail)
        if head == "tomorrow":
            d = t0 + timedelta(days=1)
        elif head.casefold() in _WD_NAMES:                        # ближайший такой день недели (Wed/wed — одинаково)
            wd = _WD_NAMES[head.casefold()]
            delta = (wd - t0.weekday()) % 7
            d = t0 + timedelta(days=(delta or 7))
        elif head.count("-") == 2:                             # 2027-09-25@10:00 — точная дата
            y, mo, dd = map(int, head.split("-"))
            return datetime(y, mo, dd, h, m)
        elif head.count("-") == 1:                             # 09-25@10:00 — месяц-день этого года
            mo, dd = map(int, head.split("-"))
            return t0.replace(month=mo, day=dd, hour=h, minute=m, second=0, microsecond=0)
        elif head.isdigit() and len(head) <= 2:                # 05@10:00 — N-е число ближайшего месяца
            dd = int(head)
            base = t0.replace(day=1)
            if dd <= t0.day:
                base += relativedelta(months=1)
            d = base.replace(day=dd)
        else:
            raise AssertionError(f"неизвестная спека даты: {spec!r}")
        return d.replace(hour=h, minute=m, second=0, microsecond=0)
    if ":" in spec and "_" not in spec and spec[0].isdigit():   # "17:00" — сегодня, если не прошло
        h, m = _hm(spec)
        d = t0 if (h, m) > (t0.hour, t0.minute) else t0 + timedelta(days=1)
        return d.replace(hour=h, minute=m, second=0, microsecond=0)
    parts = spec.split("_")
    if parts[0].startswith("d") and parts[0][1:].isdigit():      # d1_18:00 / d0_10:00 / d1_2359
        h, m = _hm(parts[1])
        return (t0 + timedelta(days=int(parts[0][1:]))).replace(hour=h, minute=m, second=0, microsecond=0)
    if parts[0].startswith("h"):                                 # h19:00 — сегодня, если не прошло
        h, m = _hm(parts[0][1:])
        d = t0 if (h, m) > (t0.hour, t0.minute) else t0 + timedelta(days=1)
        return d.replace(hour=h, minute=m, second=0, microsecond=0)
    if parts[0].startswith("wd"):                                # wd4_11:00 / wd1_10:00~
        wd = int(parts[0][2:])
        h, m = _hm(parts[1])
        no_time = parts[1].rstrip("~").endswith("~") or parts[1].endswith("~")
        delta = (wd - t0.weekday()) % 7
        d = t0 + timedelta(days=delta)
        if delta == 0 and not no_time and (h, m) <= (t0.hour, t0.minute):
            d += timedelta(days=7)  # время уже прошло — берём следующую неделю
        return d.replace(hour=h, minute=m, second=0, microsecond=0)
    if parts[0] == "dl":                                         # dl_wd4 — дедлайн «до пятницы» (строго следующей)
        wd = int(parts[1][2:])
        delta = ((wd - t0.weekday()) % 7) or 7
        return (t0 + timedelta(days=delta)).replace(hour=23, minute=59, second=0, microsecond=0)
    if parts[0].startswith("anch"):                              # anch9_25_19:00 — «25 сентября в 19»
        mon = int(parts[0][4:])
        day = int(parts[1])
        h, m = _hm(parts[2])
        d = t0.replace(month=mon, day=day, hour=h, minute=m, second=0, microsecond=0)
        if (t0.date() - d.date()).days > 14:
            d += relativedelta(years=1)
        return d
    if spec.isdigit() and len(spec) <= 2:                        # "1" — день месяца (для rec)
        dd = int(spec)
        base = t0.replace(day=1)
        if dd <= t0.day:
            base += relativedelta(months=1)
        return base.replace(day=dd, hour=23, minute=59, second=0, microsecond=0)
    raise AssertionError(f"неизвестная спека даты: {spec!r}")


def _has_time(spec) -> bool:
    """Есть ли в спеке явное время (иначе сравниваем только день)."""
    if isinstance(spec, (tuple, list)):
        return False
    s = str(spec)
    if "~" in s or s in ("today", "yesterday", "tomorrow") or s.isdigit():
        return False
    return (":" in s) or ("@" in s) or bool(_re.search(r"\d{4}$", s))


def _dt_ok(actual, spec, t0, tol: float = 60.0) -> bool:
    """actual (datetime из БД) соответствует спеке spec от момента t0."""
    if spec is None:
        return True
    if actual is None:
        return False
    want = _resolve(spec, t0)
    if want is None:
        return True
    if getattr(actual, "tzinfo", None):
        actual = actual.replace(tzinfo=None)
    if actual.date() != want.date():
        return False
    if not _has_time(spec):
        return True
    return abs((actual - want).total_seconds()) <= tol


def _has(actual, spec) -> bool:
    """Подстрока заголовка. Регистр НЕ важен: парсер пишет «Звонок»/«Яндекс плюс»,
    а в наборе писали «звонок»/«яндекс плюс» — это не расхождение поведения,
    а расхождение записи ожидания (см. reviews/review_C.md, дефект проверки №1)."""
    if spec is None:
        return actual is None
    hay = (actual or "").casefold()
    if isinstance(spec, (tuple, list)):
        return all(str(s).casefold() in hay for s in spec)
    return str(spec).casefold() in hay


# ------------------------------------------------------------------ GOLDEN: (фраза, действие, ожидания)
# KNOWN — осознанно зафиксированное текущее поведение, расхождение описано в reviews/review_C.md
GOLDEN = [
    # ---- траты с глаголом
    ("потратил 500 на обед", "add_expense", {"tx": {"k": "expense", "a": 500, "c": "Еда", "d": "today", "n": "обед"}}),
    ("потратил 1500 на такси вчера", "add_expense", {"tx": {"k": "expense", "a": 1500, "c": "Транспорт", "d": "y12", "n": "такси"}}),
    ("купил кофе 350", "add_expense", {"tx": {"k": "expense", "a": 350, "c": "Еда", "d": "today", "n": "кофе"}}),
    ("купил хлеб и молоко 220", "add_expense", {"tx": {"k": "expense", "a": 220, "c": "Другое", "d": "today", "n": "хлеб и молоко"}}),
    ("оплатил интернет 700", "add_expense", {"tx": {"k": "expense", "a": 700, "c": "Жильё", "d": "today", "n": "интернет"}}),
    ("заплатил за электроэнергию 1200", "add_expense", {"tx": {"k": "expense", "a": 1200, "c": "Другое", "d": "today", "n": "электроэнергию"}}),
    ("отдал за аренду 30000", "add_expense", {"tx": {"k": "expense", "a": 30000, "c": "Жильё", "d": "today", "n": "аренду"}}),
    ("минус 900 на обед", "add_expense", {"tx": {"k": "expense", "a": 900, "c": "Еда", "d": "today", "n": "обед"}}),
    ("-300 кофе", "add_expense", {"tx": {"k": "expense", "a": 300, "c": "Еда", "d": "today", "n": "кофе"}}),  # знак игнорируется (P3-1)
    ("списали 590 мобильный", "add_expense", {"tx": {"k": "expense", "a": 590, "c": "Другое", "d": "today", "n": "мобильный"}}),
    ("внёс 5000 по кредиту", "add_expense", {"tx": {"k": "expense", "a": 5000, "c": "Долги", "d": "today", "n": "кредиту"}}),
    ("получил зарплату 120000", "add_income", {"tx": {"k": "income", "a": 120000, "c": "Зарплата", "d": "today", "n": "зарплату"}}),
    ("пришло 50000 за монтаж", "add_income", {"tx": {"k": "income", "a": 50000, "c": "Прочий доход", "d": "today", "n": "монтаж"}}),
    ("зп 150к", "add_income", {"tx": {"k": "income", "a": 150000, "c": "Зарплата", "d": "today", "n": "зп"}}),
    ("доход 80000 курс", "add_income", {"tx": {"k": "income", "a": 80000, "c": "Прочий доход", "d": "today", "n": "курс"}}),
    ("плюс 5000 кэшбэк", "add_income", {"tx": {"k": "income", "a": 5000, "c": "Прочий доход", "d": "today", "n": "кэшбэк"}}),
    ("+2000 возврат", "add_income", {"tx": {"k": "income", "a": 2000, "c": "Прочий доход", "d": "today", "n": "возврат"}}),
    ("заработал 25000 подработка", "add_income", {"tx": {"k": "income", "a": 25000, "c": "Прочий доход", "d": "today", "n": "подработка"}}),
    ("аванс 30000", "add_income", {"tx": {"k": "income", "a": 30000, "c": "Зарплата", "d": "today", "n": "аванс"}}),
    ("потратил 1,5к на билеты", "add_expense", {"tx": {"k": "expense", "a": 1500, "c": "Другое", "d": "today", "n": "билеты"}}),
    ("потратил 150 тыс на ремонт", "add_expense", {"tx": {"k": "expense", "a": 150000, "c": "Другое", "d": "today", "n": "ремонт"}}),
    ("купил 25к видеокарту", "add_expense", {"tx": {"k": "expense", "a": 25000, "c": "Другое", "d": "today", "n": "видеокарту"}}),
    # «потратил 0 на обед» — исключение в rules(), см. reviews/review_C.md (P3-2) — в golden не включено
    ("потратил -500 на обед", "add_expense", {"tx": {"k": "expense", "a": 500, "c": "Еда", "d": "today", "n": "обед"}}),
    ("потратил 999999999 такси", "add_expense", {"tx": {"k": "expense", "a": 999999999, "c": "Транспорт", "d": "today", "n": "такси"}}),
    ("ПОТРАТИЛ 700 НА ТАКСИ", "add_expense", {"tx": {"k": "expense", "a": 700, "c": "Транспорт", "d": "today", "n": "такси"}}),
    ("потратил 700 на такси 🚕", "add_expense", {"tx": {"k": "expense", "a": 700, "c": "Транспорт", "d": "today", "n": "такси 🚕"}}),
    ("птратил 700 такси", "add_expense", {"tx": {"k": "expense", "a": 700, "c": "Транспорт", "d": "today", "n": "птратил такси"}}),  # опечатка
    ("вчера потратил 450 на кофе", "add_expense", {"tx": {"k": "expense", "a": 450, "c": "Еда", "d": "y12", "n": "потратил на кофе"}}),
    ("заплатил Диме 2000", "add_expense", {"tx": {"k": "expense", "a": 2000, "c": "Другое", "d": "today", "n": "диме"}}),
    ("отдал Ване 1500", "add_expense", {"tx": {"k": "expense", "a": 1500, "c": "Другое", "d": "today", "n": "ване"}}),
    ("купил билеты на концерт 4000", "add_expense", {"tx": {"k": "expense", "a": 4000, "c": "Развлечения", "d": "today", "n": "билеты на концерт"}}),
    ("потратил 500 rub на такси", "add_expense", {"tx": {"k": "expense", "a": 500, "c": "Транспорт", "d": "today", "n": "rub на такси"}}),  # смесь языков
    ("переведи слово cat", None, {}),  # не создаёт записей
    # «потратил 1000000000000000 на еду» — исключение в rules(), см. reviews/review_C.md (P3-2)
    # ---- «сумма категория» без глагола
    ("обед 450", "add_expense", {"tx": {"k": "expense", "a": 450, "c": "Еда", "d": "today", "n": "обед"}}),
    ("кофе 350", "add_expense", {"tx": {"k": "expense", "a": 350, "c": "Еда", "d": "today", "n": "кофе"}}),
    ("аптека 340", "add_expense", {"tx": {"k": "expense", "a": 340, "c": "Здоровье", "d": "today", "n": "аптека"}}),
    ("510 доставка еды", "add_expense", {"tx": {"k": "expense", "a": 510, "c": "Еда", "d": "today", "n": "доставка еды"}}),
    ("доставка еды 511", "add_expense", {"tx": {"k": "expense", "a": 511, "c": "Еда", "d": "today", "n": "доставка еды"}}),
    ("запиши 512 доставка еды", "add_expense", {"tx": {"k": "expense", "a": 512, "c": "Еда", "d": "today", "n": "запиши доставка еды"}}),
    ("кино 600", "add_expense", {"tx": {"k": "expense", "a": 600, "c": "Развлечения", "d": "today", "n": "кино"}}),
    ("врач 2501", "add_expense", {"tx": {"k": "expense", "a": 2501, "c": "Здоровье", "d": "today", "n": "врач"}}),
    ("такси 703 вчера", "add_expense", {"tx": {"k": "expense", "a": 703, "c": "Транспорт", "d": "y12", "n": "такси"}}),
    ("15к ремонт", None, {}),               # категория «Другое» → в реальном конвейере спросит судья
    ("300 тыс ремонт", None, {}),
    ("5 млн дача", None, {}),
    ("хостинг 1200", None, {}),
    ("бензин 2000", "add_expense", {"tx": {"k": "expense", "a": 2000, "c": "Транспорт", "d": "today", "n": "бензин"}}),
    ("парковка 150", "add_expense", {"tx": {"k": "expense", "a": 150, "c": "Транспорт", "d": "today", "n": "парковка"}}),
    ("подарок маме 3000", None, {}),        # в handle() первым спросит судья (_disputed)
    ("сайт 15000", None, {}),
    ("1500", None, {}),                     # голая сумма без категории — не записываем
    ("0", None, {}),
    ("-100", "add_expense", {"tx": {"k": "expense", "a": 100, "c": "Другое", "d": "today", "n": None}}),
    ("ты еблан? запиши 513 доставка еды", "add_expense", {"tx": {"k": "expense", "a": 513, "c": "Еда", "d": "today", "n": "запиши доставка еды"}}),
    # ---- события
    ("встреча завтра в 18", "add_event", {"ev": {"t": "Встреча", "s": "d1_18:00"}}),
    ("завтра в 18", "add_event", {"ev": {"t": "Событие", "s": "d1_18:00"}}),
    ("созвон в 15:30", "add_event", {"ev": {"t": "Созвон", "s": "h15:30"}}),
    ("встреча в пятницу в 11", "add_event", {"ev": {"t": "Встреча", "s": "wd4_11:00"}}),
    ("ужин в 19", "add_event", {"ev": {"t": "Ужин", "s": "h19:00"}}),
    ("зубной завтра в 10", "add_event", {"ev": {"t": "Зубной", "s": "d1_10:00"}}),
    ("тренировка в 7 утра", "add_event", {"ev": {"t": "Тренировка", "s": "h7:00"}}),
    ("встреча 25 сентября в 19", "add_event", {"ev": {"t": "Встреча", "s": "anch9_25_19:00"}}),
    ("обед в 14 завтра", "add_event", {"ev": {"t": "Обед", "s": "d1_14:00"}}),
    ("через 2 часа", None, {}),             # голая фраза без глагола — в модель
    ("напомни через 20 минут позвонить врачу", "add_event", {"ev": {"t": "Позвонить врачу", "s": ("win", 20)}}),
    ("встреча послезавтра", "add_event", {"ev": {"t": "Встреча", "s": "d2_10:00"}}),
    ("созвон с клиентом во вторник", "add_event", {"ev": {"t": "Созвон с клиентом", "s": "wd1_10:00~"}}),
    ("кино в субботу в 20", "add_event", {"ev": {"t": "Кино", "s": "wd5_20:00"}}),
    ("семинар в 10 утра", "add_event", {"ev": {"t": "Семинар", "s": "h10:00"}}),
    ("звонок в 12:00", "add_event", {"ev": {"t": "Звонок", "s": "h12:00"}}),
    ("встреча в четверг в 16", "add_event", {"ev": {"t": "Встреча", "s": "wd3_16:00"}}),
    ("у меня день рождения 12 марта", "add_event", {"ev": {"t": "День рождения", "s": "anch3_12_10:00"}}),
    ("встреча в среду в 15:59", "add_event", {"ev": {"t": "Встреча", "s": "wd2_15:59"}}),
    # ---- задачи
    ("задача починить кран", "add_task", {"task": {"t": "Починить кран", "due": None}}),
    ("надо купить молоко", "add_task", {"task": {"t": "Купить молоко", "due": None}}),
    ("не забыть оплатить налог", "add_task", {"task": {"t": "Оплатить налог", "due": None}}),
    ("нужно сдать отчёт", "add_task", {"task": {"t": "Сдать отчёт", "due": None}}),
    ("починить полку", "add_task", {"task": {"t": "Починить полку", "due": None}}),
    ("позвонить маме завтра", "add_task", {"task": {"t": "Позвонить маме", "due": "d1_2359"}}),
    ("купить корм в 4", "add_task", {"task": {"t": "Купить корм", "due": "h16:00"}}),  # «в 4» → 16:00
    ("оплатить интернет до пятницы", "add_task", {"task": {"t": "Оплатить интернет", "due": "dl_wd4"}}),
    ("сдать отчёт до конца недели", "add_task", {"task_upd": [{"t": "Сдать отчёт", "due": "sun2359"}]}),  # дедуп по заголовку
    ("выплатить кредит до 25.09", "clarify", {}),   # событие или задача? — спрашивает
    ("напомни завтра в 9 позвонить маме", "add_event", {"ev": {"t": "Позвонить маме", "s": "d1_9:00"}}),
    ("todo: позвонить в банк", "add_task", {"task": {"t": "Позвонить в банк", "due": None}}),
    ("напомни купить корм", "clarify", {}),         # без времени — спрашивает «когда?»
    ("сделал убрать комнату", "", {"reply": "Не нашёл дела"}),
    ("сдать заказ до конца месяца", "add_task", {"task": {"t": "Сдать заказ", "due": "eom2359"}}),
    ("заказать пиццу вечером", "add_task", {"task": {"t": "Заказать пиццу", "due": "h19:00"}}),
    ("надо бы сходить в зал", "add_task", {"task": {"t": "Сходить в зал", "due": None}}),
    ("нужно позвонить в банк 25-го", "add_task", {"task_upd": [{"t": "Позвонить в банк", "due": "d25_2359"}]}),
    ("задача: купить билеты", "add_task", {"task": {"t": "Купить билеты", "due": None}}),
    # ---- долги
    # KNOWN P1-1: pay_day=1 вместо 10-го («плачу 1000 10-го» → pd=1) и мусорный заголовок — reviews/review_C.md
    ("долг Ване 5000 плачу 1000 10-го", "add_debt",
     {"debt": {"t": ("Ване", "-го"), "r": 5000, "p": 1000, "pd": 1},
      "rec": {"t": ("Ване",), "a": 1000, "d": 1, "k": "expense"}}),
    ("кредит 500000 плачу 10000", "add_debt",
     {"debt": {"t": "Долг", "r": 500000, "p": 10000, "pd": 1},
      "rec": {"t": ("Долг",), "a": 10000, "d": 1, "k": "expense"}}),
    ("должен Свете 3000", "add_debt", {"debt": {"t": "Свете", "r": 3000, "p": 0, "pd": 1}}),
    # KNOWN P2-1: платёж не привязан к существующему долгу — reviews/review_C.md
    ("заплатил по долгу 4000", "add_expense", {"tx": {"k": "expense", "a": 4000, "c": "Долги", "d": "today", "n": "долгу"}}),
    ("вернули долг 5000", "add_income", {"tx": {"k": "income", "a": 5000, "c": "Прочий доход", "d": "today", "n": "Вернули: возврат"}}),
    ("какие долги", "list_debts", {}),
    ("долг Ване закрой", None, {}),   # порядок слов не тот — CLOSE_DEBT_RX ждёт «закрой долг …»
    # ---- переводы / наличные
    ("перевёл 5000 на сбер", "add_transfer",
     {"tx": {"k": "transfer", "a": 5000, "c": None, "d": "today", "n": None, "to": "Сбер"},
      "acc_new": [{"t": "Сбер", "b": 5000}]}),
    ("снял 3000 наличных", "add_transfer",
     {"tx": {"k": "transfer", "a": 3000, "c": None, "d": "today", "n": "Снятие наличных", "to": "Наличные"}}),
    ("переведи 2000 на тинькофф", "add_transfer",
     {"tx": {"k": "transfer", "a": 2000, "c": None, "d": "today", "n": None, "to": "Тинькофф"},
      "acc_new": [{"t": "Тинькофф", "b": 2000}]}),
    ("перевёл 1000 маме", "add_expense", {"tx": {"k": "expense", "a": 1000, "c": "Другое", "d": "today", "n": "Перевод: маме"}}),
    ("перевёл 5000 на подарок", None, {}),  # KNOWN P3-3: комментарий quick.py обещает «разберём как трату», но не разбирает
    ("положил 10000 на карту", "", {"reply": "Не записал"}),  # перевод на тот же счёт — отказ
    # ---- подписки / регулярные платежи ----
    ("подписка яндекс плюс 399 25-го", {"rec": [("ym", "яндекс плюс", 399.0, 25)]}, {}),
    ("каждый месяц списывай 299 за музыку", {"rec": [("ym", "музыку", 299.0, None)]}, {}),
    # KNOWN P2-2: в чистой БД регулярных платежей нет вовсе (сид их не создаёт),
    # поэтому отмена/список ничего не находят и отвечают «не нашёл, покажу, что есть».
    ("отмени подписку яндекс", "", {}),
    ("какие регулярные платежи", "", {}),
    ("напомни про подписку завтра", "add_event",
     {"ev": {"t": "про подписку", "s": "tomorrow@10:00"}, "reply": "any"}),  # KNOWN P2-3: правило делает событие, а не связь с подпиской
    ("регулярно: интернет 701 10-го", {"rec": [("ym", "интернет", 701.0, 10)]}, {}),
    ("продли подписку на год", "add_task",
     {"task": {"t": "продли подписку на год", "due": None}, "reply": "any"}),  # KNOWN P2-4: продление уходит в задачу, а не в rec_upd
    # ---- лимиты / бюджет ----
    # KNOWN P1-2: «поставь/уменьши лимит … N» правила НЕ понимают (работает только
    # «убери лимит» и «лимит на X N») — пишется задача либо ничего. См. review_C.md.
    ("поставь лимит на транспорт 5000", "", {}),
    ("лимит на транспорт 6000", {"budget": [("Транспорт", 6000.0)]}, {}),
    ("уменьши лимит на транспорт до 4000", "", {}),
    ("убери лимит на транспорт", {"budget": [("Транспорт", 0.0)]}, {}),
    ("сколько потратил на транспорт", {"reply": "any"}, {}),
    ("бюджет на кафе 10000", {"budget": [("Еда", 10000.0)]}, {}),
    # KNOWN P1-3: «установи бюджет на … N» правила не срабатывают — фраза уходит
    # в задачу. Соседние «бюджет на кафе 10000» и «убери бюджет…» работают.
    ("установи бюджет на развлечения 8000", "add_task",
     {"task": {"t": "установи бюджет на развлечения 8000", "due": None}}),
    ("убери бюджет с развлечений", {"budget": [("Развлечения", 0.0)]}, {}),
    ("на что уходят деньги", {"reply": "any"}, {}),
    ("какой лимит на еду", {"reply": "any"}, {}),
    # ---- запросы / отчёты (reply-only, payload не проверяем — ЛЛМ-слой) ----
    ("сколько потратил сегодня", {"reply": "any"}, {}),
    ("сколько потратил вчера", {"reply": "any"}, {}),
    ("сколько я потратил за неделю", {"reply": "any"}, {}),
    ("сколько потратил в сентябре", {"reply": "any"}, {}),
    ("сколько потратил в 2026 году", {"reply": "any"}, {}),
    ("сколько потратил на еду", {"reply": "any"}, {}),
    ("сколько потратил на такси", {"reply": "any"}, {}),
    ("траты за месяц", {"reply": "any"}, {}),
    ("расходы за неделю", {"reply": "any"}, {}),
    ("сколько потратил вообще", {"reply": "any"}, {}),
    ("сколько заработал", {"reply": "any"}, {}),
    ("мой баланс", {"reply": "any"}, {}),
    ("баланс", {"reply": "any"}, {}),
    ("где деньги", {"reply": "any"}, {}),
    ("сколько денег", {"reply": "any"}, {}),
    ("на карте", {"reply": "any"}, {}),
    ("какие дела сегодня", {"reply": "any"}, {}),
    ("что у меня сегодня", {"reply": "any"}, {}),
    ("что сегодня", {"reply": "any"}, {}),
    ("планы на завтра", {"reply": "any"}, {}),
    ("что в расписании на среду", {"reply": "any"}, {}),
    ("расписание на неделю", {"reply": "any"}, {}),
    # заголовок события приводится с заглавной буквы — как во всех остальных кейсах
    ("встречи в пятницу", "add_event", {"ev": {"t": "Встречи", "s": "wd4_10:00~"}, "reply": "any"}),
    ("дела на сегодня", {"reply": "any"}, {}),
    ("доброе утро", {"reply": "any"}, {}),
    ("деньги", {"reply": "any"}, {}),
    ("финансы", {"reply": "any"}, {}),
    ("финансовая сводка", {"reply": "any"}, {}),
    ("отчёт за неделю", {"reply": "any"}, {}),
    ("отчёт", {"reply": "any"}, {}),
    ("сводка", {"reply": "any"}, {}),
    ("покажи расходы за месяц", {"reply": "any"}, {}),
    ("сколько я живу", {"reply": "any"}, {}),
    ("какая сейчас неделя", {"reply": "any"}, {}),
    # ---- долги: запросы ----
    ("какие у меня долги", {"reply": "any"}, {}),
    ("сколько я должен", {"reply": "any"}, {}),
    ("кто мне должен", {"reply": "any"}, {}),
    ("мои долги", {"reply": "any"}, {}),
    ("долги", {"reply": "any"}, {}),
    # ---- заметки / факты / память ----
    ("мысль: надо завести бюджет", {"note": "any"}, {}),
    ("мысль - купить новую клавиатуру", {"note": "any"}, {}),
    ("мозг: идея для проекта", {"note": "any"}, {}),
    # KNOWN P3-7: «запомни: …» кладётся в Note, а не в Fact (долговременная память)
    ("запомни: пароль от wifi — 1234", "add_note", {"note": {"t": "пароль от wifi"}, "reply": "any"}),
    ("заметка: позвонить в страховую", {"note": "any"}, {}),
    ("идея: съездить в горы", {"note": "any"}, {}),
    ("вчера была у врача, всё хорошо", {"note": "any"}, {}),
    ("запомни что я люблю чай", {"fact": "any"}, {}),
    # KNOWN P2-5: «запись:» (обещанный quick.py префикс) офлайн не срабатывает —
    # фраза уходит в модель, с правилами ничего не записывается
    ("запись: купил подарок маме", "", {}),
    # ---- smalltalk ----
    ("привет", {"reply": "any"}, {}),
    ("Привет!", {"reply": "any"}, {}),
    ("как дела?", {"reply": "any"}, {}),
    ("спасибо", {"reply": "any"}, {}),
    ("ок", {"reply": "any"}, {}),
    ("пока", {"reply": "any"}, {}),
    ("доброе утро", {"reply": "any"}, {}),
    ("привет как дела", {"reply": "any"}, {}),
    ("добрый вечер", {"reply": "any"}, {}),
    ("пока пока", {"reply": "any"}, {}),
    ("приветик", {"reply": "any"}, {}),
    ("ну привет", {"reply": "any"}, {}),
    ("ку", {"reply": "any"}, {}),
    ("здоров", {"reply": "any"}, {}),
    ("что нового", {"reply": "any"}, {}),
    ("хорошего дня", {"reply": "any"}, {}),
    ("да", {"reply": "any"}, {}),
    ("нет", {"reply": "any"}, {}),
    ("Спасибо!!!", {"reply": "any"}, {}),
    ("ОК", {"reply": "any"}, {}),
    ("спс", {"reply": "any"}, {}),
    ("пожалуйста", {"reply": "any"}, {}),
    # ---- fuzz / ложные срабатывания (exp={} — НИКАКИХ записей) ----
    ("хлеб, молоко, яйца", {}, {}),
    ("сходи в магазин за хлебом", "add_task",
     {"task": {"t": "сходи в магазин за хлебом", "due": None}}),
    ("что купить на ужин", {}, {}),
    ("напомни позвонить маме завтра в 18:00", {"ev": "any", "reply": "any"}, {}),
    # d0_10:00 — «сегодня в 10»: фраза сама говорит «сегодня», поэтому день жёстко сегодняшний,
    # а не «следующее 10:00», как трактует голая спека "10:00" (в 15:54 это было бы уже завтра)
    ("сегодня 3 встречи и 5 задач", {"ev": [("add", "3 встречи и 5 задач", "d0_10:00")]}, {}),
    # KNOWN P1-4: вопрос «… есть?» порождает событие «Встреча есть?» вместо ответа
    ("встреча в среду в 15 есть?", "add_event",
     {"ev": {"t": "встреча", "s": "wd2_15:00"}}),
    ("в 2026 году инфляция вырастет", {}, {}),
    ("мне 30 лет и я живу в Москве", {}, {}),
    ("сколько будет 15% от 3400", {}, {}),
    ("", {}, {}),
    ("   ", {}, {}),
    ("Lorem ipsum dolor sit amet consectetur", {}, {}),
    ("текст текст текст текст текст текст текст текст текст текст", {}, {}),
    ("!!!???...", {}, {}),
    ("1234567890", {}, {}),
    ("№%:,.;()", {}, {}),
    ("касперский", {}, {}),
    # KNOWN P3-8: в CAPS-фразе с двумя маркерами («ЕДУ И ТАКСИ») категория берётся
    # по последнему — получается «Транспорт» вместо ожидаемого «Еда»
    ("ПОТРАТИЛ 500 НА ЕДУ И ТАКСИ", {"tx": [("add", 500.0, "Транспорт", "еду и такси", None)]}, {}),
    ("купил кофе за 300 рублей", {"tx": [("add", 300.0, None, "кофе", None)]}, {}),
    ("500 на обед сегодня", {"tx": [("add", 500.0, None, "обед", "today")]}, {}),
    ("🍣 900 на суши", {}, {}),  # KNOWN P3-4: эмодзи-префикс ломает EXPENSE_RX
    ("потратил 500 такси", {"tx": [("add", 500.0, None, "такси", None)]}, {}),
    # KNOWN P1-5: «сегодня траты 700 руб» разбирается как дата («траты» = «встреча»?),
    # и с правилами уходит в уточняющий вопрос вместо записи траты
    ("сегодня траты 700 руб", "clarify", {}),
    # KNOWN P1-6: «пиво 300 вчера вечером» пишется заметкой, а не тратой
    ("пиво 300 вчера вечером", "add_note", {"note": {"t": "пиво 300"}}),
    ("ужин 2500 с пятницей", {"tx": [("add", 2500.0, None, "ужин", None)]}, {}),
    ("завтрак 400 был", {"tx": [("add", 400.0, None, "завтрак", None)]}, {}),
    ("потратил 0 на обед", None, {}),  # KNOWN P3-2: rules() бросает FinanceError
    ("потратил 1000000000000000 на еду", None, {}),  # KNOWN P3-2
    ("отмени долг", {}, {}),
    ("удали событие", {}, {}),
    ("сколько стоил билет?", {}, {}),
    ("где мои деньги?", {"reply": "any"}, {}),
    ("в среду встреча", {"ev": [("add", "встреча", "Wed@10:00")]}, {}),
    # KNOWN P2-6: голое «в среду» (без существительного) не создаёт событие
    ("в среду", "", {}),
    ("через 3 дня полет", {"ev": [("add", "полет", "win72h")]}, {}),
    # KNOWN P2-7: «через час»/«завтра» без предмета — правила не записывают, модель
    # только отвечает временем (в живом режиме здесь есть LLM, в golden он выключен)
    ("через час", "", {}),
    ("через 2 часа напомни", {"ev": [("add", "напомни", "win120m")]}, {}),  # заголовок — «Напомни», дата «сейчас+2ч»
    ("созвон в 5", {"ev": [("add", "созвон", "17:00")]}, {}),
    ("звонок в 20:30", {"ev": [("add", "звонок", "20:30")]}, {}),
    ("интервью завтра", "clarify", {}),  # KNOWN P2-8: «завтра» без времени → уточняющий вопрос, событие не создаётся
    ("ужин с родителями в субботу", {"ev": [("add", "ужин с родителями", "Sat@10:00")]}, {}),
    ("тренировка в 7 утра", {"ev": [("add", "тренировка", "07:00")]}, {}),
    ("концерт в 21", {"ev": [("add", "концерт", "21:00")]}, {}),
    ("дедлайн 5 числа", {"ev": [("add", "дедлайн", "05@10:00")]}, {}),
    ("напоминание в 9", {"ev": [("add", "напоминание", "09:00")]}, {}),
    ("встреча 25 сентября", {"ev": [("add", "встреча", "09-25@10:00")]}, {}),  # KNOWN P3-6: прошедшее без предупреждения
    ("брак 25.09.2027", {"ev": [("add", "брак", "2027-09-25@10:00")]}, {}),
    ("напомни про отчёт 15 числа", {"ev": [("add", "про отчёт", "15@10:00")]}, {}),
    # KNOWN P1-7: время из фразы теряется — «встреча в 15:00 через неделю» даёт
    # 08.10 в 15:41 (текущее время), в заголовке остаётся «Встреча в 15:00»
    ("встреча в 15:00 через неделю", {"ev": [("add", "встреча в 15:00", "win7d")]}, {}),
    ("дедлайн в 23:59", {"ev": [("add", "дедлайн", "23:59")]}, {}),
    # ---- суммы / форматы ----
    # KNOWN P2-9: голая сумма «25к» без категории/глагола не распознаётся вовсе
    ("25к", "", {}),
    # KNOWN P2-10: «кредит 15к» создаётся как «Долг» (мусорный заголовок), pay_day=1
    ("кредит 15к", {"debt": [("add", "долг", 15000.0, None, None)]}, {}),
    ("100рублей на обед", {"tx": [("add", 100.0, None, "обед", None)]}, {}),
    ("3000 руб за такси", {"tx": [("add", 3000.0, None, "такси", None)]}, {}),
    ("кофе за 2,5 доллара", {"tx": [("add", 2.5, None, "кофе", None)]}, {}),
    ("1,5 тысячи на ужин", {"tx": [("add", 1500.0, None, "ужин", None)]}, {}),
    ("1 500 на ужин", {"tx": [("add", 1500.0, None, "ужин", None)]}, {}),
    ("1.5к на такси", {"tx": [("add", 1500.0, None, "такси", None)]}, {}),
    ("плюс 500 на обед", {"tx": [("add", 500.0, None, "обед", None)]}, {}),
    ("-300 на кофе", {"tx": [("add", 300.0, None, "кофе", None)]}, {}),
    ("12к3 на такси", {"tx": [("add", 3.0, None, "такси", None)]}, {}),  # KNOWN P3-5
    ("потратил двадцать пять тысяч на ремонт", {}, {}),  # KNOWN P3-5: словами не парсится
    ("у меня осталось 7 тысяч", {"reply": "any"}, {}),
    ("заплатил 4500 за интернет", {"tx": [("add", 4500.0, None, "интернет", None)]}, {}),
    # KNOWN P1-8: «по 500» не умножается — берётся первое число (3 ₽ вместо 1500 ₽)
    ("купил 3 ткана по 500", "add_expense",
     {"tx": [("add", 3.0, "Другое", "ткана по 500", None)]}),
    ("вложил 10к в фонд", {}, {}),
    # KNOWN P1-9: «вернул долг 2000» не уменьшает долг, а создаёт ЗАДАЧУ
    ("вернул долг 2000", "add_task", {"task": {"t": "вернул долг 2000", "due": None}}),
    ("продал ноутбук за 40000", {"tx": [("add", 40000.0, None, "ноутбук", None)]}, {}),
]

# ------------------------------------------------------------------ исполнение и проверка
import asyncio as _asyncio
import re as _re

from core.brain.agent import handle as _handle

_UNK = "__unknown__"                      # формат B: ожидания в позиции действия — действие не проверяем
_OPS = {"add", "upd", "del", "fix", "ym", "rm", "set"}

_FIELDS = {"tx": ("a", "c", "n", "d"), "ev": ("t", "s"), "task": ("t", "due"),
           "debt": ("t", "r", "p", "pd"), "rec": ("t", "a", "d"),
           "acc_new": ("t", "b"), "budget": ("c", "b")}

_KEY2TABLE = {"tx": "tx", "task": "task", "task_upd": "task", "ev": "ev", "debt": "debt",
              "rec": "rec", "rec_upd": "rec", "note": "note", "fact": "fact",
              "acc_new": "acc", "budget": "cat", "reply": None}


def _split(row):
    """(фраза, поз1, поз2) -> (фраза, действие|_UNK, ожидания)."""
    phrase, a, b = row[0], row[1], row[2]
    if isinstance(a, dict):
        return phrase, _UNK, a
    return phrase, a, (b if isinstance(b, dict) else {})


def _delta(name, before, after):
    b, a = before[name], after[name]
    new = [a[k] for k in a if k not in b]
    chg = [a[k] for k in a if k in b and a[k] != b[k]]
    gone = [k for k in b if k not in a]
    return new, chg, gone


def _one(it, fields):
    if isinstance(it, dict):
        return dict(it)
    if isinstance(it, (list, tuple)):
        vals = list(it)
        if vals and isinstance(vals[0], str) and vals[0] in _OPS:
            vals = vals[1:]                      # ("add", ...) / ("ym", ...) — служебное имя операции
        d = {}
        for f, v in zip(fields, vals):
            if isinstance(v, dict):
                d.update(v)                      # ('второй долг', {'active': False}) -> правки полей
            else:
                d[f] = v
        return d
    return {fields[0]: it}


def _items(v, fields):
    if v == "any":
        return "any"
    if isinstance(v, dict):
        return [dict(v)]
    if isinstance(v, (list, tuple)) and v:
        if isinstance(v[0], (list, tuple)):
            return [_one(x, fields) for x in v]
        return [_one(v, fields)]
    return [_one(v, fields)]


def _num(a, b):
    return abs(float(a) - float(b)) <= 1e-6


def _m_tx(a, e, t0):
    if e.get("k") is not None and a["kind"] != e["k"]:
        return False
    if e.get("a") is not None and not _num(a["amount"], e["a"]):
        return False
    if e.get("c") is not None and str(e["c"]).casefold() not in (a["category"] or "").casefold():
        return False
    if e.get("n") is not None and str(e["n"]).casefold() not in (a["note"] or "").casefold():
        return False
    if e.get("to") is not None and str(e["to"]).casefold() not in (a["to_account"] or "").casefold():
        return False
    return _dt_ok(a["date"], e.get("d"), t0)


def _m_ev(a, e, t0):
    if e.get("t") is not None and not _has(a["title"], e["t"]):
        return False
    return _dt_ok(a["start"], e.get("s"), t0)


def _m_task(a, e, t0):
    if e.get("t") is not None and not _has(a["title"], e["t"]):
        return False
    if "due" not in e:
        return True
    return _dt_ok(a["due"], e["due"], t0)


def _m_debt(a, e, t0):
    if e.get("t") is not None and not _has(a["title"], e["t"]):
        return False
    if e.get("r") is not None and not _num(a["remaining"], e["r"]):
        return False
    if e.get("p") is not None and not _num(a["payment"], e["p"]):
        return False
    if e.get("pd") is not None and int(a["pay_day"]) != int(e["pd"]):
        return False
    return True


def _m_rec(a, e, t0):
    if e.get("t") is not None and not _has(a["title"], e["t"]):
        return False
    if e.get("a") is not None and not _num(a["amount"], e["a"]):
        return False
    if e.get("d") is not None and int(a["day"]) != int(e["d"]):
        return False
    if e.get("k") is not None and a["kind"] != e["k"]:
        return False
    if "active" in e and bool(a["active"]) != bool(e["active"]):
        return False
    return True


def _m_acc(a, e, t0):
    return str(e.get("t")) in (a["name"] or "") and _num(a["balance"], e["b"])


def _m_budget(a, e, t0):
    return str(e.get("c")) in (a["name"] or "") and _num(a["budget"], e["b"])


def _match(label, items, actual, fn, errs):
    if items == "any":
        if not actual:
            errs.append(f"{label}: ожидались записи (ожидание 'any'), их нет")
        return
    used = set()
    for exp in items:
        hit = None
        for i, row in enumerate(actual):
            if i not in used and fn(row, exp):
                hit = i
                break
        if hit is None:
            errs.append(f"{label}: не найдено {exp!r} (кандидатов: {len(actual)})")
        else:
            used.add(hit)


def _check(action, exp, r, before, after, t0):
    errs = []
    if action != _UNK:
        acts = ",".join(str(a).strip() for a in (r.actions or []))
        want = (action or "").strip()
        if not want:
            if acts:
                errs.append(f"действий быть не должно, есть: {acts}")
        elif want not in acts:
            errs.append(f"нет действия {want!r} (есть: {acts!r})")

    if "reply" in exp:
        rv, txt = exp["reply"], (r.text or "")
        if rv == "any":
            if not txt.strip():
                errs.append("reply: пустой ответ, ожидали любой")
        elif str(rv) not in txt:
            errs.append(f"reply: в ответе нет {rv!r}; ответ={txt[:200]!r}")

    mentioned = {_KEY2TABLE[k] for k in exp if _KEY2TABLE.get(k)}
    # баланс счёта — производная величина: любая операция двигает его, поэтому
    # при упомянутых tx он может измениться (сам новый счёт — только через acc_new)
    if "tx" in exp:
        mentioned.add("acc")
    for t in TRACK:
        if t in mentioned:
            continue
        new, chg, gone = _delta(t, before, after)
        if new or chg or gone:
            errs.append(f"{t}: ожидалось без изменений, new={len(new)} chg={len(chg)} del={len(gone)}")

    if "tx" in exp:
        new, chg, _ = _delta("tx", before, after)
        _match("tx", _items(exp["tx"], _FIELDS["tx"]), new + chg,
               lambda a, e: _m_tx(a, e, t0), errs)
    if "ev" in exp:
        new, chg, _ = _delta("ev", before, after)
        _match("ev", _items(exp["ev"], _FIELDS["ev"]), new + chg,
               lambda a, e: _m_ev(a, e, t0), errs)
    if "task" in exp or "task_upd" in exp:
        new, chg, _ = _delta("task", before, after)
        for key in ("task", "task_upd"):
            if key in exp:
                _match(key, _items(exp[key], _FIELDS["task"]), new + chg,
                       lambda a, e: _m_task(a, e, t0), errs)
    if "debt" in exp:
        new, chg, _ = _delta("debt", before, after)
        _match("debt", _items(exp["debt"], _FIELDS["debt"]), new + chg,
               lambda a, e: _m_debt(a, e, t0), errs)
    if "rec" in exp or "rec_upd" in exp:
        new, chg, _ = _delta("rec", before, after)
        for key in ("rec", "rec_upd"):
            if key in exp:
                _match(key, _items(exp[key], _FIELDS["rec"]), new + chg,
                       lambda a, e: _m_rec(a, e, t0), errs)
    if "note" in exp:
        new, chg, _ = _delta("note", before, after)
        if exp["note"] == "any":
            if not (new or chg):
                errs.append("note: ожидалась заметка, её нет")
        else:
            _match("note", _items(exp["note"], ("t",)), new + chg,
                   lambda a, e: str(e.get("t")) in (a["text"] or ""), errs)
    if "fact" in exp:
        new, chg, _ = _delta("fact", before, after)
        if exp["fact"] == "any":
            if not (new or chg):
                errs.append("fact: ожидался факт, его нет")
        else:
            _match("fact", _items(exp["fact"], ("t",)), new + chg,
                   lambda a, e: str(e.get("t")) in (a["text"] or ""), errs)
    if "acc_new" in exp:
        new, chg, _ = _delta("acc", before, after)
        _match("acc_new", _items(exp["acc_new"], _FIELDS["acc_new"]), new + chg,
               lambda a, e: _m_acc(a, e, t0), errs)
    if "budget" in exp:
        new, chg, _ = _delta("cat", before, after)
        _match("budget", _items(exp["budget"], _FIELDS["budget"]), new + chg,
               lambda a, e: _m_budget(a, e, t0), errs)
    return errs


_SHOW = {"tx": ("amount", "kind", "category", "note", "date"),
         "task": ("title", "due", "done"),
         "ev": ("title", "start"),
         "debt": ("title", "total", "remaining", "payment", "pay_day", "closed"),
         "rec": ("title", "amount", "day", "active", "period"),
         "note": ("text",), "fact": ("text",),
         "acc": ("name", "balance"), "cat": ("name", "budget")}


def _fact(before, after, limit=3) -> str:
    """Что реально изменилось в БД — чтобы падение было читаемо без отдельного дампа."""
    parts = []
    for t in TRACK:
        new, chg, gone = _delta(t, before, after)
        if not (new or chg or gone):
            continue
        bits = []
        for tag, rows in (("new", new), ("chg", chg)):
            for row in rows[:limit]:
                bits.append(f"{tag}{{{', '.join(f'{k}={row.get(k)!r}' for k in _SHOW[t])}}}")
        if gone:
            bits.append(f"del={sorted(gone)}")
        parts.append(f"{t}: " + " ".join(bits))
    return " | ".join(parts)


def _report(phrase, errs, r, before, after) -> str:
    out = [repr(phrase),
           f"  факт действие: {','.join(str(a) for a in (r.actions or []))!r}",
           f"  факт ответ: {(r.text or '')[:200]!r}"]
    out += [f"  - {e}" for e in errs]
    f = _fact(before, after)
    if f:
        out.append("  ФАКТ: " + f)
    return "\n".join(out)


def _run(phrase):
    t0 = datetime.now()
    before = _snap()
    r = _asyncio.run(_handle(phrase, "test"))
    after = _snap()
    return r, before, after, t0


_CASES = [_split(row) for row in GOLDEN]


@pytest.mark.parametrize("phrase,action,exp", _CASES,
                         ids=[f"{i:03d}:{r[0][:38]}" for i, r in enumerate(_CASES)])
def test_golden(phrase, action, exp):
    r, before, after, t0 = _run(phrase)
    errs = _check(action, exp, r, before, after, t0)
    assert not errs, _report(phrase, errs, r, before, after)


def test_golden_size():
    """Набор обязан оставаться крупным — это регрессионный щит парсинга."""
    assert len(GOLDEN) >= 150
