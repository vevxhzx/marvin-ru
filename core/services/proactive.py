"""Инициативные сообщения: ассистент сам пишет о том, что заметил в базе, — когда сочтёт нужным, но не чаще N раз в день.

Что замечает (кандидаты, все считаются локально по базе):
- клиент задерживает оплату (режим фрилансера, pulse.late_payments);
- дело без срока висит дольше STALE_TASK_DAYS дней;
- дедлайн задачи сегодня, а времени в нём нет (легко забыть);
- «сейчас»-факт про самочувствие старше 2 дней → «как самочувствие?»;
- «сейчас»-факт про дело/план без задачи → «поставить задачу?».

Правила: тихие часы (notifications.quiet_*), лимит notifications.proactive_per_day, каждый повод — один раз
(ключ в Setting), кнопка «🔕 не надо про это» = Lesson(kind="mute") — тема больше не всплывает.
Формулировка — persona.nudge: факт (JSON) → облако/ПК по persona.where в характере ассистента; без них — шаблон persona.nudge_fallback. Никаких действий без сообщения:
всё, что предлагает, делается только по кнопке.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from sqlmodel import select

from ..brain import persona
from ..config import cfg
from ..db import Fact, Task, get_setting, session, set_setting
from . import judge

log = logging.getLogger("assistant.proactive")

STALE_TASK_DAYS = 5
HEALTH_RX = re.compile(r"болe|боле|просту|температур|давлени|самочувств|лечит|таблетк|врач|плохо\s+себя|устал|не\s+спал|бессонниц", re.I)
PLAN_RX = re.compile(r"\b(надо|нужно|собирается|планирует|хочет|думает)\s+\w+", re.I)
COUNT_KEY = "proactive.count"   # "YYYY-MM-DD|n"

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
                            "fact": {"kind": "late_pay", "client": who, "title": x["title"], "amount": money(x["left"]), "days": x["days"],
                                     "urgency": "high" if x["days"] >= 14 else "normal", "question": "напомнить ему?"},
                            "text": persona.nudge_fallback("late_pay", who=who, money=money(x["left"]), title=x["title"], days=x["days"]),
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
                    "fact": {"kind": "stale_task", "title": t.title, "days": days, "deadline": None, "urgency": "low",
                             "question": "поставить срок, сделать или отпустить?"},
                    "text": persona.nudge_fallback("stale_task", title=t.title, days=days),
                    "buttons": [("📅 Завтра", f"task:{t.id}:tomorrow"), ("✅ Сделал", f"task:{t.id}:done"), ("🔕 Не надо", f"pro:mute:{t.id}:stale")]})
    today_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
    # утренний дайджест уже перечислил дела на день — повторять их отдельным сообщением незачем; повод остаётся только
    # для тех, у кого дайджест выключен
    digest_on = bool((getattr(cfg.telegram, "morning_digest", "") or "").strip())
    day_tasks = [] if digest_on else [t for t in open_tasks if t.due and t.due.date() == now.date() and t.due.hour == 23 and t.due.minute == 59 and now < today_noon]
    if len(day_tasks) == 1:
        t = day_tasks[0]
        out.append({"key": f"today:{t.id}:{now:%Y%m%d}", "topic": t.title,
                    "fact": {"kind": "today_task", "title": t.title, "deadline": "сегодня, без времени", "urgency": "normal"},
                    "text": persona.nudge_fallback("today_task", title=t.title),
                    "buttons": [("✅ Сделал", f"task:{t.id}:done"), ("📅 Завтра", f"task:{t.id}:tomorrow"), ("🔕 Не надо", f"pro:mute:{t.id}:today")]})
    elif day_tasks:
        # несколько дел на день — одно сообщение списком (а не по сообщению в час на каждое); ключ — на день, темы — все названия
        titles = ", ".join(f"«{t.title}»" for t in day_tasks[:5]) + (f" и ещё {len(day_tasks) - 5}" if len(day_tasks) > 5 else "")
        out.append({"key": f"today:0:{now:%Y%m%d}", "topic": " ".join(t.title for t in day_tasks),
                    "fact": {"kind": "today_many", "titles": [t.title for t in day_tasks[:5]], "deadline": "сегодня, без времени", "urgency": "normal"},
                    "text": persona.nudge_fallback("today_many", titles=titles), "buttons": []})
    # 2б. цели: стоит без движения (STALE_DAYS) — один повод, редко (ключ на неделю); рутины: ≥2 пропуска подряд
    try:
        from . import aims, routines
        for a in aims.stale_aims()[:1]:
            days = (now - (a.last_touch or a.created_at)).days
            out.append({"key": f"aim_stale:{a.id}:{now:%Y%W}", "topic": a.title,
                        "fact": {"kind": "aim_stale", "title": a.title, "days": days, "why": a.why, "urgency": "low",
                                 "question": "шаг, пауза или закрыть?"},
                        "text": f"«{a.title}» стоит {days} дн. без единого шага." + (f" Ты хотел её, потому что {a.why}." if a.why else "") + " Шаг, пауза или закрываем?",
                        "buttons": [("⏸ Пауза", f"aim:{a.id}:pause"), ("✖ Снять", f"aim:{a.id}:drop"), ("🔕 Не надо", f"pro:mute:{a.id}:aim")]})
        for r in ([] if muted("рутины: пропуски") else routines.nudges(now)[:1]):
            out.append({"key": r["key"], "topic": r["title"],
                        "fact": {"kind": "routine_missed", "title": r["title"], "missed": r["missed"], "urgency": "low", "question": "привычка сломалась?"},
                        "text": r["text"], "buttons": [("🔕 Не надо", f"pro:mute:0:routine")]})
    except Exception as e:  # pragma: no cover
        log.debug("aims/routines candidates: %s", e)
    # 3. факты «сейчас»: самочувствие и планы без задачи
    with session() as s:
        short = list(s.exec(select(Fact).where(Fact.layer == "short")))
    titles = " ".join(t.title.lower() for t in open_tasks)
    for f in short:
        age = (now - f.created_at).days
        if HEALTH_RX.search(f.text) and 2 <= age <= 7:
            out.append({"key": f"health:{f.id}", "topic": f.text,
                        "fact": {"kind": "health", "text": f.text, "days": age, "urgency": "low", "question": "как самочувствие?"},
                        "text": persona.nudge_fallback("health", text=f.text),
                        "buttons": [("👍 Норм", f"pro:ok:{f.id}:health"), ("🔕 Не надо", f"pro:mute:{f.id}:health")]})
        elif PLAN_RX.search(f.text) and 1 <= age <= 5:
            words = judge._words(f.text)
            if words and not any(w in titles for w in words if len(w) >= 5):
                out.append({"key": f"plan:{f.id}", "topic": f.text,
                            "fact": {"kind": "plan", "text": f.text, "days": age, "urgency": "low", "question": "поставить задачу?"},
                            "text": persona.nudge_fallback("plan", text=f.text),
                            "buttons": [("✍️ Поставить задачу", f"pro:task:{f.id}:plan"), ("🔕 Не надо", f"pro:mute:{f.id}:plan")]})
    # 3b. экранное время: YouTube час подряд при дедлайне, игра в рабочее время, 6 ч без перерыва — не чаще раза в 3 часа
    try:
        from . import screen
        last_screen = get_setting("proactive.screen_at", "")
        if not last_screen or (now - datetime.fromisoformat(last_screen)).total_seconds() >= 3 * 3600:
            out.extend(screen.nudge_facts(now))
    except Exception as e:  # pragma: no cover
        log.debug("screen nudges: %s", e)
    out = [c for c in out if not _sent(c["key"]) and not muted(c["topic"])]
    # 4. просто написать: поводов по делам нет, а в чате тихо с утра (VIBE_SILENT_H часов) — спросить как дела / пошутить.
    # Раз в день, только днём (11–20), только когда есть кому формулировать (без облака/ПК шаблон быстро приестся).
    if not out and vibe_enabled() and 11 <= now.hour < 20:
        last = _last_chat_at()
        silent_h = (now - last).total_seconds() / 3600 if last else 99
        if silent_h >= VIBE_SILENT_H:
            out.append({"key": f"vibe:{now:%Y%m%d}", "topic": "просто поболтать",
                        "fact": {"kind": "vibe", "hours_silent": int(silent_h), "weekday": persona._DAYS.get(now.strftime("%A"), ""),
                                 "time": f"{now:%H:%M}", "urgency": "low"},
                        "text": persona.nudge_fallback("vibe"),
                        "buttons": [("🔕 Не надо так", "pro:mute:0:vibe")]})
    return [c for c in out if not _sent(c["key"]) and not muted(c["topic"])]


VIBE_SILENT_H = 5


def vibe_enabled() -> bool:
    n = getattr(cfg, "notifications", None)
    return bool(getattr(n, "proactive_vibe", True)) if n is not None else True


def _last_chat_at() -> datetime | None:
    from ..db import ChatMessage
    with session() as s:
        row = s.exec(select(ChatMessage).order_by(ChatMessage.id.desc())).first()
    return row.created_at if row else None


# ---------------------------------------------------------------- формулировка
async def phrase(c: dict) -> str:
    """Голос персоны по факту (persona.nudge); сбой, пустой или казённый ответ — шаблон из кандидата."""
    fact = c.get("fact")
    if not fact:
        return c["text"]
    try:
        return await persona.nudge(fact, c["text"])
    except Exception as e:  # pragma: no cover
        log.debug("phrase: %s", e)
        return c["text"]


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
    c["text"] = await phrase(c)
    _mark(c["key"]); _bump()
    if c["key"].startswith("screen:"):
        set_setting("proactive.screen_at", (now or datetime.now()).isoformat())
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
        elif why == "vibe":
            # «не надо так» под болтовнёй — выключаем её совсем, не по теме (темы у неё нет)
            from ..config import save_settings
            save_settings({"notifications.proactive_vibe": False})
            return "Понял: без болтовни, только по делу."
        elif why == "screen":
            # подколы про экранное время — выключаем все разом (учёт продолжается, карточка и вечерняя строка остаются)
            from ..config import save_settings
            save_settings({"voice.pc.screen_time.nudges": False})
            return "Понял: про время за ПК больше не подкалываю. Считать продолжаю — карточка на «Сегодня» остаётся."
        elif why == "aim":
            from . import aims
            a = aims.find_aim(ref); topic = a.title if a else None
        elif why == "routine":
            return "Понял: про пропуски рутин не напоминаю (серии считать продолжаю — «мои рутины»)." if not mute("рутины: пропуски") else "Понял."
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
