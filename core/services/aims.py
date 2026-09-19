"""Долгосрочные цели: цель → веха → задача. Не todo-лист: цель отвечает «зачем», веха — «что будет готово»,
задача — «что сделать сегодня». Прогресс считается, следующий шаг выбирается, закрытие задачи двигает веху.

Почему три уровня, а не семь из ТЗ (goal/area/project/milestone/subgoal/task/action): у одного человека пустые уровни
не заполняются и убивают систему. «Проект» здесь = веха (или заказ Order, привязанный к вехе). «Область» и «подцель»
не нужны: цель с 2–6 вехами и читается, и живёт.

API (всё синхронно, база — единственный источник):
  add_aim(title, why, due, priority) · add_milestone(aim, title, due, order_id) · link_task(task, aim=, milestone=)
  progress(aim) → 0..1 · aim_view(aim) → dict с вехами и задачами · list_aims()
  on_task_done(task) → {"aim", "milestone", "milestone_closed", "aim_ready", "next"} — зовётся из tasks.complete_task
  focus(now) → 1–3 действия на сегодня, которые двигают активные цели (см. правила внизу)
  text_focus() / text_aims() — для чата и утреннего дайджеста
  detect_aim_phrase(text) — «цель: …», «хочу за год …» → параметры для add_aim (правило агента)
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

from sqlmodel import select

from ..db import Aim, Milestone, Order, Task, log_action, now, remember, session
from . import events
from .match import score

log = logging.getLogger("marvin.aims")

STALE_DAYS = 7           # по цели ничего не закрывали столько дней → «давно не возвращался»
FOCUS_MAX = 3            # больше действий на день не даём — меньше задач, больше сделанных


# ----------------------------------------------------------------- CRUD
def add_aim(title: str, why: str = "", due: datetime | None = None, priority: int = 2, source: str = "web") -> Aim:
    title = (title or "").strip(" .«»\"'")
    if not title:
        raise ValueError("Нужно название цели")
    with session() as s:
        for a in s.exec(select(Aim).where(Aim.status == "active")).all():
            if a.title.strip().lower() == title.lower():
                return a
        a = Aim(title=title[0].upper() + title[1:], why=(why or "").strip(), due=due, priority=max(1, min(3, int(priority or 2))))
        s.add(a); s.commit(); s.refresh(a)
        remember(s, "aim", f"Цель: «{a.title}»" + (f" — {a.why}" if a.why else "") + (f", к {due:%d.%m.%Y}" if due else ""), "aim", a.id, source)
        log_action(s, "add_aim", "aim", a.id, a.title, source)
        s.commit()
        return a


def find_aim(query: str | int, any_status: bool = False) -> Aim | None:
    with session() as s:
        if isinstance(query, int) or str(query).isdigit():
            return s.get(Aim, int(query))
        q = select(Aim) if any_status else select(Aim).where(Aim.status.in_(("active", "paused")))   # type: ignore[attr-defined]
        rows = s.exec(q).all()
    best = max(((score(a.title, str(query)), a) for a in rows), key=lambda x: x[0], default=(0, None))
    return best[1] if best[0] >= 0.5 else None


def update_aim(aim_id: int, **fields) -> Aim | None:
    with session() as s:
        a = s.get(Aim, aim_id)
        if not a:
            return None
        for k in ("title", "why", "status", "priority", "due", "progress"):
            if k in fields and fields[k] is not None:
                setattr(a, k, fields[k])
        if a.status == "done" and not a.done_at:
            a.done_at = now()
        if "due" in fields and fields["due"] is None and "clear_due" in fields:
            a.due = None
        s.add(a); s.commit(); s.refresh(a)
        if fields.get("status") in ("done", "dropped", "paused"):
            remember(s, "aim", {"done": "Цель достигнута", "dropped": "Цель снята", "paused": "Цель на паузе"}[fields["status"]] + f": «{a.title}»", "aim", a.id)
            log_action(s, "close_aim", "aim", a.id, a.title, "web")
            s.commit()
        return a


def add_milestone(aim: Aim | int, title: str, due: datetime | None = None, order_id: int | None = None, notes: str = "") -> Milestone:
    aid = aim if isinstance(aim, int) else aim.id
    title = (title or "").strip(" .«»\"'")
    if not title:
        raise ValueError("Нужно название вехи")
    with session() as s:
        existing = s.exec(select(Milestone).where(Milestone.aim_id == aid)).all()
        for m in existing:
            if m.title.strip().lower() == title.lower():
                return m
        m = Milestone(aim_id=aid, title=title[0].upper() + title[1:], due=due, order_id=order_id, notes=notes or "",
                      order=max([x.order for x in existing], default=0) + 1)
        s.add(m); s.commit(); s.refresh(m)
        a = s.get(Aim, aid)
        remember(s, "aim", f"Веха «{m.title}» в цели «{a.title if a else aid}»", "milestone", m.id)
        s.commit()
        return m


def find_milestone(query: str, aim_id: int | None = None) -> Milestone | None:
    with session() as s:
        q = select(Milestone).where(Milestone.status == "open")
        if aim_id:
            q = q.where(Milestone.aim_id == aim_id)
        rows = s.exec(q).all()
    best = max(((score(m.title, query), m) for m in rows), key=lambda x: x[0], default=(0, None))
    return best[1] if best[0] >= 0.5 else None


def close_milestone(mid: int, status: str = "done") -> Milestone | None:
    with session() as s:
        m = s.get(Milestone, mid)
        if not m:
            return None
        m.status = status; m.done_at = now() if status == "done" else None
        s.add(m); s.commit(); s.refresh(m)
        return m


def link_task(task: Task | int, aim: Aim | int | None = None, milestone: Milestone | int | None = None) -> Task | None:
    tid = task if isinstance(task, int) else task.id
    with session() as s:
        t = s.get(Task, tid)
        if not t:
            return None
        if milestone is not None:
            mid = milestone if isinstance(milestone, int) else milestone.id
            m = s.get(Milestone, mid)
            if m:
                t.milestone_id = m.id; t.aim_id = m.aim_id
        elif aim is not None:
            t.aim_id = aim if isinstance(aim, int) else aim.id
        s.add(t); s.commit(); s.refresh(t)
        return t


def set_blocked(task_id: int, why: str) -> Task | None:
    with session() as s:
        t = s.get(Task, task_id)
        if not t:
            return None
        t.blocked_by = (why or "").strip()[:200]
        s.add(t); s.commit(); s.refresh(t)
        return t


# ----------------------------------------------------------------- прогресс и представление
def _tasks_of(s, aim_id: int | None = None, milestone_id: int | None = None) -> list[Task]:
    q = select(Task)
    if milestone_id is not None:
        q = q.where(Task.milestone_id == milestone_id)
    elif aim_id is not None:
        q = q.where(Task.aim_id == aim_id)
    return list(s.exec(q).all())


def milestone_progress(s, m: Milestone) -> float:
    if m.status == "done":
        return 1.0
    if m.order_id:
        o = s.get(Order, m.order_id)
        if o and o.status in ("done", "paid"):
            return 1.0
        if o and o.status in ("work", "review"):
            return 0.5
    ts = _tasks_of(s, milestone_id=m.id)
    return (sum(1 for t in ts if t.done) / len(ts)) if ts else 0.0


def progress(aim: Aim | int) -> float:
    aid = aim if isinstance(aim, int) else aim.id
    with session() as s:
        a = s.get(Aim, aid)
        if not a:
            return 0.0
        if a.status == "done":
            return 1.0
        ms = [m for m in s.exec(select(Milestone).where(Milestone.aim_id == aid)).all() if m.status != "dropped"]
        if ms:
            return round(sum(milestone_progress(s, m) for m in ms) / len(ms), 3)
        ts = [t for t in _tasks_of(s, aim_id=aid) if not t.milestone_id]
        if ts:
            return round(sum(1 for t in ts if t.done) / len(ts), 3)
        return float(a.progress or 0.0)


def aim_view(aim: Aim | int) -> dict | None:
    aid = aim if isinstance(aim, int) else aim.id
    with session() as s:
        a = s.get(Aim, aid)
        if not a:
            return None
        ms = sorted(s.exec(select(Milestone).where(Milestone.aim_id == aid)).all(), key=lambda m: (m.status == "done", m.order))
        out_ms = []
        for m in ms:
            ts = sorted(_tasks_of(s, milestone_id=m.id), key=lambda t: (t.done, t.due or datetime.max, t.id))
            order_title = None
            if m.order_id:
                o = s.get(Order, m.order_id)
                order_title = o.title if o else None
            out_ms.append({**m.model_dump(), "progress": milestone_progress(s, m), "order_title": order_title,
                           "tasks": [{"id": t.id, "title": t.title, "done": t.done, "due": t.due, "blocked_by": t.blocked_by} for t in ts],
                           "open": sum(1 for t in ts if not t.done)})
        loose = [t for t in _tasks_of(s, aim_id=aid) if not t.milestone_id]
        stale = (now() - (a.last_touch or a.created_at)).days if a.status == "active" else 0
        return {**a.model_dump(), "progress": progress(a), "milestones": out_ms,
                "tasks": [{"id": t.id, "title": t.title, "done": t.done, "due": t.due, "blocked_by": t.blocked_by} for t in sorted(loose, key=lambda t: (t.done, t.id))],
                "stale_days": stale, "days_left": (a.due.date() - now().date()).days if a.due else None}


def list_aims(include_closed: bool = False) -> list[dict]:
    with session() as s:
        rows = s.exec(select(Aim).order_by(Aim.priority, Aim.created_at)).all()
    return [v for a in rows if (include_closed or a.status in ("active", "paused")) and (v := aim_view(a))]


# ----------------------------------------------------------------- движение
def on_task_done(task: Task) -> dict | None:
    """Задача закрыта. Если она к чему-то привязана — сдвинуть веху/цель, вернуть что произошло и что дальше.
    Зовётся из tasks.complete_task; события шлёт сама (goal_step_done / milestone_done / aim_done)."""
    if not task or not (task.aim_id or task.milestone_id):
        return None
    out: dict = {"aim": None, "milestone": None, "milestone_closed": False, "aim_ready": False, "next": []}
    with session() as s:
        a = s.get(Aim, task.aim_id) if task.aim_id else None
        m = s.get(Milestone, task.milestone_id) if task.milestone_id else None
        if not a and m:
            a = s.get(Aim, m.aim_id)
        if not a:
            return None
        a.last_touch = now(); s.add(a)
        out["aim"] = a.title
        if m:
            out["milestone"] = m.title
            left = [t for t in _tasks_of(s, milestone_id=m.id) if not t.done]
            if not left and m.status == "open" and not m.order_id:
                m.status = "done"; m.done_at = now(); s.add(m)
                out["milestone_closed"] = True
        s.commit()
        # все вехи закрыты — цель НЕ закрываем сами (человек решает, достигнута ли она), но говорим об этом
        ms = [x for x in s.exec(select(Milestone).where(Milestone.aim_id == a.id)).all() if x.status != "dropped"]
        if ms and all(x.status == "done" for x in ms) and a.status == "active":
            out["aim_ready"] = True
        aim_title, aim_id = a.title, a.id
    out["next"] = next_actions(aim_id, limit=2)
    events.emit("goal_step_done", key=f"task:{task.id}", aim=aim_title, title=task.title, quiet=True)
    if out["milestone_closed"]:
        events.emit("milestone_done", key=f"ms:{task.milestone_id}", aim=aim_title, milestone=out["milestone"],
                    next=(out["next"][0]["title"] if out["next"] else ""))
    if out.get("aim_ready"):
        events.emit("aim_ready", key=f"aim:{aim_id}", dedup_sec=86400, aim=aim_title)
    return out


def close_aim(aim: Aim | int, status: str = "done") -> Aim | None:
    """«цель X достигнута» / «закрой цель X» / «цель X — отбой». Событие aim_done только при достижении."""
    a = update_aim(aim if isinstance(aim, int) else aim.id, status=status)
    if a and status == "done":
        events.emit("aim_done", key=f"aim:{a.id}", aim=a.title)
    return a


AIM_CLOSE_RX = re.compile(r"^\s*(?:цель\s+[«\"]?(.+?)[»\"]?\s+(достигнута|выполнена|закрыта|сделана|отбой|отменяется|больше не актуальна)|(?:закрой|закрыть|убери|отмени)\s+цель\s+[«\"]?(.+?)[»\"]?)\s*[.!]?\s*$", re.I)


def next_actions(aim_id: int, limit: int = 3) -> list[dict]:
    """Что логично дальше по цели: незаблокированные открытые задачи первой незакрытой вехи (по сроку, потом по возрасту);
    если вех нет — свободные задачи цели; если и задач нет — «поставить следующую веху/задачу»."""
    with session() as s:
        ms = sorted([m for m in s.exec(select(Milestone).where(Milestone.aim_id == aim_id, Milestone.status == "open")).all()],
                    key=lambda m: (m.due or datetime.max, m.order))
        picks: list[dict] = []
        for m in ms:
            ts = [t for t in _tasks_of(s, milestone_id=m.id) if not t.done]
            ts.sort(key=lambda t: (bool(t.blocked_by), t.due or datetime.max, t.priority, t.id))
            for t in ts:
                picks.append({"task_id": t.id, "title": t.title, "milestone": m.title, "due": t.due, "blocked_by": t.blocked_by})
                if len(picks) >= limit:
                    return picks
            if ts:
                break   # следующая веха — после текущей
            picks.append({"task_id": None, "title": f"Разбить веху «{m.title}» на 1–3 задачи", "milestone": m.title, "due": m.due, "blocked_by": ""})
            return picks[:limit]
        loose = [t for t in _tasks_of(s, aim_id=aim_id) if not t.done and not t.milestone_id]
        loose.sort(key=lambda t: (bool(t.blocked_by), t.due or datetime.max, t.priority, t.id))
        for t in loose[:limit - len(picks)]:
            picks.append({"task_id": t.id, "title": t.title, "milestone": None, "due": t.due, "blocked_by": t.blocked_by})
        if not picks:
            a = s.get(Aim, aim_id)
            picks.append({"task_id": None, "title": f"Поставить первую веху для «{a.title if a else 'цели'}»", "milestone": None, "due": None, "blocked_by": ""})
        return picks


# ----------------------------------------------------------------- фокус дня
def focus(now_: datetime | None = None, limit: int = FOCUS_MAX) -> dict:
    """1–3 действия на сегодня, которые двигают цели. Порядок:
    1) задачи целей с дедлайном сегодня/просроченные; 2) главная цель (priority 1) — её следующий шаг;
    3) остальные активные цели по очереди — по одному шагу, сначала та, к которой дольше не возвращались.
    Заблокированные задачи не предлагаются — отдельным списком «что мешает». Пусто — если целей нет."""
    now_ = now_ or now()
    with session() as s:
        aims = sorted(s.exec(select(Aim).where(Aim.status == "active")).all(), key=lambda a: (a.priority, a.last_touch or a.created_at))
        if not aims:
            return {"items": [], "blocked": [], "aims": 0}
        picks: list[dict] = []
        seen: set[int] = set()
        blocked: list[dict] = []
        aim_title = {a.id: a.title for a in aims}
        # 1) горящие
        for t in s.exec(select(Task).where(Task.done == False, Task.aim_id != None, Task.due != None)).all():  # noqa: E711,E712
            if t.due.date() <= now_.date() and t.aim_id in aim_title:
                if t.blocked_by:
                    blocked.append({"task_id": t.id, "title": t.title, "aim": aim_title[t.aim_id], "blocked_by": t.blocked_by})
                    continue
                picks.append({"task_id": t.id, "title": t.title, "aim": aim_title[t.aim_id], "why": "срок сегодня" if t.due.date() == now_.date() else "просрочено", "due": t.due})
                seen.add(t.id)
        picks.sort(key=lambda p: p["due"])
        # 2–3) по одному шагу на цель
        for a in aims:
            if len(picks) >= limit:
                break
            for n in next_actions(a.id, limit=3):
                if n["task_id"] in seen:
                    continue
                if n["blocked_by"]:
                    blocked.append({"task_id": n["task_id"], "title": n["title"], "aim": a.title, "blocked_by": n["blocked_by"]})
                    continue
                picks.append({"task_id": n["task_id"], "title": n["title"], "aim": a.title, "why": n["milestone"] or ("главная цель" if a.priority == 1 else "цель"), "due": n["due"]})
                if n["task_id"]:
                    seen.add(n["task_id"])
                break
        return {"items": picks[:limit], "blocked": blocked[:3], "aims": len(aims)}


def stale_aims(days: int = STALE_DAYS) -> list[Aim]:
    """Активные цели, по которым ничего не закрывали ≥ days (для инициативы «давно не возвращался»)."""
    cutoff = now() - timedelta(days=days)
    with session() as s:
        return [a for a in s.exec(select(Aim).where(Aim.status == "active")).all() if (a.last_touch or a.created_at) <= cutoff]


# ----------------------------------------------------------------- текст
def _fmt_due(d: datetime | None) -> str:
    if not d:
        return ""
    days = (d.date() - now().date()).days
    return " — сегодня" if days == 0 else (f" — просрочено на {-days} дн." if days < 0 else f" — до {d:%d.%m}")


def text_focus(now_: datetime | None = None) -> str:
    f = focus(now_)
    if not f["aims"]:
        return "Долгосрочных целей пока нет. Скажите «цель: …» — и я начну подбирать, что делать сегодня, от неё, а не от списка дел."
    if not f["items"] and not f["blocked"]:
        return "По целям всё, что можно, сделано. Поставьте следующую веху — или просто отдыхайте."
    lines = ["Фокус дня:"]
    for i, p in enumerate(f["items"], 1):
        if p["task_id"] is None:
            lines.append(f"{i}. {p['title']} — скажите «веха: …» или «задача: … к цели {p['aim'][:20]}»")
            continue
        lines.append(f"{i}. {p['title']}{_fmt_due(p['due'])}  ·  {p['aim']}" + (f" / {p['why']}" if p["why"] and p["why"] not in ("цель", "главная цель") else ""))
    if not f["items"]:
        lines.append("свободных шагов нет — всё упирается в чужие ответы.")
    if f["blocked"]:
        lines.append("Мешает: " + "; ".join(f"«{b['title']}» — {b['blocked_by']}" for b in f["blocked"]))
    return "\n".join(lines)


def text_aims() -> str:
    views = list_aims()
    if not views:
        return "Целей нет. «Цель: устойчивая карьера монтажёра, потому что хочу выбирать заказы» — так и заводится."
    lines = []
    for v in views:
        pct = int(round(v["progress"] * 100))
        ms_open = [m for m in v["milestones"] if m["status"] == "open"]
        head = f"• {v['title']} — {pct}%" + (f", к {datetime.fromisoformat(str(v['due'])):%d.%m.%Y}" if v["due"] else "") + (" (пауза)" if v["status"] == "paused" else "")
        lines.append(head)
        if ms_open:
            m = ms_open[0]
            lines.append(f"   сейчас: веха «{m['title']}» ({int(round(m['progress'] * 100))}%, открыто задач: {m['open']})")
        if v["stale_days"] >= STALE_DAYS and v["status"] == "active":
            lines.append(f"   ⚠ ничего не двигалось {v['stale_days']} дн." + (f" Зачем это было: {v['why']}" if v["why"] else ""))
    return "\n".join(lines)


# ----------------------------------------------------------------- разбор фраз
AIM_RX = re.compile(r"^\s*(?:моя\s+)?(?!цель\s+на\s+(?:сегодня|завтра|день|неделю))(?:цель|большая цель|долгосрочная цель|хочу (за (?:год|полгода|месяц|\d+\s*(?:мес\w*|год\w*|лет))))\s*[:\-—]?\s*(.+)$", re.I | re.S)
WHY_RX = re.compile(r"\s*[,—\-]?\s*\b(?:потому что|чтобы|так как|зачем:|почему:)\s*(.+)$", re.I | re.S)
MS_RX = re.compile(r"^\s*(?:веха|этап|milestone)\s*[:\-—]?\s*(.+?)(?:\s+(?:в|для|к)\s+цел[иь]\s+(.+))?$", re.I | re.S)
FOCUS_RX = re.compile(r"^\s*(?:что\s+(?:мне\s+)?(?:сегодня\s+)?(?:делать|сделать)(?:\s+сегодня)?|фокус(?:\s+дня)?|план на сегодня по целям|чем заняться|что важно сегодня)\s*\??\s*$", re.I)
AIMS_RX = re.compile(r"^\s*(?:мои\s+)?(?:цели|долгосрочные цели|как (?:дела|прогресс) (?:по|с) цел\w*|прогресс по целям|что с целями)\s*\??\s*$", re.I)
BLOCK_RX = re.compile(r"^\s*(?:задача\s+)?[«\"]?(.+?)[»\"]?\s+(?:заблокирован\w*|застряла|стоит|не могу сделать|мешает)\s*[:\-—,]?\s*(.+)$", re.I | re.S)


def detect_aim_phrase(text: str) -> dict | None:
    m = AIM_RX.match(text or "")
    if not m:
        return None
    body = m.group(2).strip() + (f" {m.group(1)}" if m.group(1) else "")
    why = ""
    w = WHY_RX.search(body)
    if w:
        why = w.group(1).strip(" .")
        body = body[:w.start()].strip(" ,.-—")
    if len(body) < 4 or len(body) > 120:
        return None
    due, title = aim_due(body)
    return {"title": title or body, "why": why, "due": due}


_MONTHS = {"январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12}
_MONTH_RX = re.compile(r"\s*(?:к|до|на)\s+(январ|феврал|март|апрел|ма|июн|июл|август|сентябр|октябр|ноябр|декабр)(?:ю|я|а|е|у|та|ту|й|ю)\b\.?", re.I)
_END_RX = re.compile(r"\s*(?:к|до)\s+конц[ау]\s+(года|месяца|лета|осени|зимы|весны)\b\.?", re.I)
_SPAN_RX = re.compile(r"\s*за\s+(полгода|год|месяц|(\d+)\s*(?:мес\w*|недел\w*|дн\w*))\b\.?", re.I)
_DAY_RX = re.compile(r"\b(?:к|до)\s+\d{1,2}(?:\s+[а-я]+|[./]\d{1,2})", re.I)


def aim_due(body: str, now_: datetime | None = None) -> tuple[datetime | None, str]:
    """Срок цели — это месяцы, а не «завтра в 17:00»: «к декабрю», «до конца года», «за полгода», «к 1 декабря».
    Общий parse_datetime тут не годится — он из «похудеть на 5 кг» делает «в 5 часов». Возвращает (срок, текст без срока)."""
    now_ = now_ or now()
    m = _MONTH_RX.search(body)
    if m:
        mon = _MONTHS[m.group(1).lower()]
        year = now_.year + (1 if mon <= now_.month else 0)
        first = datetime(year, mon, 1)
        return first, (body[:m.start()] + body[m.end():]).strip(" ,.-—")
    m = _END_RX.search(body)
    if m:
        w = m.group(1).lower()
        if w == "года":
            due = datetime(now_.year, 12, 31)
        elif w == "месяца":
            nxt = (now_.replace(day=28) + timedelta(days=4)).replace(day=1)
            due = nxt - timedelta(days=1)
        else:
            end_month = {"зимы": 2, "весны": 5, "лета": 8, "осени": 11}[w]
            year = now_.year + (1 if end_month < now_.month or (w == "зимы" and now_.month == 12) else 0)
            due = datetime(year, end_month, 28)
        return due.replace(hour=0, minute=0), (body[:m.start()] + body[m.end():]).strip(" ,.-—")
    m = _SPAN_RX.search(body)
    if m:
        word = m.group(1).lower()
        n = int(m.group(2)) if m.group(2) else 0
        if word == "полгода":
            days = 182
        elif word == "год":
            days = 365
        elif word == "месяц":
            days = 30
        elif "недел" in word:
            days = 7 * n
        elif "дн" in word:
            days = n
        else:
            days = 30 * n
        return (now_ + timedelta(days=days)).replace(hour=0, minute=0, second=0, microsecond=0), (body[:m.start()] + body[m.end():]).strip(" ,.-—")
    if _DAY_RX.search(body):
        from ..brain.dates import parse_datetime
        due, rest = parse_datetime(body)
        if due:
            return due.replace(hour=0, minute=0), (rest or body).strip(" ,.-—")
    return None, body


LINK_RX = re.compile(r"\s*[,—-]?\s*(?:к|для|по|в рамках)\s+(цел[иь]|вехе|этапу)\s+[«\"]?(.+?)[»\"]?\s*$", re.I)


def split_link(body: str) -> tuple[str, dict]:
    """«сделать сцену кухни к вехе портфолио» → («сделать сцену кухни», {milestone: <Milestone>}) /
    «… к цели заказы» → ({aim: <Aim>}). Ничего не нашли по имени — хвост остаётся в названии, ссылки нет."""
    m = LINK_RX.search(body)
    if not m:
        return body, {}
    kind, name = m.group(1).lower(), m.group(2).strip()
    if kind.startswith("цел"):
        a = find_aim(name)
        return (body[:m.start()].strip(), {"aim": a}) if a else (body, {})
    ms = find_milestone(name)
    return (body[:m.start()].strip(), {"milestone": ms}) if ms else (body, {})


def attach_hint(task: Task, link: dict) -> str:
    """Привязать задачу по результату split_link и вернуть хвост для ответа."""
    if link.get("milestone"):
        link_task(task, milestone=link["milestone"])
        return f" — к вехе «{link['milestone'].title}»."
    if link.get("aim"):
        link_task(task, aim=link["aim"])
        return f" — к цели «{link['aim'].title}»."
    return ""
