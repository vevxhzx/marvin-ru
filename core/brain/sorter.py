"""Сортировщик: одно сообщение-список → много записей нужных типов.

«Задачи на день: доделать матрицу, купить очки, в 15:00 врач, клиент Ромашка, заказ логотип для Ромашки 15к до пятницы,
человек Лена — сестра, мысль — попробовать рисовать» — раньше такое улетало в модель с инструментами, и она клала всё
одной заметкой. Здесь текст сначала проходит через нейронку в строгом JSON (каждый пункт → тип + поля), потом каждый
пункт записывается своим сервисом напрямую — модель не может «забыть вызвать инструмент». Человек получает разбор по
группам, «отмени» откатывает всю пачку.

Разбирает облако (если включено) — оно заметно надёжнее на длинных смешанных списках, чем локальная 4b. Настройка
brain.sorter.where: cloud / local / auto. Честно: весь текст сообщения уходит в облако целиком.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from sqlmodel import select

from ..db import ActionLog, get_setting, session, set_setting
from ..services import brain_notes, calendar, finance, goals, orders, people, tasks, undo
from ..services.calendar import fmt_dt
from ..services.finance import money
from . import llm
from .dates import fix_night_hour, parse_datetime, parse_datetime_ex
from .persona import now_line

log = logging.getLogger("assistant.sorter")

# явная «шапка» списка: «задачи на день: …», «на завтра: …», «разбери: …», «пожалуйста, запиши дела: …»
HEAD_RX = re.compile(r"^\s*(?:пожалуйста[,\s]+)?(?:запиши|добавь|разбери|разложи|рассортируй|сохрани)?\s*"
                     r"(?:мне\s+|пожалуйста\s+)?(?:задачи|дела|планы?|список|всё|все|на\s+(?:сегодня|завтра|день|неделю|выходные)|сегодня|завтра)"
                     r"\b[^:\n]{0,30}[:\-—]\s*\S", re.I)
# явный префикс заметки — человек сам сказал «в мозг», не сортируем
NOTE_HEAD_RX = re.compile(r"^\s*(мозг|в\s+мозг|мысль|заметка|идея|запомни)(?![а-яё])", re.I)
# одна команда с явным префиксом («заказ: ролик, 25к, до пятницы», «клиент: Пятёрочка, сеть») — запятые внутри не список
ONE_CMD_RX = re.compile(r"^\s*(?:новый\s+)?(?:заказ|проект|клиент|компания|фирма|человек|контакт|персона|долг|цель|ссылка|задача|встреча|событие|напомни)\s*[:\-—]", re.I)
INF_RX = re.compile(r"^\s*(?:(?:надо|нужно|не\s+забыть|обязательно|срочно|ещё|еще|потом|и)\s+)*[а-яё]{3,}(?:ть|ти|чь)(?:ся)?\b", re.I)   # пункт начинается с «сделать …»
# явные маркеры типов внутри пункта — «клиент …», «заказ …», «человек …», «должен …», «цель …», «ссылка …»
TYPED_RX = re.compile(r"(?:^|\s)(?:клиент|компания|фирма|человек|контакт|заказ|проект|долг|должен|должна|цель|копим|подушк|ссылк|https?://|сделал|готово|выполнил|пришл[оа]|оплат|аванс|подписк|регулярн|каждый\s+месяц)", re.I)
# жёсткие разделители — переносы строк, «;», маркеры списка, нумерация
HARD_SPLIT_RX = re.compile(r"\n+|;\s*|\s+[•·\-–—]\s+|(?:^|\s)\d{1,2}[.)]\s+")
ITEM_SPLIT_RX = HARD_SPLIT_RX
BATCH_TTL_H = 24
KINDS_ORDER = ("task", "event", "order", "order_payment", "person", "family", "friend", "client", "company", "debt", "goal", "recurring", "expense", "income", "link", "note", "done")
KIND_LABEL = {"task": "📋 Задачи", "event": "📅 В календарь", "note": "🧠 В память", "expense": "💸 Траты", "income": "💰 Доходы",
              "person": "👤 Люди", "family": "👨‍👩‍👧 Семья", "friend": "🫂 Друзья", "client": "🤝 Клиенты", "company": "🏢 Компании", "order": "💼 Заказы", "order_payment": "💳 Оплаты по заказам",
              "debt": "🏦 Долги", "goal": "🎯 Цели", "recurring": "🔁 Регулярные", "link": "🔗 Ссылки", "done": "✅ Закрыто"}

PROMPT = """Ты разбираешь сообщение человека на отдельные записи для личного помощника. Ответь СТРОГО в JSON без пояснений:
{"items": [{"kind": "...", "title": "...", "when": "YYYY-MM-DDTHH:MM или YYYY-MM-DD или null", "amount": число или null, "priority": 1|2|3,
            "who": "имя человека/клиента или null", "note": "уточнение или null", "hours": число или null, "status": "work|done|paid или null",
            "url": "ссылка или null", "day": число 1-31 или null}]}

