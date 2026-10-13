# -*- coding: utf-8 -*-
"""Правки: fix/catchange (исправление типа и категории), правка заметок,
перенос/переименование/удаление, автоперенос, undo-просьбы.

Вынесено из core/brain/agent.py 1:1. Общие хелперы (Reply, regexes,
_pending_*, say/money, fmt_*) остаются в agent и импортируются здесь.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from ..agent import (
    AUTO_ROLL_MARK_RX,
    AUTO_ROLL_OFF_PRE_RX,
    AUTO_ROLL_OFF_RX,
    AUTO_ROLL_ON_PRE_RX,
    AUTO_ROLL_ON_RX,
    DELETE_RX,
    EDIT_NOTE_RX,
    FIX_RX,
    MOVE_RX,
    NO_RX,
    PENDING_TTL_SEC,
    RENAME_RX,
    SKIP_RX,
    UNDO_RX,
    Reply,
    _ACTION_KIND,
    _CATCHANGE_KIND_RX,
    _CATCHANGE_RX,
    _FIX_BARE_RX,
    _FIX_KIND,
    _channel_where,
    _clean_event_title,
    _past_date,
    _pending_clear,
    _pending_consume,
    _pending_get,
    _pending_set,
    _plural_ru,
    _remind_at,
    _strip_fillers,
    fmt_dt,
    fmt_due,
    log,
    money,
    say,
)


def fix_kind(word: str) -> str | None:
    w = word.lower()
    for pref, k in _FIX_KIND:
        if w.startswith(pref):
            return k
    return None


def _last_user_text(channel: str) -> str | None:
    """Предыдущая реплика хозяина (не текущая) — исходник для перезаписи другим типом."""
    from core.db import ChatMessage, session
    from sqlmodel import select

    with session() as s:
        rows = s.exec(select(ChatMessage).where(ChatMessage.role == "user").order_by(ChatMessage.id.desc()).limit(2)).all()
    return rows[1].text if len(rows) > 1 else None


def write_as(kind: str, text: str, channel: str) -> Reply | None:
    """Записать фразу заданным типом (после судьи, урока или исправления). None — не смог разобрать (нет суммы и т.п.)."""
    from core.brain.dates import parse_amount as _pa
    from core.brain.dates import parse_datetime as _pd
    from core.brain.dates import parse_datetime_ex as _pdx
    from core.brain.dates import task_due as _td
    from core.services import brain_notes, calendar, finance, tasks

    t = text.strip()
    if kind in ("expense", "income"):
        amount, rest = _pa(re.sub(r"^\s*(потратил\w*|получил\w*|отдал\w*|заплатил\w*|пришл[оа]|перевёл|перевел|перекинул\w*|закинул\w*|скинул\w*)\s*", "", t, flags=re.I))
        if amount is None:
            return None
        when, rest = _past_date(rest)
        note = _strip_fillers(rest) or None
        tx = finance.add_transaction(amount, kind, None, note, source=channel, date=when)
        sm = finance.summary(1)
        return Reply(say(kind, amount=money(tx.amount), category=tx.category, balance=money(sm["total_balance"])), [f"add_{kind}"])
    if kind == "debt":
        amount, rest = _pa(t)
        if amount is None:
            return None
        title = _strip_fillers(re.sub(r"^\s*(долг|должен|должна|отдал\w*|дал\w*|занял\w*|взял\w*|одолжил\w*|перевёл|перевел|перекинул\w*|закинул\w*|скинул\w*)\s*", "", rest, flags=re.I)) or "Долг"
        d = finance.add_debt(title[0].upper() + title[1:], amount)
        return Reply(f"Долг «{d.title}» на {money(d.remaining)} записан.", ["add_debt"])
    if kind == "order":
        from core.services import orders
        client = None
        mc = re.search(r"(?:^|\s)(?:для|от|клиент[:\s])\s*([А-ЯЁA-Z][\w\-]*(?:\s+[А-ЯЁA-Z][\w\-]*)?)", t)
        body = t
        if mc:
            client = mc.group(1); body = (t[:mc.start()] + " " + t[mc.end():]).strip()
        amount, rest = _pa(re.sub(r"^\s*(заказ|проект|новый\s+заказ)\s*[:\-—]?\s*", "", body, flags=re.I))
        dt, rest = _pd(rest)
        title = re.sub(r"\s{2,}", " ", rest).strip(" ,.-—:;")
        if not title:
            return None
        o = orders.add_order(title[0].upper() + title[1:], amount or 0, client, dt, source=channel)
        return Reply(f"Заказ #{o.id} «{o.title}»" + (f" · {money(o.price)}" if o.price else " · сумму уточним") + ". В работе.", ["add_order"])
    if kind == "task":
        auto_roll = bool(AUTO_ROLL_MARK_RX.search(t))
        t = AUTO_ROLL_MARK_RX.sub(" ", t).strip() if auto_roll else t
        due, body, time_set = _pdx(t)
        due = _td(due, time_set)
        body = re.sub(r"^\s*(задача|надо\s+бы|надо|нужно|не\s+забыть)\s*[:\-—]?\s*", "", body, flags=re.I).strip() or t
        tk = tasks.add_task(body[0].upper() + body[1:], due, source=channel, auto_roll=auto_roll)
        return Reply(say("task", title=tk.title) + fmt_due(due) + (" · автоперенос вкл" if auto_roll else ""), ["add_task"])
    if kind == "event":
        dt, rest = _pd(t)
        if not dt:
            return None
        title = _clean_event_title(re.sub(r"^\s*(встреча|событие|у\s+меня)\s*[:\-—]?\s*", "", rest, flags=re.I))
        ev = calendar.add_event(title[0].upper() + title[1:], dt, remind_minutes=30, source=channel)
        return Reply(say("event", title=ev.title, when=fmt_dt(ev.start), remind=_remind_at(ev.start, 30)), ["add_event"])
    if kind == "note":
        brain_notes.add_note(re.sub(r"^\s*(мозг|мысль|заметка|запомни)\s*[:\-—,]?\s*", "", t, flags=re.I) or t, source=channel)
        return Reply(say("note"), ["add_note"])
    return None


def resolve_category_name(want: str, kind: str) -> str | None:
    """«доставка еды» → «Еда»: сначала точное имя категории, потом угадайка по ключевым словам."""
    from core.services import finance as _finance

    low = (want or "").strip().lower()
    if not low:
        return None
    for c in _finance.list_categories(kind):
        if c.name.lower() == low:
            return c.name
    g = _finance.guess_category(want, kind)
    if g not in ("Другое", "Прочий доход"):
        return g
    return None


def fix_apply(kind: str, channel: str) -> Reply | None:
    from core.services import finance as _finance
    from core.services import judge, undo

    a = undo.last_action(channel, max_age_min=30)
    orig = _last_user_text(channel)
    if not a or not orig or a.kind not in _ACTION_KIND:
        return Reply("Исправлять нечего, сэр: за последние полчаса я ничего не записывал. Скажите фразу заново — запишу как " + judge.KIND_RU[kind] + ".", [])
    wrong = _ACTION_KIND[a.kind]
    if wrong == kind:
        return Reply(f"Так и записано — {judge.KIND_RU[kind]}: «{a.title}».", [])
    try:
        r = write_as(kind, orig, channel)
    except (_finance.FinanceError, ValueError) as e:
        log.warning("fix as %s failed: %s", kind, e)
        r = None
    if r is None:
        return Reply(f"Понял, что это {judge.KIND_RU[kind]}, но из «{orig[:60]}» не собрал запись" + (" — нет суммы." if kind in ("expense", "income", "debt") else " — нет даты." if kind == "event" else ".") + " Скажите заново, сэр.", [])
    undo.undo_one(a)   # откатываем именно ту запись, а не только что созданную
    judge.add_lesson(orig, kind, wrong=wrong)
    r.text = f"Переложил: было «{judge.KIND_RU[wrong]}», теперь {judge.KIND_RU[kind]}. " + r.text + " Запомнил на будущее."
    r.actions = r.actions + ["fix", "lesson"]
    return r


def resolve_judge_rule(text: str, low: str, channel: str) -> Reply | None:
    """Ответ на вопрос судьи («трата, заказ или доход?»)."""
    from core.services import finance as _finance
    from core.services import judge

    p = _pending_get(channel)
    if not p or not p[0].startswith("judge|"):
        return None
    orig, ts = p
    if (datetime.now() - ts).total_seconds() > PENDING_TTL_SEC:
        _pending_clear(channel)
        return None
    orig = orig[6:]
    m = re.match(r"^\s*(?:это\s+)?(трата|расход|доход|долг|заказ|проект|задача|дело|событие|встреча|календарь|заметка|мысль|мозг)\s*[.!]*\s*$", text, re.I)
    if NO_RX.match(text):
        _pending_clear(channel)
        return Reply("Ок, не записываю.", [])
    if not m:
        return None   # заговорили о другом — вопрос снимется по TTL
    kind = fix_kind(m.group(1))
    _pending_clear(channel)
    try:
        r = write_as(kind, orig, channel)
    except _finance.FinanceError as e:
        return Reply(f"Не записал: {e}", [], "rules")
    if r is None:
        return Reply(f"Понял, {judge.KIND_RU[kind]}, но из «{orig[:60]}» не собрал запись. Скажите заново полностью, сэр.", [])
    judge.add_lesson(orig, kind)
    r.text += " Запомнил: в следующий раз такое не переспрошу."
    r.actions = r.actions + ["lesson"]
    return r


def fix_rule(text: str, low: str, channel: str) -> Reply | None:
    """«это задача» после неверной записи: откатить последнее, записать исходную фразу нужным типом, запомнить урок."""
    m = FIX_RX.match(text)
    if not m:
        return None
    kind = fix_kind(m.group(1))
    if not kind:
        return None
    return fix_apply(kind, channel)


def resolve_fix_rule(text: str, low: str, channel: str) -> Reply | None:
    """Голое «трата/заказ/…» сразу после догадки судьи (pending fix|): чиним, как явное «это трата».
    Без свежей догадки — не трогаем (слот пуст): голое слово идёт обычным путём."""
    p = _pending_consume(channel, prefix="fix|")
    if not p:
        return None
    m = _FIX_BARE_RX.match(text)
    if not m:
        return None   # заговорили о другом — слот снят, ничего не пишем
    kind = fix_kind(m.group(1))
    if not kind:
        return None
    return fix_apply(kind, channel)


def catchange_rule(text: str, low: str, channel: str) -> Reply | None:
    """«это еда» / «это доставка еды а не транспорт» после траты/дохода: меняем категорию
    последней операции офлайн, с настоящими цифрами."""
    from core.db import Transaction, session
    from core.services import finance as _finance
    from core.services import undo

    m = _CATCHANGE_RX.match(text)
    if not m:
        return None
    body = m.group(1).strip()
    if _CATCHANGE_KIND_RX.match(body):
        return None   # вид записи («это трата») — дело судьи/фикса, не категория
    m2 = re.match(r"^(.*?)\s+а\s+не\s+.+$", body, re.I | re.S) or re.match(r"^не\s+.+?\s+а\s+(.+)$", body, re.I | re.S)
    want = (m2.group(1) if m2 else body).strip(" ,.-—:")
    a = undo.last_action(channel, max_age_min=30)
    if not a or a.kind not in ("add_expense", "add_income") or a.ref_table != "transaction":
        return None   # править нечего — фраза идёт обычным путём
    kind = "expense" if a.kind == "add_expense" else "income"
    with session() as s:
        tx = s.get(Transaction, a.ref_id)
        old, amount = (tx.category, tx.amount) if tx else (None, None)
    if tx is None:
        return None
    cat = resolve_category_name(want, kind)
    if cat is None:
        return Reply(f"Не нашёл категорию «{want[:40]}», сэр: {money(amount)} · {old} — оставил как было. Скажите точнее — например «это еда».", [])
    if cat == old:
        return Reply(f"Так и стоит — {cat}: {money(amount)}.", [])
    _finance.update_transaction(tx.id, category=cat)
    return Reply(f"Понял: было «{old}», стало «{cat}», сэр: {money(amount)} · {cat}.", ["update_transaction"],
                 buttons=[("↩ Отменить", "отмени")])


def edit_note_rule(text: str, low: str, channel: str) -> Reply | None:
    """«исправь заметку про очки: они в комоде», «дополни мысль о ролике: добавить титры» — правка памяти без модели."""
    from core.services import brain_notes

    t = text
    m = EDIT_NOTE_RX.match(t)
    if not m:
        return None
    verb, _, query, body = m.group(1).lower(), m.group(2), m.group(3).strip(" «»\"'"), m.group(4).strip()
    n = brain_notes.find_note(query)
    if not n:
        return Reply(f"Заметку про «{query}» не нашёл, сэр. Посмотрите в Мозге, как она называется.", [])
    if verb.startswith(("дополни", "допиши")):
        head = (n.title or n.text.splitlines()[0])[:50]
        n = brain_notes.update_note(n.id, append=body)
        return Reply(f"Дописал в «{head}»: {body[:150]}", ["edit_note"])
    body = body[0].upper() + body[1:]
    n = brain_notes.update_note(n.id, text=body)
    return Reply(f"Заметка обновлена: «{n.text[:200]}». Старый вариант сохранён как оригинал.", ["edit_note"])


def auto_roll_rule(text: str, low: str, channel: str) -> Reply | None:
    """«задача X каждый день переноси» / «X с автопереносом» → флаг вкл;
    «X без автопереноса» / «убери автоперенос у X» → флаг выкл."""
    from core.services import tasks

    t = text
    want: bool | None = None
    what: str | None = None
    for rx, flag in ((AUTO_ROLL_OFF_RX, False), (AUTO_ROLL_OFF_PRE_RX, False),
                     (AUTO_ROLL_ON_RX, True), (AUTO_ROLL_ON_PRE_RX, True)):
        m = rx.match(t)
        if m:
            want, what = flag, m.group(1).strip(" .!«»\"'")
            break
    if want is None or not what:
        return None
    what = re.sub(r"^(задачу|задача|дело)\s+(про|о|об)?\s*", "", what, flags=re.I).strip() or what
    tk = tasks.find_task(what)
    if tk is None and what.isdigit():
        tk = tasks.find_task(int(what))
    if tk is None:
        return Reply(f"Не нашёл задачу «{what}», сэр.", [])
    tasks.update_task(tk.id, auto_roll=want)
    if want:
        return Reply(f"Включил автоперенос «{tk.title}»: не закроете — сама переедет на завтра.", ["update_task"])
    return Reply(f"Выключил автоперенос «{tk.title}»: вечером спрошу, перенести ли.", ["update_task"])


def edit_rule(text: str, low: str, channel: str) -> Reply | None:
    """«перенеси ужин на 8», «переименуй встречу в созвон», «удали задачу про полку», «сегодня тренировки не будет»."""
    from core.brain.dates import parse_datetime as _pd
    from core.services import brain_notes, calendar, tasks
    from core.services.calendar import fmt_task_due as _ftd

    t = text
    r = auto_roll_rule(t, low, channel)
    if r is not None:
        return r
    m = SKIP_RX.match(t)
    if m:
        ev = calendar.find_event(m.group(2).strip())
        if ev and ev.repeat:
            day = datetime.now() + (timedelta(days=1) if m.group(1).lower() == "завтра" else timedelta(0))
            calendar.skip_occurrence(ev.id, day)
            return Reply(f"Понял, «{ev.title}» {m.group(1).lower()} пропускаем. Повтор остаётся.", ["update_event"])
        if ev:
            calendar.delete_event(ev.id)
            return Reply(f"Убрал «{ev.title}» из календаря.", ["delete_event"])
        return Reply(f"Не нашёл «{m.group(2).strip()}» в календаре, сэр.")

    m = MOVE_RX.match(t)
    if m:
        what, when = m.group(2).strip(), m.group(3).strip()
        # «на 8» / «на 20:00» / «на завтра в 10» / «на пятницу»
        dt, _ = _pd("в " + when if re.fullmatch(r"\d{1,2}(?:[:.]\d{2})?", when) else when)
        if not dt:
            return Reply(f"Не понял, на когда перенести «{what}», сэр. Скажите время или день.")
        ev = calendar.find_event(what)
        if ev:
            # «на 8» без даты — оставляем день события, меняем только время
            if re.fullmatch(r"(?:в\s+)?\d{1,2}(?:[:.]\d{2})?(?:\s*(?:утра|вечера|дня|ночи))?", when.lower()):
                dt = ev.start.replace(hour=dt.hour, minute=dt.minute)
            old = fmt_dt(ev.start)
            ev = calendar.update_event(ev.id, start=dt)
            return Reply(f"Перенёс «{ev.title}»: {old} → {fmt_dt(ev.start)}.", ["update_event"])
        tk = tasks.find_task(what)
        if tk:
            tasks.update_task(tk.id, due=dt)
            return Reply(f"Дедлайн «{tk.title}» теперь {_ftd(dt)}.", ["update_task"])
        return Reply(f"Не нашёл «{what}» ни в календаре, ни в задачах, сэр.")

    m = RENAME_RX.match(t)
    if m:
        what, new = m.group(2).strip(), m.group(3).strip()
        what = re.sub(r"^(задачу|событие|встречу)\s+", "", what, flags=re.I)
        ev = calendar.find_event(what)
        if ev:
            calendar.update_event(ev.id, title=new[0].upper() + new[1:])
            return Reply(f"«{ev.title}» теперь называется «{new[0].upper() + new[1:]}».", ["update_event"])
        tk = tasks.find_task(what)
        if tk:
            tasks.update_task(tk.id, title=new[0].upper() + new[1:])
            return Reply(f"Задача «{tk.title}» → «{new[0].upper() + new[1:]}».", ["update_task"])
        return Reply(f"Не нашёл «{what}», сэр.")

    m = DELETE_RX.match(t)
    if m and m.group(3).strip() and not re.match(r"^(последн|это|её|его)", m.group(3).strip(), re.I):
        kind = (m.group(2) or "").lower()
        what = m.group(3).strip(" .!«»\"")
        if kind.startswith("задач") or not kind:
            tk = tasks.find_task(what)
            if tk and (kind or not calendar.find_event(what)):
                tasks.delete_task(tk.id)
                return Reply(f"Задача «{tk.title}» удалена.", ["delete_task"])
        if kind.startswith(("событ", "встреч", "напомин")) or not kind:
            ev = calendar.find_event(what)
            if ev:
                calendar.delete_event(ev.id)
                return Reply(f"«{ev.title}» ({fmt_dt(ev.start)}) убрано из календаря.", ["delete_event"])
        if kind.startswith(("заметк", "мысл")):
            n = brain_notes.find_note(what)
            if n:
                brain_notes.delete_note(n.id)
                return Reply("Заметку удалил.", ["delete_note"])
        if kind:
            return Reply(f"Не нашёл «{what}», сэр.")
    return None


def undo_ask_rule(text: str, low: str, channel: str) -> Reply | None:
    """Батч 3: «отмени» не откатывает молча — показывает ЧТО и ждёт «да»/«нет»."""
    from core.brain import sorter
    from core.services import undo

    if not UNDO_RX.match(text.strip().lower()):
        return None
    bi = sorter.batch_info(channel)
    if bi is not None:
        n, titles = bi
        _pending_set(channel, "undo|batch")
        tail = f" ({'; '.join(titles[:5])})" if titles else ""
        return Reply(f"Отменить всю пачку — {n} {_plural_ru(n, 'запись', 'записи', 'записей')}{tail}? "
                     "«да» — целиком, или скажите что именно («удали задачу …» одну).", ["clarify"],
                     buttons=[("✅ Да", "да"), ("❌ Нет", "нет")])
    a = undo.last_action(channel)
    if a is None:
        other = undo.last_action_any()
        if other is not None and other.channel != channel:
            label = undo._LABEL.get(other.kind, other.kind)
            _pending_set(channel, f"undo|single-any:{other.id}")
            return Reply(f"В этом канале записей не было, сэр. Но последнее действие было в другом канале — "
                         f"{label} «{other.title}» ({_channel_where(other.channel)}). Отменить его? «да»/«нет».", ["clarify"],
                         buttons=[("✅ Да", "да"), ("❌ Нет", "нет")])
        return Reply("Отменять нечего, сэр.", [])
    _pending_set(channel, "undo|single")
    label = undo._LABEL.get(a.kind, a.kind)
    return Reply(f"Отменить {label} «{a.title}»? Скажите «да» или «нет», сэр.", ["clarify"],
                 buttons=[("✅ Да", "да"), ("❌ Нет", "нет")])


RULES = [resolve_judge_rule, fix_rule, resolve_fix_rule, catchange_rule, edit_note_rule, undo_ask_rule, edit_rule]
