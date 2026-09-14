"""Сортировщик: одно сообщение-список → много записей нужных типов.

«Задачи на день: доделать матрицу, купить очки, в 15:00 врач, мысль — попробовать рисовать» — раньше такое улетало в
модель с инструментами, и она клала всё одной заметкой. Здесь текст сначала проходит через нейронку в строгом JSON
(каждый пункт → тип, название, дата, сумма), потом каждый пункт записывается своим сервисом, а человек получает разбор
по группам. «Отмени» после этого откатывает всю пачку.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from sqlmodel import select

from ..db import ActionLog, get_setting, session, set_setting
from ..services import brain_notes, calendar, finance, tasks, undo
from ..services.calendar import fmt_dt
from ..services.finance import money
from . import llm
from .dates import parse_datetime
from .persona import now_line

log = logging.getLogger("assistant.sorter")

# явная «шапка» списка: «задачи на день: …», «на завтра: …», «разбери: …», «пожалуйста, запиши дела: …»
HEAD_RX = re.compile(r"^\s*(?:пожалуйста[,\s]+)?(?:запиши|добавь|разбери|разложи|рассортируй|сохрани)?\s*"
                     r"(?:мне\s+|пожалуйста\s+)?(?:задачи|дела|планы?|список|на\s+(?:сегодня|завтра|день|неделю|выходные)|сегодня|завтра)"
                     r"\b[^:\n]{0,30}[:\-—]\s*\S", re.I)
# явный префикс заметки — человек сам сказал «в мозг», не сортируем
NOTE_HEAD_RX = re.compile(r"^\s*(мозг|в\s+мозг|мысль|заметка|идея|запомни)(?![а-яё])", re.I)
INF_RX = re.compile(r"^\s*(?:(?:надо|нужно|не\s+забыть|обязательно|срочно|ещё|еще|потом|и)\s+)*[а-яё]{3,}(?:ть|ти|чь)(?:ся)?\b", re.I)   # пункт начинается с «сделать …»
ITEM_SPLIT_RX = re.compile(r"\n+|;\s*|\s+[•·\-–—]\s+|(?:^|\s)\d{1,2}[.)]\s+")
BATCH_TTL_H = 24
KIND_LABEL = {"task": "📋 Задачи", "event": "📅 В календарь", "note": "🧠 В память", "expense": "💸 Траты", "income": "💰 Доходы"}

PROMPT = """Ты разбираешь сообщение человека на отдельные записи для личного помощника. Ответь СТРОГО в JSON без пояснений:
{"items": [{"kind": "task|event|note|expense|income", "title": "...", "when": "YYYY-MM-DDTHH:MM или YYYY-MM-DD или null", "amount": число или null, "priority": 1|2|3}]}