Типы (kind):
- task — дело, которое надо сделать (купить, позвонить, доделать, приготовить). Если в шапке «на сегодня/на завтра» — у каждой задачи when = эта дата (только дата).
- done — человек сообщает, что дело СДЕЛАНО («сделал отчёт», «отправил правки», «готово: …»). title — как называлось дело.
- event — есть конкретное время или это визит/приём/встреча/звонок с датой («в 15:00 врач», «завтра в 10 парикмахер»). when обязателен с временем.
- note — мысль, факт, идея, наблюдение, то, что нужно просто запомнить (не действие).
- expense / income — деньги с суммой («хлеб 120», «пришла пенсия 20000»), НЕ связанные с заказом. amount — рубли.
- family — родственник («мама», «Лена — сестра», «брат Дима»). friend — друг/подруга/приятель. person — человек, про которого непонятно, кто он
  («человек: Ваня, +7…», «врач Петров»). title = имя, note = кто это/контакт. НЕ делай человека client без слова «клиент/заказчик» или заказа.
- client — заказчик («клиент Пятёрочка», «новый клиент Иван Петров»). title = имя. company — если явно компания/фирма/ООО.
- order — фриланс-заказ/проект («заказ логотип для Ромашки 15к до пятницы», «взял монтаж свадьбы за 40к»). title = что делаем,
  who = клиент, amount = цена, when = дедлайн, hours = оценка часов если названа, status: "done" если сказано «старый/сдал»,
  "paid" если «уже оплачен/закрыт», иначе null.
- order_payment — деньги пришли ПО ЗАКАЗУ («пришло 15000 за логотип», «аванс от Ромашки 5000»). title = заказ или клиент, amount, when = дата если названа.
- debt — Я кому-то должен / кредит («должен Лене 3000», «кредит Сбер 200к, платёж 8000 5-го»). title, amount = сумма, note = кому, day = день платежа.
  Если наоборот — кто-то должен МНЕ («Ваня должен мне 5000») — kind = note, title = «Ваня должен мне 5000».
- goal — накопление («цель подушка 300к к марту», «копим на отпуск 100к»). title, amount, when = срок.
- recurring — регулярный платёж («подписка Яндекс 300 каждый месяц 5-го», «аренда 30000 1-го»). title, amount, day.
- link — есть URL. url = адрес, note = комментарий человека.

