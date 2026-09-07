"""Массовая чистка: «сотри все финансы за последние 2 дня», «удали задачи за неделю», «очисти историю чата».

Ничего не пропадает безвозвратно: удалённые строки складываются в «корзину» (таблица настроек, ключ trash:N),
а «отмена» возвращает их на место вместе с балансами.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from sqlmodel import select

from ..db import ChatMessage, Debt, Event, Link, Note, Task, Transaction, get_setting, log_action, session, set_setting
from . import finance
from .finance import money

# что чистим → (таблица, поле даты, человеческое название в род. падеже мн. ч.)
KINDS = {
    "transaction": (Transaction, "date", "операций"),
    "task": (Task, "created_at", "задач"),
    "event": (Event, "start", "событий"),
    "note": (Note, "created_at", "заметок"),
    "link": (Link, "created_at", "ссылок"),
    "chat": (ChatMessage, "created_at", "сообщений чата"),
}

_WORD2KIND = [
    (r"финанс\w*|операци\w*|транзакци\w*|трат\w*|расход\w*|доход\w*|платеж\w*|платёж\w*|истори\w*\s+(?:финанс\w*|операци\w*|трат\w*)", "transaction"),
    (r"задач\w*|дел[аоы]?|туду|todo", "task"),
    (r"событи\w*|встреч\w*|календар\w*|напоминани\w*", "event"),
    (r"заметк\w*|мысл\w*|идеи|идею", "note"),
    (r"ссылк\w*|закладк\w*", "link"),
    (r"истори\w*\s+(?:чата|переписки|сообщений)|чат|переписк\w*|сообщени\w*", "chat"),
]

VERB_RX = r"(сотри|сотр[её]ть|стереть|стирай|удали|удалить|удаляй|очисти|очистить|почисти|почистить|убери|убрать|снеси|снести|грохни|вычисти|обнули|обнулить)"
BULK_RX = re.compile(
    r"^\s*" + VERB_RX + r"\s+(?:пожалуйста\s+)?(?:мне\s+)?(?:все|всю|всё|всех|полностью|все\s+мои|мои)?\s*"
    r"(финанс\w*|операци\w*|транзакци\w*|трат\w*|расход\w*|доход\w*|платеж\w*|платёж\w*|истори\w*\s+(?:финанс\w*|операци\w*|трат\w*|чата|переписки|сообщений)|"
    r"задач\w*|дел[аоы]?|туду|todo|событи\w*|встреч\w*|календар\w*|напоминани\w*|заметк\w*|мысл\w*|идеи|идею|ссылк\w*|закладк\w*|чат|переписк\w*|сообщени\w*)"
    r"\b(.*)$", re.I | re.S)

_NUM = {"один": 1, "одну": 1, "одного": 1, "два": 2, "две": 2, "двух": 2, "три": 3, "трёх": 3, "трех": 3, "четыре": 4, "пять": 5,
        "шесть": 6, "семь": 7, "восемь": 8, "девять": 9, "десять": 10, "пару": 2, "пара": 2, "несколько": 3, "полгода": 182}


def kind_of(word: str) -> str | None:
    w = word.strip().lower()
    for rx, k in _WORD2KIND:
        if re.fullmatch(rx, w):
            return k
    return None


def parse_period(tail: str, now: datetime | None = None) -> tuple[datetime | None, datetime | None, str]:
    """«за последние 2 дня» / «за сегодня» / «за вчера» / «за неделю» / «за сентябрь» / пусто → (с, по, подпись)."""
    now = now or datetime.now()
    t = " " + tail.lower().strip(" .!,«»\"") + " "
    day0 = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if re.search(r"\bза\s+сегодня\b|\bсегодняшн", t):
        return day0, None, "за сегодня"
    if re.search(r"\bза\s+вчера\b|\bвчерашн", t):
        return day0 - timedelta(days=1), day0, "за вчера"
    m = re.search(r"\bза\s+(?:последн\w*|прошл\w*|прошедш\w*|ближайш\w*)?\s*(\d+|[а-яё]+)?\s*(час\w*|дн\w*|ден\w*|сут\w*|недел\w*|месяц\w*|мес\b|год\w*|лет)\b", t)
    if m:
        raw = (m.group(1) or "").strip()
        n = _NUM.get(raw)
        if n is None:
            try:
                n = int(raw) if raw else 1
            except ValueError:
                n = 1
        u = m.group(2)
        if u.startswith("час"):
            since, label = now - timedelta(hours=n), f"за последние {n} ч"
        elif u.startswith(("дн", "ден", "сут")):
            # «за последние 2 дня» = сегодня и вчера (целые дни)
            since, label = day0 - timedelta(days=n - 1), f"за последние {n} дн"
        elif u.startswith("недел"):
            since, label = day0 - timedelta(days=7 * n - 1), f"за последние {n} нед"
        elif u.startswith("мес"):
            since, label = day0 - timedelta(days=30 * n - 1), f"за последние {n} мес"
        else:
            since, label = day0 - timedelta(days=365 * n - 1), f"за последние {n} г"
        return since, None, label
    if re.search(r"\bза\s+(?:эту\s+|текущую\s+)?неделю\b|\bна\s+этой\s+неделе\b", t):
        return day0 - timedelta(days=now.weekday()), None, "за эту неделю"
    if re.search(r"\bза\s+(?:этот\s+|текущий\s+)?месяц\b|\bв\s+этом\s+месяце\b", t):
        return day0.replace(day=1), None, "за этот месяц"
    return None, None, "за всё время"


def _query(kind: str, since: datetime | None, until: datetime | None):
    model, field, _ = KINDS[kind]
    col = getattr(model, field)
    q = select(model)
    if since is not None:
        q = q.where(col >= since)
    if until is not None:
        q = q.where(col < until)
    return q


def preview(kind: str, since: datetime | None, until: datetime | None) -> dict:
    """Сколько строк попадёт под нож и (для финансов) на какую сумму."""
    with session() as s:
        rows = list(s.exec(_query(kind, since, until)))
    total = None
    if kind == "transaction":
        total = sum(r.amount for r in rows if r.kind == "expense") + sum(r.amount for r in rows if r.kind == "income")
    return {"count": len(rows), "total": total, "label": KINDS[kind][2], "sample": [_title(r) for r in rows[:3]]}


def _title(r) -> str:
    if isinstance(r, Transaction):
        return f"{'−' if r.kind == 'expense' else '+'}{money(r.amount)} {r.note or r.category or ''}".strip()
    if isinstance(r, (Task, Event)):
        return r.title
    if isinstance(r, Note):
        return (r.title or r.text)[:40]
    if isinstance(r, Link):
        return r.title or r.url
    return (r.text or "")[:40]


def execute(kind: str, since: datetime | None, until: datetime | None, channel: str = "tg") -> dict:
    """Удаляет, откатывает балансы, кладёт всё в корзину и пишет в журнал действий (для «отмена»)."""
    model, _, label = KINDS[kind]
    with session() as s:
        rows = list(s.exec(_query(kind, since, until)))
        snapshot = [r.model_dump(mode="json") for r in rows]
        for r in rows:
            if kind == "transaction":
                finance._apply(s, r, -1)
                if r.debt_id:
                    d = s.get(Debt, r.debt_id)
                    if d:
                        d.remaining = min(d.total, d.remaining + r.amount)
                        d.closed = d.remaining <= 0
                        s.add(d)
            if kind == "event" and getattr(r, "google_id", None):
                from .calendar import _gcal_remove
                _gcal_remove(r.id, r.google_id)
            s.delete(r)
        s.commit()
        n = len(rows)
        trash_id = 0
        if n:
            trash_id = int(get_setting("trash:seq", "0") or 0) + 1
            set_setting("trash:seq", str(trash_id))
            set_setting(f"trash:{trash_id}", json.dumps({"kind": kind, "rows": snapshot}, ensure_ascii=False))
            log_action(s, "bulk_delete", "trash", trash_id, f"{n} {label}", channel)
            s.commit()
    return {"count": n, "trash_id": trash_id, "label": label}


def restore(trash_id: int) -> int:
    """Вернуть из корзины. Возвращает число восстановленных строк (0 — корзина пуста/уже возвращена)."""
    raw = get_setting(f"trash:{trash_id}")
    if not raw:
        return 0
    data = json.loads(raw)
    model = KINDS[data["kind"]][0]
    n = 0
    with session() as s:
        for row in data["rows"]:
            if s.get(model, row.get("id")) is not None:
                continue  # уже на месте
            obj = model.model_validate(row)
            s.add(obj)
            if data["kind"] == "transaction":
                finance._apply(s, obj, +1)
                if obj.debt_id:
                    d = s.get(Debt, obj.debt_id)
                    if d:
                        d.remaining = max(0.0, d.remaining - obj.amount)
                        d.closed = d.remaining <= 0
                        s.add(d)
            n += 1
        s.commit()
    set_setting(f"trash:{trash_id}", None)
    return n


def describe(kind: str, since: datetime | None, until: datetime | None, label: str) -> str:
    p = preview(kind, since, until)
    if not p["count"]:
        return f"Тут и стирать нечего, сэр: {p['label']} {label} — ноль."
    what = f"{p['count']} {p['label']}"
    if p["total"]:
        what += f" на {money(p['total'])}"
    sample = "; ".join(p["sample"])
    return (f"Удалить {what} {label}?" + (f" Например: {sample}." if sample else "") +
            " Ответьте «да» — и я сотру (балансы пересчитаю; «отмена» вернёт всё назад), или «нет».")