Правила:
- task — дело, которое надо сделать (купить, позвонить, доделать, навести порядок, приготовить). Если в шапке «на сегодня/на день/на завтра» — у каждой задачи when = эта дата (только дата, без времени).
- event — есть конкретное время или это визит/приём/встреча/звонок с датой («в 15:00 врач», «завтра в 10 парикмахер»). when обязателен с временем.
- note — мысль, факт, идея, наблюдение, то, что нужно просто запомнить (не действие).
- expense / income — деньги с суммой («хлеб 120», «пришла пенсия 20000»). amount — число в рублях.
- Каждый пункт списка — ОДИН item. Не дроби один пункт на несколько и не объединяй разные. Ничего не выдумывай и не добавляй.
- title — коротко, с заглавной буквы, без точки в конце, слова человека сохраняй (только опечатки поправь). Шапку списка («задачи на день») в items не включай.
- priority: 1 — если человек подчеркнул срочность/важность, иначе 2.
- Даты считай от текущей даты в конце сообщения."""


def split_items(text: str) -> list[str]:
    parts = [p.strip(" .") for p in ITEM_SPLIT_RX.split(text) if p and p.strip(" .")]
    if len(parts) >= 3:
        return parts
    parts = [p.strip(" .") for p in re.split(r",\s*", text) if p.strip(" .")]
    if len(parts) >= 3:
        return parts
    # «доделать матрицу, написать песню и навести порядок» — последний пункт через «и» перед глаголом
    return [p.strip(" .") for p in re.split(r",\s*|\s+и\s+(?=[а-яё]+(?:ть|ти|чь)(?:ся)?\b)", text, flags=re.I) if p.strip(" .")]


def looks_like_batch(text: str) -> bool:
    """Похоже ли на список из нескольких дел/записей (а не одна команда, вопрос или рассказ)."""
    t = text.strip()
    if len(t) < 20 or NOTE_HEAD_RX.match(t) or "http" in t or t.rstrip().endswith("?"):
        return False
    from .agent import ANALYZE_RX, ACTION_VERB_RX, _QUESTION_RX
    if ANALYZE_RX.search(t) or _QUESTION_RX.match(t.lower()):
        return False
    items = split_items(t)
    if len(items) < 3:
        return False
    if HEAD_RX.match(t):
        return True
    verbs = sum(1 for i in items if ACTION_VERB_RX.search(i) or INF_RX.search(i))
    priced = sum(1 for i in items if re.search(r"\d{2,}", i))   # «хлеб 120, молоко 90, яйца 150» — несколько трат
    return verbs >= 2 or priced >= 3


async def _ask_llm(text: str) -> list[dict] | None:
    user = text.strip() + "\n" + now_line()
    msgs = [{"role": "system", "content": PROMPT}, {"role": "user", "content": user}]
    if await llm.ollama_available():
        out = await llm.ollama_chat(msgs, temperature=0.1, json_mode=True)
        raw = out.get("content") or ""
    elif llm.MODE == "cloud" and llm.cloud_enabled():
        raw = await llm.cloud_chat(PROMPT + "\nТолько JSON, без markdown.", user) or ""
    else:
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    items = data.get("items") if isinstance(data, dict) else data
    return items if isinstance(items, list) else None


def _when(v) -> datetime | None:
    if not v or not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.strip())
    except ValueError:
        return parse_datetime(v)[0]


def _amount(v) -> float | None:
    try:
        a = abs(float(str(v).replace(" ", "").replace(",", ".")))
    except (TypeError, ValueError):
        return None
    return a if a > 0 else None


async def sort(text: str, channel: str, confirm_amount: float = 100_000):
    """Разобрать сообщение-список и записать всё по местам. None — модель не справилась (пойдём обычным путём)."""
    from .agent import Reply
    try:
        items = await _ask_llm(text)
    except Exception as e:
        log.warning("sorter: модель не ответила: %s", e)
        return None
    if not items:
        return None
    via = "ollama" if await llm.ollama_available() else "gemini"
    with session() as s:
        last = s.exec(select(ActionLog.id).order_by(ActionLog.id.desc())).first() or 0
    done: dict[str, list[str]] = {}
    skipped: list[str] = []
    for it in items[:30]:
        if not isinstance(it, dict):
            continue
        title = str(it.get("title") or "").strip(" .")
        if not title:
            continue
        title = title[0].upper() + title[1:]
        kind = str(it.get("kind") or "task").lower()
        when = _when(it.get("when"))
        amount = _amount(it.get("amount"))
        try:
            if kind in ("expense", "income") and amount:
                if amount >= confirm_amount:
                    skipped.append(f"{title} {money(amount)} — крупная сумма, запишите отдельно, я переспрошу")
                    continue
                finance.add_transaction(amount, kind, note=title, source=channel)
                done.setdefault(kind, []).append(f"{title} — {money(amount)}")
            elif kind == "event" and when and (when.hour or when.minute):
                ev = calendar.add_event(title, when, remind_minutes=30, source=channel)
                done.setdefault("event", []).append(f"{ev.title} — {fmt_dt(ev.start)}")
            elif kind == "note":
                brain_notes.add_note(title, source=channel)
                done.setdefault("note", []).append(title)
            else:
                # задача; дата без времени → дедлайн конец дня, чтобы не сыпались напоминания «через час»
                due = when.replace(hour=23, minute=59) if when and not (when.hour or when.minute) else when
                pr = it.get("priority") if it.get("priority") in (1, 2, 3) else 2
                tk = tasks.add_task(title, due, pr, source=channel)
                if due and (due.hour, due.minute) == (23, 59):
                    # план на день: без отдельных «сегодня дедлайн»/«остался час» по каждому пункту — семь пингов подряд никому не нужны
                    with session() as s:
                        row = s.get(tasks.Task, tk.id)
                        if row and row.remind_stage < 2:
                            row.remind_stage = 2; s.add(row); s.commit()
                done.setdefault("task", []).append(tk.title + (f" — до {fmt_dt(due)}" if due and (due.hour, due.minute) != (23, 59) else ""))
        except finance.FinanceError as e:
            skipped.append(f"{title}: {e}")
    if not done:
        return None
    with session() as s:
        ids = [i for i in s.exec(select(ActionLog.id).where(ActionLog.id > last)).all()]
    set_setting(f"batch:{channel}", f"{datetime.now().isoformat()}|{','.join(map(str, ids))}")
    total = sum(len(v) for v in done.values())
    lines = [f"Разобрал, получилось {total} {_plural(total, 'запись', 'записи', 'записей')}:"]
    for kind in ("task", "event", "expense", "income", "note"):
        if kind in done:
            lines.append(f"\n{KIND_LABEL[kind]} ({len(done[kind])}):")
            lines += [f"• {x}" for x in done[kind]]
    if skipped:
        lines.append("\nНе записал:")
        lines += [f"• {x}" for x in skipped]
    lines.append("\nЕсли что-то не туда — «отмени» уберёт всю пачку, или «удали задачу …» одну.")
    actions = [f"add_{k}" for k in done]
    return Reply("\n".join(lines), actions, via)


def undo_batch(channel: str) -> str | None:
    """«Отмени» сразу после разбора списка — откатить все записи пачки. None — пачки нет или она уже не последняя."""
    raw = get_setting(f"batch:{channel}")
    if not raw or "|" not in raw:
        return None
    ts, ids = raw.split("|", 1)
    try:
        fresh = (datetime.now() - datetime.fromisoformat(ts)).total_seconds() < BATCH_TTL_H * 3600
    except ValueError:
        fresh = False
    id_list = [int(x) for x in ids.split(",") if x.strip().isdigit()]
    set_setting(f"batch:{channel}", None)
    if not fresh or not id_list:
        return None
    last = undo.last_action(channel)
    if not last or last.id != max(id_list):
        return None   # после пачки что-то ещё записали — откатываем по одному, как обычно
    n = undo.undo_ids(id_list)
    return f"Отменил всю пачку — {n} {_plural(n, 'запись', 'записи', 'записей')}. Как будто и не было." if n else None


def _plural(n: int, one: str, few: str, many: str) -> str:
    n = abs(n) % 100
    if 11 <= n <= 19:
        return many
    n %= 10
    return one if n == 1 else few if 2 <= n <= 4 else many