Правила:
- Каждый пункт списка — ОДИН item. Не дроби один пункт на несколько и не объединяй разные. Ничего не выдумывай и не добавляй.
- title — коротко, с заглавной буквы, без точки в конце, слова человека сохраняй (только опечатки поправь). Шапку списка («задачи на день») в items не включай.
- priority: 1 — если человек подчеркнул срочность/важность, иначе 2.
- Суммы: «15к» = 15000, «1.5к» = 1500, «200 тыс» = 200000.
- Даты считай от текущей даты в конце сообщения. «До пятницы» — ближайшая пятница. Оплата «20 августа» без года — прошедшая дата этого года.
- Если тип непонятен — task для действий, note для всего остального."""


def split_items(text: str) -> list[str]:
    parts = [p.strip(" .") for p in HARD_SPLIT_RX.split(text) if p and p.strip(" .")]
    if len(parts) >= 2:
        return parts
    parts = [p.strip(" .") for p in re.split(r",\s*", text) if p.strip(" .")]
    if len(parts) >= 3:
        return parts
    # «доделать матрицу, написать песню и навести порядок» — последний пункт через «и» перед глаголом
    return [p.strip(" .") for p in re.split(r",\s*|\s+и\s+(?=[а-яё]+(?:ть|ти|чь)(?:ся)?\b)", text, flags=re.I) if p.strip(" .")]


def looks_like_batch(text: str) -> bool:
    """Похоже ли на список из нескольких дел/записей (а не одна команда, вопрос или рассказ).

    2+ пункта, если разделены жёстко (переносы, «;», нумерация, маркеры) или есть шапка; 3+ — через запятые.
    """
    t = text.strip()
    if len(t) < 20 or NOTE_HEAD_RX.match(t) or t.rstrip().endswith("?"):
        return False
    if ONE_CMD_RX.match(t) and not HARD_SPLIT_RX.search(t):
        return False
    from .agent import ANALYZE_RX, ACTION_VERB_RX, _QUESTION_RX
    if ANALYZE_RX.search(t) or _QUESTION_RX.match(t.lower()):
        return False
    hard = [p for p in HARD_SPLIT_RX.split(t) if p and p.strip(" .")]
    if len(hard) >= 2 and (HEAD_RX.match(t) or len(hard) >= 3 or any(TYPED_RX.search(p) or ACTION_VERB_RX.search(p) or INF_RX.search(p) for p in hard)):
        return True
    if "http" in t and len(hard) < 2:
        return False   # одна ссылка с комментарием — обычный путь (превью, теги)
    items = split_items(t)
    if len(items) < 3:
        return False
    if HEAD_RX.match(t):
        return True
    verbs = sum(1 for i in items if ACTION_VERB_RX.search(i) or INF_RX.search(i))
    typed = sum(1 for i in items if TYPED_RX.search(i))
    priced = sum(1 for i in items if re.search(r"\d{2,}", i))   # «хлеб 120, молоко 90, яйца 150» — несколько трат
    return verbs >= 2 or priced >= 3 or (typed >= 1 and verbs + typed >= 2)


def where() -> str:
    """Кто разбирает списки: cloud / local / auto (по настройке brain.sorter.where; по умолчанию облако, если включено)."""
    from .. import config as _c
    node = getattr(_c.cfg.brain, "sorter", None)
    w = str(getattr(node, "where", "cloud") or "cloud").lower()
    return w if w in ("cloud", "local", "auto") else "cloud"


async def _ask_llm(text: str) -> tuple[list[dict] | None, str]:
    user = text.strip() + "\n" + now_line()
    msgs = [{"role": "system", "content": PROMPT}, {"role": "user", "content": user}]
    w = where()
    raw, via = "", "none"
    cloud_ok = llm.cloud_enabled()
    local_ok = await llm.ollama_available()
    if w == "cloud" and cloud_ok:
        raw = await llm.cloud_chat(PROMPT + "\nТолько JSON, без markdown.", user) or ""
        via = "gemini"
        if not raw and local_ok:   # облако легло — локальная подстрахует
            out = await llm.ollama_chat(msgs, temperature=0.1, json_mode=True)
            raw, via = out.get("content") or "", "ollama"
    elif w == "local" and local_ok:
        out = await llm.ollama_chat(msgs, temperature=0.1, json_mode=True)
        raw, via = out.get("content") or "", "ollama"
    elif local_ok and (w != "cloud" or not cloud_ok):
        out = await llm.ollama_chat(msgs, temperature=0.1, json_mode=True)
        raw, via = out.get("content") or "", "ollama"
    elif cloud_ok:
        raw = await llm.cloud_chat(PROMPT + "\nТолько JSON, без markdown.", user) or ""
        via = "gemini"
    else:
        return None, via
    return _parse(raw), via


def _parse(raw: str) -> list[dict] | None:
    m = re.search(r"\{.*\}", raw or "", re.S)
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
        dt, _, time_set = parse_datetime_ex(v)
        # «сегодня», «в пятницу» без времени → 00:00, дальше задача превратит это в «весь день», событие — оставит утро
        return dt.replace(hour=0, minute=0) if dt and not time_set and not (dt.hour == 23 and dt.minute == 59) else dt


def _amount(v) -> float | None:
    if isinstance(v, str):
        s = v.lower().replace(" ", "").replace(",", ".")
        mult = 1000 if re.search(r"(к|k|тыс)$", s) else 1
        s = re.sub(r"[^\d.]", "", s)
        try:
            a = abs(float(s)) * mult
        except ValueError:
            return None
        return a if a > 0 else None
    try:
        a = abs(float(v))
    except (TypeError, ValueError):
        return None
    return a if a > 0 else None


def _s(v) -> str | None:
    if v is None:
        return None
    s = str(v).strip(" .«»\"'")
    if s.lower() in ("none", "null", "nil", "undefined", "n/a"):
        return None  # модель иногда пишет «None» строкой — это не заметка
    return s or None


async def apply_items(items: list[dict], channel: str, confirm_amount: float = 100_000) -> tuple[dict[str, list[str]], list[str], list[str]]:
    """Записать разобранные пункты по сервисам. Возвращает (сделано по типам, пропущено, действия)."""
    done: dict[str, list[str]] = {}
    skipped: list[str] = []
    actions: list[str] = []

    def ok(kind: str, line: str, action: str | None = None):
        done.setdefault(kind, []).append(line)
        actions.append(action or f"add_{kind}")

    for it in items[:40]:
        if not isinstance(it, dict):
            continue
        title = _s(it.get("title")) or ""
        kind = str(it.get("kind") or "task").lower().strip()
        when = _when(it.get("when"))
        amount = _amount(it.get("amount"))
        who = _s(it.get("who"))
        note = _s(it.get("note"))
        if kind in ("task", "event"):
            when = fix_night_hour(when, f"{title} {note or ''} {it.get('when') or ''}")
        url = _s(it.get("url"))
        if not title and not url:
            continue
        if title:
            title = title[0].upper() + title[1:]
        try:
            if kind in ("expense", "income") and amount:
                if amount >= confirm_amount:
                    skipped.append(f"{title} {money(amount)} — крупная сумма, запишите отдельно, я переспрошу")
                    continue
                finance.add_transaction(amount, kind, note=title, source=channel, date=when)
                ok(kind, f"{title} — {money(amount)}")
            elif kind == "event" and when and (when.hour or when.minute):
                ev = calendar.add_event(title, when, remind_minutes=30, source=channel)
                ok("event", f"{ev.title} — {fmt_dt(ev.start)}")
            elif kind == "note" or (kind in ("expense", "income") and not amount):
                body = title if not note else f"{title} — {note}"
                brain_notes.add_note(body, source=channel)
                ok("note", body)
            elif kind == "done":
                t = tasks.complete_task(title)
                if t:
                    ok("done", t.title, "complete_task")
                else:
                    skipped.append(f"«{title}» — такой открытой задачи не нашёл")
            elif kind in ("person", "family", "friend", "client", "company"):
                c = people.add_person(title, kind, notes=note)
                ok(kind, c.name + (f" — {note}" if note else ""), "add_person")
            elif kind == "order":
                status = str(it.get("status") or "work").lower()
                status = status if status in ("work", "done", "paid", "new", "review") else "work"
                hours = _amount(it.get("hours")) or 0
                o = orders.add_order(title, amount or 0, who, when, notes=note, estimate_h=hours, status="done" if status == "paid" else status, source=channel)
                line = o.title + (f" · {who}" if who else "") + (f" · {money(o.price)}" if o.price else "") + (f" · до {o.deadline:%d.%m}" if o.deadline else "")
                if status == "paid":
                    orders.update_order(o.id, status="paid")
                    line += " · оплачен"
                elif status == "done":
                    line += " · сдан, ждём оплату"
                ok("order", line)
            elif kind == "order_payment" and amount:
                q = who or title
                o = orders.find_order(q) if q else None
                if not o:
                    skipped.append(f"оплата {money(amount)} «{q}» — не нашёл такой заказ (заведите заказ первым пунктом)")
                    continue
                pay_date = when if when and when < datetime.now() else None
                orders.add_payment(o.id, amount, source=channel, date=pay_date)
                v = orders.order_view(orders.get_order(o.id))
                ok("order_payment", f"{v['title']} — {money(amount)}" + (f" за {pay_date:%d.%m}" if pay_date else "") + (" · заказ закрыт" if v["status"] == "paid" else f" · осталось {money(v['left'])}"), "order_payment")
            elif kind == "debt" and amount:
                d = finance.add_debt(title, amount, creditor=note, pay_day=int(it.get("day") or 1))
                ok("debt", f"{d.title} — {money(d.remaining)}" + (f" ({note})" if note else ""))
            elif kind == "goal" and amount:
                g = goals.add_goal(title, amount, when, source=channel)
                ok("goal", f"{g.title} — {money(g.target)}" + (f" к {when:%d.%m.%Y}" if when else ""))
            elif kind == "recurring" and amount:
                r = finance.add_recurring(title, amount, int(it.get("day") or 1), "expense")
                ok("recurring", f"{r.title} — {money(r.amount)} {r.day}-го")
            elif kind == "link" and url:
                lk = await brain_notes.add_link(url, note or (title if title != url else None), source=channel)
                ok("link", lk.title or url)
            else:
                # задача; дата без времени → дедлайн конец дня, чтобы не сыпались напоминания «через час»
                due = when.replace(hour=23, minute=59) if when and not (when.hour or when.minute) else when
                pr = it.get("priority") if it.get("priority") in (1, 2, 3) else 2
                tk = tasks.add_task(title, due, pr, source=channel)
                if due and (due.hour, due.minute) == (23, 59):
                    with session() as s:
                        row = s.get(tasks.Task, tk.id)
                        if row and row.remind_stage < 2:
                            row.remind_stage = 2; s.add(row); s.commit()
                ok("task", tk.title + (f" — до {fmt_dt(due)}" if due and (due.hour, due.minute) != (23, 59) else ""))
        except (finance.FinanceError, orders.OrderError) as e:
            skipped.append(f"{title or url}: {e}")
    return done, skipped, actions




def preview_text(items: list[dict]) -> str:
    """Черновик разбора для режима «показывать перед записью»."""
    lines = ["Вот как я это понял:"]
    for it in items[:40]:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("kind") or "task").lower()
        label = KIND_LABEL.get(kind, kind).split(" ", 1)[-1].lower()
        bits = [str(it.get("title") or it.get("url") or "").strip()]
        if it.get("who"): bits.append(str(it["who"]))
        if _amount(it.get("amount")): bits.append(money(_amount(it["amount"])))
        if it.get("when"): bits.append(str(it["when"]))
        lines.append(f"• {label}: " + " · ".join(b for b in bits if b))
    lines.append("\nЗаписать? «да» / «нет».")
    return "\n".join(lines)


def confirm_enabled() -> bool:
    from .. import config as _c
    node = getattr(_c.cfg.brain, "sorter", None)
    return bool(getattr(node, "confirm", False))


async def commit(items: list[dict], channel: str, via: str, confirm_amount: float = 100_000):
    """Записать пункты и собрать ответ."""
    from .agent import Reply
    with session() as s:
        last = s.exec(select(ActionLog.id).order_by(ActionLog.id.desc())).first() or 0
    done, skipped, actions = await apply_items(items, channel, confirm_amount)
    if not done:
        return None
    with session() as s:
        ids = [i for i in s.exec(select(ActionLog.id).where(ActionLog.id > last)).all()]
    set_setting(f"batch:{channel}", f"{datetime.now().isoformat()}|{','.join(map(str, ids))}")
    total = sum(len(v) for v in done.values())
    lines = [f"Разобрал, получилось {total} {_plural(total, 'запись', 'записи', 'записей')}:"]
    for kind in KINDS_ORDER:
        if kind in done:
            lines.append(f"\n{KIND_LABEL[kind]} ({len(done[kind])}):")
            lines += [f"• {x}" for x in done[kind]]
    if skipped:
        lines.append("\nНе записал:")
        lines += [f"• {x}" for x in skipped]
    lines.append("\nЕсли что-то не туда — «отмени» уберёт всю пачку, или «удали задачу …» одну.")
    return Reply("\n".join(lines), sorted(set(actions)), via)


async def sort(text: str, channel: str, confirm_amount: float = 100_000):
    """Разобрать сообщение-список и записать всё по местам. None — модель не справилась (пойдём обычным путём)."""
    from .agent import Reply, _pending_set
    try:
        items, via = await _ask_llm(text)
    except Exception as e:
        log.warning("sorter: модель не ответила: %s", e)
        return None
    if not items:
        return None
    if confirm_enabled():
        _pending_set(channel, "sorter|" + json.dumps({"items": items, "via": via}, ensure_ascii=False))
        return Reply(preview_text(items), [], via)
    return await commit(items, channel, via, confirm_amount)


async def resolve_pending(text: str, channel: str, pending: str, confirm_amount: float = 100_000):
    """Ответ «да»/«нет» на черновик разбора."""
    from .agent import Reply, YES_RX, NO_RX
    d = json.loads(pending[len("sorter|"):])
    if YES_RX.match(text):
        return (await commit(d["items"], channel, d.get("via", "rules"), confirm_amount)) or Reply("Записывать оказалось нечего, сэр.", [], "rules")
    if NO_RX.match(text):
        return Reply("Отбой, ничего не записал.", [], "rules")
    return None


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
