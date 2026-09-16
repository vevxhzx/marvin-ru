"""Инициативные сообщения: ассистент сам пишет о том, что заметил в базе, — когда сочтёт нужным, но не чаще N раз в день.

Что замечает (кандидаты, все считаются локально по базе):
- клиент задерживает оплату (режим фрилансера, pulse.late_payments);
- дело без срока висит дольше STALE_TASK_DAYS дней;
- дедлайн задачи сегодня, а времени в нём нет (легко забыть);
- «сейчас»-факт про самочувствие старше 2 дней → «как самочувствие?»;
- «сейчас»-факт про дело/план без задачи → «поставить задачу?».

Правила: тихие часы (notifications.quiet_*), лимит notifications.proactive_per_day, каждый повод — один раз
(ключ в Setting), кнопка «🔕 не надо про это» = Lesson(kind="mute") — тема больше не всплывает.
Формулировка — малая модель (llm.small_chat) в стиле персоны; без неё — шаблон. Никаких действий без сообщения:
всё, что предлагает, делается только по кнопке.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from sqlmodel import select

from ..brain import llm
from ..config import cfg
from ..db import Fact, Task, get_setting, session, set_setting
from . import judge

log = logging.getLogger("assistant.proactive")

STALE_TASK_DAYS = 5
HEALTH_RX = re.compile(r"болe|боле|просту|температур|давлени|самочувств|лечит|таблетк|врач|плохо\s+себя|устал|не\s+спал|бессонниц", re.I)
PLAN_RX = re.compile(r"\b(надо|нужно|собирается|планирует|хочет|думает)\s+\w+", re.I)
COUNT_KEY = "proactive.count"   # "YYYY-MM-DD|n"

STYLE_PROMPT = """Ты — личный ассистент с характером (лёгкий свэг, короткие фразы, обращение «сэр»). Перепиши подсказку одной-двумя
фразами по-русски, дружелюбно и по делу, без markdown и без эмодзи в начале. Не добавляй фактов. Ответ — только текст."""


def enabled() -> bool:
    n = getattr(cfg, "notifications", None)
    return bool(getattr(n, "proactive_enabled", True)) if n is not None else True


def per_day() -> int:
    n = getattr(cfg, "notifications", None)
    try:
        return max(0, int(getattr(n, "proactive_per_day", 5) or 5)) if n is not None else 5
    except (TypeError, ValueError):
        return 5


def _today_count() -> int:
    raw = get_setting(COUNT_KEY, "") or ""
    d, _, n = raw.partition("|")
    return int(n) if d == datetime.now().strftime("%Y-%m-%d") and n.isdigit() else 0


def _bump() -> None:
    set_setting(COUNT_KEY, f"{datetime.now():%Y-%m-%d}|{_today_count() + 1}")


def _sent(key: str) -> bool:
    return bool(get_setting("proactive:" + key))


def _mark(key: str) -> None:
    set_setting("proactive:" + key, datetime.now().isoformat())


def muted(topic: str) -> bool:
    """Тема замьючена кнопкой «не надо про это» (по словам, как уроки без эмбеддингов)."""
    w = judge._words(topic)
    if not w:
        return False
    for l in judge.list_lessons("mute"):
        lw = judge._words(l.text)
        if lw and len(w & lw) / len(w | lw) >= 0.5:
            return True
    return False


def mute(topic: str) -> None:
    judge.add_lesson(topic, "mute")


# ---------------------------------------------------------------- кандидаты
def candidates(now: datetime | None = None) -> list[dict]:
    """[{key, topic, text, buttons}] — что стоит сказать. Уже сказанное и замьюченное отфильтровано."""
    now = now or datetime.now()
    out: list[dict] = []
    # 1. задержки оплат (фриланс)
    try:
        from . import pulse
        if pulse.enabled() and pulse.freelance_settings().get("late_nudge", True):
            from .finance import money
            for x in pulse.late_payments(now)[:2]:
                who = x["client"] or f"«{x['title']}»"
                out.append({"key": f"late:{x['order_id']}:{x['days'] // 7}", "topic": f"оплата {who} {x['title']}",
                            "text": f"{who} задерживает {money(x['left'])} за «{x['title']}» — уже {x['days']} дн. после сдачи. Напомнить ему?",
                            "buttons": [("✍️ Задача: напомнить", f"pro:task:{x['order_id']}:late"), ("🔕 Не надо про это", f"pro:mute:{x['order_id']}:late")]})
    except Exception as e:  # pragma: no cover
        log.debug("late candidates: %s", e)
    # 2. задачи
    with session() as s:
        open_tasks = list(s.exec(select(Task).where(Task.done == False)))  # noqa: E712
    stale = [t for t in open_tasks if not t.due and (now - t.created_at).days >= STALE_TASK_DAYS and (t.project or "") != "archive"]
    stale.sort(key=lambda t: t.created_at)
    for t in stale[:1]:
        days = (now - t.created_at).days
        out.append({"key": f"stale:{t.id}:{days // 7}", "topic": t.title,
                    "text": f"«{t.title}» висит без срока уже {days} дн. Поставить дедлайн, сделать или отпустить?",
                    "buttons": [("📅 Завтра", f"task:{t.id}:tomorrow"), ("✅ Сделал", f"task:{t.id}:done"), ("🔕 Не надо", f"pro:mute:{t.id}:stale")]})
    today_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    for t in [t for t in open_tasks if t.due and t.due.date() == now.date() and t.due.hour == 23 and t.due.minute == 59 and now < today_noon]:
        out.append({"key": f"today:{t.id}:{now:%Y%m%d}", "topic": t.title,
                    "text": f"Сегодня дедлайн «{t.title}», а времени в нём нет — не потеряйте среди дня.",
                    "buttons": [("✅ Сделал", f"task:{t.id}:done"), ("📅 Завтра", f"task:{t.id}:tomorrow"), ("🔕 Не надо", f"pro:mute:{t.id}:today")]})
    # 3. факты «сейчас»: самочувствие и планы без задачи
    with session() as s:
        short = list(s.exec(select(Fact).where(Fact.layer == "short")))
    titles = " ".join(t.title.lower() for t in open_tasks)
    for f in short:
        age = (now - f.created_at).days
        if HEALTH_RX.search(f.text) and 2 <= age <= 7:
            out.append({"key": f"health:{f.id}", "topic": f.text,
                        "text": f"Пару дней назад вы упоминали: «{f.text}». Как самочувствие, сэр?",
                        "buttons": [("👍 Норм", f"pro:ok:{f.id}:health"), ("🔕 Не надо", f"pro:mute:{f.id}:health")]})
        elif PLAN_RX.search(f.text) and 1 <= age <= 5:
            words = judge._words(f.text)
            if words and not any(w in titles for w in words if len(w) >= 5):
                out.append({"key": f"plan:{f.id}", "topic": f.text,
                            "text": f"Вы говорили: «{f.text}». Задачи на это нет — поставить?",
                            "buttons": [("✍️ Поставить задачу", f"pro:task:{f.id}:plan"), ("🔕 Не надо", f"pro:mute:{f.id}:plan")]})
    return [c for c in out if not _sent(c["key"]) and not muted(c["topic"])]


# ---------------------------------------------------------------- формулировка
async def phrase(text: str) -> str:
    """Малая модель придаёт подсказке голос персоны; сбой или пустой ответ — исходный шаблон."""
    try:
        if not await llm.ollama_available():
            return text
        out = (await llm.small_chat(STYLE_PROMPT, text, json_mode=False, num_predict=120)).strip()
        if 10 <= len(out) <= 400 and "\n\n" not in out and not out.startswith("{"):
            return out
    except Exception as e:  # pragma: no cover
        log.debug("phrase: %s", e)
    return text


async def tick(now: datetime | None = None, quiet: bool = False) -> dict | None:
    """Один проход планировщика: выбрать один повод и вернуть {text, buttons, key} — или None. Отправку делает scheduler."""
    if not enabled() or quiet:
        return None
    if _today_count() >= per_day():
        return None
    cands = candidates(now)
    if not cands:
        return None
    c = cands[0]
    c["text"] = await phrase(c["text"])
    _mark(c["key"]); _bump()
    return c


# ---------------------------------------------------------------- кнопки
def act(action: str, ref: int, why: str) -> str:
    """pro:<action>:<ref>:<why> из Telegram. Возвращает текст для ответа."""
    if action == "mute":
        topic = None
        if why == "late":
            from .orders import get_order
            o = get_order(ref)
            topic = f"оплата {o.title}" if o else None
        elif why in ("stale", "today"):
            with session() as s:
                t = s.get(Task, ref); topic = t.title if t else None
        else:
            with session() as s:
                f = s.get(Fact, ref); topic = f.text if f else None
        if topic:
            mute(topic)
        return "Понял, про это больше не напоминаю."
    if action == "ok":
        return "Рад слышать, сэр."
    if action == "task":
        from . import tasks
        if why == "late":
            from .orders import order_view, get_order
            o = get_order(ref)
            if not o:
                return "Заказ не нашёл."
            v = order_view(o)
            due = (datetime.now() + timedelta(days=1)).replace(hour=11, minute=0, second=0, microsecond=0)
            t = tasks.add_task(f"Напомнить {v['client'] or 'клиенту'} про оплату «{o.title}»", due, source="proactive")
            return f"Задача «{t.title}» — завтра в 11:00."
        with session() as s:
            f = s.get(Fact, ref)
        if not f:
            return "Уже не актуально."
        title = re.sub(r"^\s*(он|она|хозяин|хозяйка)\s+", "", f.text, flags=re.I)
        t = tasks.add_task(title[0].upper() + title[1:], None, source="proactive")
        return f"Поставил задачу «{t.title}». Срок — скажете."
    return "Не понял кнопку."
