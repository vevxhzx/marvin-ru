"""Экранное время: сколько и где хозяин сидит за ПК.

Источник — пульс ПК-клиента (voice.bat) раз в 20 с: активная программа, заголовок окна, простой мыши/клавиатуры.
Ядро склеивает соседние пульсы с той же программой в отрезки ScreenSlot; простой ≥ idle_min минут — отрезок idle
(«отошёл»). Из idle-отрезков считаются сессии «сел / ушёл». Всё локально, в облако не уходит ничего: в проактивные
подколы попадают только имя программы, сайт и минуты.

Категории: работа (монтаж/графика/код), браузер (сайт отдельно), общение, игра, медиа, прочее.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta

from sqlmodel import select

from ..config import cfg
from ..db import ScreenSlot, session

log = logging.getLogger("assistant.screen")

# --------------------------------------------------------------- настройки
def _node():
    pc = getattr(getattr(cfg, "voice", None), "pc", None)
    return getattr(pc, "screen_time", None) if pc is not None else None


def enabled() -> bool:
    n = _node()
    return bool(getattr(n, "enabled", False)) if n is not None else False


def idle_min() -> int:
    n = _node()
    try:
        return max(1, int(getattr(n, "idle_min", 5) or 5))
    except (TypeError, ValueError):
        return 5


def nudges_enabled() -> bool:
    n = _node()
    return bool(getattr(n, "nudges", True)) if n is not None else True


def keep_days() -> int:
    n = _node()
    try:
        return max(7, int(getattr(n, "keep_days", 90) or 90))
    except (TypeError, ValueError):
        return 90


# --------------------------------------------------------------- программы → имя и категория
APPS = {
    # работа
    "adobe premiere pro.exe": ("Premiere Pro", "работа"), "premiere pro.exe": ("Premiere Pro", "работа"), "afterfx.exe": ("After Effects", "работа"),
    "adobe media encoder.exe": ("Media Encoder", "работа"), "davinci resolve.exe": ("DaVinci Resolve", "работа"), "resolve.exe": ("DaVinci Resolve", "работа"),
    "photoshop.exe": ("Photoshop", "работа"), "illustrator.exe": ("Illustrator", "работа"), "figma.exe": ("Figma", "работа"),
    "blender.exe": ("Blender", "работа"), "cinema 4d.exe": ("Cinema 4D", "работа"), "obs64.exe": ("OBS", "работа"), "audition.exe": ("Audition", "работа"),
    "code.exe": ("VS Code", "работа"), "cursor.exe": ("Cursor", "работа"), "pycharm64.exe": ("PyCharm", "работа"), "windowsterminal.exe": ("Терминал", "работа"),
    "cmd.exe": ("Терминал", "работа"), "powershell.exe": ("Терминал", "работа"), "excel.exe": ("Excel", "работа"), "winword.exe": ("Word", "работа"),
    "notion.exe": ("Notion", "работа"), "obsidian.exe": ("Obsidian", "работа"), "capcut.exe": ("CapCut", "работа"),
    # общение
    "telegram.exe": ("Telegram", "общение"), "discord.exe": ("Discord", "общение"), "whatsapp.exe": ("WhatsApp", "общение"),
    "zoom.exe": ("Zoom", "общение"), "teams.exe": ("Teams", "общение"), "ms-teams.exe": ("Teams", "общение"), "slack.exe": ("Slack", "общение"), "viber.exe": ("Viber", "общение"),
    # медиа
    "spotify.exe": ("Spotify", "медиа"), "vlc.exe": ("VLC", "медиа"), "mpc-hc64.exe": ("Плеер", "медиа"), "potplayermini64.exe": ("Плеер", "медиа"),
    "yandexmusic.exe": ("Яндекс Музыка", "медиа"),
    # браузеры (сайт определяется по заголовку)
    "chrome.exe": ("Chrome", "браузер"), "msedge.exe": ("Edge", "браузер"), "firefox.exe": ("Firefox", "браузер"), "brave.exe": ("Brave", "браузер"),
    "opera.exe": ("Opera", "браузер"), "opera_gx.exe": ("Opera GX", "браузер"), "browser.exe": ("Яндекс Браузер", "браузер"), "vivaldi.exe": ("Vivaldi", "браузер"), "arc.exe": ("Arc", "браузер"),
    # системное
    "explorer.exe": ("Проводник", "прочее"), "lockapp.exe": ("Экран блокировки", "прочее"), "searchhost.exe": ("Поиск Windows", "прочее"),
    "steam.exe": ("Steam", "игра"), "steamwebhelper.exe": ("Steam", "игра"), "epicgameslauncher.exe": ("Epic Games", "игра"),
}
BROWSERS = {k for k, v in APPS.items() if v[1] == "браузер"}

# сайты по хвосту заголовка браузера: «Видео — YouTube — Google Chrome»
SITES = [
    (re.compile(r"youtube|ютуб", re.I), "YouTube", "медиа"), (re.compile(r"twitch", re.I), "Twitch", "медиа"),
    (re.compile(r"кинопоиск|kinopoisk|netflix|okko|ivi\b", re.I), "Кино", "медиа"), (re.compile(r"vk video|vk\.com/video", re.I), "VK Видео", "медиа"),
    (re.compile(r"telegram|web\.telegram", re.I), "Telegram Web", "общение"), (re.compile(r"вконтакте|vk\.com|\bvk\b", re.I), "ВКонтакте", "общение"),
    (re.compile(r"whatsapp", re.I), "WhatsApp Web", "общение"), (re.compile(r"discord", re.I), "Discord", "общение"),
    (re.compile(r"instagram", re.I), "Instagram", "общение"), (re.compile(r"tiktok", re.I), "TikTok", "медиа"), (re.compile(r"reddit", re.I), "Reddit", "медиа"),
    (re.compile(r"chatgpt|openai|claude|gemini|deepseek|perplexity", re.I), "Нейросети", "работа"),
    (re.compile(r"github|gitlab|stack overflow|stackoverflow", re.I), "GitHub", "работа"),
    (re.compile(r"figma", re.I), "Figma", "работа"), (re.compile(r"notion", re.I), "Notion", "работа"),
    (re.compile(r"google (docs|sheets|slides|документы|таблицы)|docs\.google", re.I), "Google Docs", "работа"),
    (re.compile(r"gmail|почта|mail\.ru|yandex\.mail|яндекс почта", re.I), "Почта", "работа"),
    (re.compile(r"avito|авито|ozon|озон|wildberries|яндекс маркет|aliexpress", re.I), "Магазины", "прочее"),
    (re.compile(r"habr|хабр|vc\.ru|dtf", re.I), "Хабр/VC", "медиа"),
    (re.compile(r"envato|motion array|artlist|epidemic sound|storyblocks|freepik|pexels|unsplash", re.I), "Стоки", "работа"),
    (re.compile(r"kwork|fl\.ru|upwork|freelance|хабр фриланс|profi\.ru", re.I), "Биржи", "работа"),
]


def classify(app: str, title: str, games: set[str] | None = None) -> tuple[str, str, str]:
    """(отображаемое имя, подпись/сайт, категория)."""
    app = (app or "").lower().strip()
    title = (title or "").strip()
    if not app:
        return "Неизвестно", "", "прочее"
    if games and app in games:
        return app.removesuffix(".exe").title(), "", "игра"
    name, cat = APPS.get(app, (app.removesuffix(".exe").replace("-", " ").title(), "прочее"))
    if app in BROWSERS:
        for rx, site, scat in SITES:
            if rx.search(title):
                return site, name, scat
        # неизвестный сайт: берём последний осмысленный кусок заголовка до имени браузера
        parts = [p.strip() for p in re.split(r"\s[—–-]\s", title) if p.strip()]
        site = parts[-2] if len(parts) >= 2 else (parts[0] if parts else "")
        return (site[:40] or name), name, "браузер"
    return name, "", cat


# --------------------------------------------------------------- приём пульса
_last: dict = {}   # последний принятый пульс: {"at": datetime, "app": str}

_GAMES: set[str] = set()


def set_games(games: set[str]) -> None:
    global _GAMES
    _GAMES = {g.lower() for g in games}


def record(app: str, title: str, idle_sec: int, now: datetime | None = None, step: int = 20) -> ScreenSlot | None:
    """Один пульс с ПК. Склеиваем с последним отрезком, если та же программа/сайт и прошло не больше 2 шагов."""
    if not enabled():
        return None
    now = now or datetime.now()
    idle = idle_sec >= idle_min() * 60
    if idle:
        name, sub, cat = "Отошёл", "", "простой"
    else:
        name, sub, cat = classify(app, title, _GAMES)
    with session() as s:
        last = s.exec(select(ScreenSlot).order_by(ScreenSlot.id.desc())).first()
        gap = (now - last.end).total_seconds() if last else 1e9
        if last and gap <= step * 2.5 and last.app == name and last.title == sub and last.idle == idle:
            last.end = now
            s.add(last); s.commit(); s.refresh(last)
            return last
        if last and gap <= step * 2.5:
            last.end = now - timedelta(seconds=step / 2)   # дотягиваем предыдущий до середины паузы
            s.add(last)
        # простой начался не сейчас, а idle_sec назад: отрезок «отошёл» стартует с последнего движения мыши
        start = now - timedelta(seconds=idle_sec) if idle and last is None else (now - timedelta(seconds=step / 2))
        if idle and last is not None and not last.idle:
            start = max(last.start + timedelta(seconds=1), now - timedelta(seconds=idle_sec))
            last.end = min(last.end, start)
            s.add(last)
        slot = ScreenSlot(start=start, end=now, app=name, title=sub, category=cat, idle=idle)
        s.add(slot); s.commit(); s.refresh(slot)
        return slot


def cleanup() -> int:
    """Старше keep_days — удалить (личные заголовки окон не должны лежать вечно)."""
    cutoff = datetime.now() - timedelta(days=keep_days())
    with session() as s:
        old = list(s.exec(select(ScreenSlot).where(ScreenSlot.end < cutoff)))
        for r in old:
            s.delete(r)
        s.commit()
    return len(old)


# --------------------------------------------------------------- отчёты
def _day_bounds(day: datetime | None = None) -> tuple[datetime, datetime]:
    d = (day or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    return d, d + timedelta(days=1)


def slots(day: datetime | None = None, days: int = 1) -> list[ScreenSlot]:
    d0, _ = _day_bounds(day)
    d1 = d0 + timedelta(days=days)
    with session() as s:
        return list(s.exec(select(ScreenSlot).where(ScreenSlot.end > d0, ScreenSlot.start < d1).order_by(ScreenSlot.start)))


def summary(day: datetime | None = None, days: int = 1) -> dict:
    """{'total_min', 'active_min', 'idle_min', 'apps': [(name, min, cat, sub)], 'cats': {cat: min}, 'sessions': [(start, end)],
    'first', 'last', 'hours': [min активных по часам 0..23]}"""
    d0, _ = _day_bounds(day)
    d1 = d0 + timedelta(days=days)
    rows = slots(day, days)
    apps: dict[tuple[str, str, str], float] = defaultdict(float)
    cats: dict[str, float] = defaultdict(float)
    hours = [0.0] * 24
    hour_cats: list[dict[str, float]] = [defaultdict(float) for _ in range(24)]
    active = idle = 0.0
    first = last = None
    for r in rows:
        a, b = max(r.start, d0), min(r.end, d1)
        mins = max(0.0, (b - a).total_seconds() / 60)
        if r.idle:
            idle += mins
            continue
        active += mins
        first = first or a
        last = b
        apps[(r.app, r.title, r.category)] += mins
        cats[r.category] += mins
        # по часам (для полоски дня)
        cur = a
        while cur < b:
            nxt = min(b, (cur + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0))
            hours[cur.hour] += (nxt - cur).total_seconds() / 60
            hour_cats[cur.hour][r.category] += (nxt - cur).total_seconds() / 60
            cur = nxt
    # сессии «сел/ушёл»: непрерывные куски активности с разрывами < idle_min
    sessions: list[tuple[datetime, datetime]] = []
    for r in rows:
        if r.idle:
            continue
        a, b = max(r.start, d0), min(r.end, d1)
        if sessions and (a - sessions[-1][1]).total_seconds() <= idle_min() * 60:
            sessions[-1] = (sessions[-1][0], max(sessions[-1][1], b))
        else:
            sessions.append((a, b))
    top = sorted(((k[0], round(v), k[2], k[1]) for k, v in apps.items()), key=lambda x: -x[1])
    return {"total_min": round(active + idle), "active_min": round(active), "idle_min": round(idle), "apps": top,
            "cats": {k: round(v) for k, v in sorted(cats.items(), key=lambda kv: -kv[1]) if round(v) >= 1},
            "sessions": sessions, "first": first, "last": last, "hours": [round(h) for h in hours],
            "hour_cats": [max(hc.items(), key=lambda kv: kv[1])[0] if hc else "" for hc in hour_cats],
            "recording": enabled(), "days": days}


def fmt_min(m: float) -> str:
    m = int(round(m))
    if m < 60:
        return f"{m} мин"
    h, r = divmod(m, 60)
    return f"{h} ч" if not r else f"{h} ч {r:02d}"


def text(day: datetime | None = None, days: int = 1) -> str:
    """Ответ в чат: «сколько сидел за компом», «на что ушёл день»."""
    d = summary(day, days)
    if not d["recording"]:
        return ("Экранное время выключено. Включить: настройки → голос и ПК → «экранное время», потом перезапустить voice.bat. "
                "Пишется только имя программы и сайт, всё остаётся на ПК.")
    if not d["active_min"] and not d["idle_min"]:
        return "За этот период данных нет: voice.bat не был запущен (пульс идёт от него)." if days == 1 else "За этот период данных нет."
    when = "сегодня" if days == 1 and (day is None or day.date() == datetime.now().date()) else (f"{day:%d.%m}" if days == 1 else f"за {days} дн.")
    lines = [f"🖥 **За ПК {when}: {fmt_min(d['active_min'])}**" + (f" (первый раз сели в {d['first']:%H:%M})" if d["first"] and days == 1 else "")]
    for name, mins, cat, sub in d["apps"][:7]:
        if mins < 2:
            continue
        lines.append(f"— {name}{f' · {sub}' if sub and sub != name else ''}: **{fmt_min(mins)}**")
    if len(d["sessions"]) > 1 and days == 1:
        lines.append("Подходы: " + ", ".join(f"{a:%H:%M}–{b:%H:%M}" for a, b in d["sessions"][:6]))
    return "\n".join(lines)


def evening_line(day: datetime | None = None) -> str:
    """Одна строка для вечернего итога — или пусто."""
    d = summary(day)
    if not d["recording"] or d["active_min"] < 10:
        return ""
    top = next(((n, m) for n, m, c, s in d["apps"] if m >= 5), None)
    return f"🖥 {fmt_min(d['active_min'])} за ПК" + (f", больше всего — {top[0]} ({fmt_min(top[1])})" if top else "") + "."


# --------------------------------------------------------------- поводы для подколов
_SPENT_RX = re.compile(r"^\s*(?:сколько\s+(?:я\s+)?(?:сегодня\s+|вчера\s+)?(?:сидел\w*|просидел\w*|провёл|провел|за\s+компом|за\s+пк|за\s+компьютером)|"
                       r"(?:на\s+что|куда)\s+(?:ушёл|ушел|делся|потратил\w*)\s+(?:мой\s+)?день|экранное\s+время|скринтайм|screen\s*time|"
                       r"сколько\s+(?:сегодня\s+|вчера\s+|за\s+неделю\s+)?(?:ютуба|youtube|телеги|telegram|премьера|premiere|игр\w*|в\s+игр\w*)|"
                       r"что\s+я\s+(?:сегодня\s+)?делал\s+(?:за\s+)?(?:компом|пк|компьютером)|отчёт\s+по\s+времени|отчет\s+по\s+времени)", re.I)


def chat_rule(text_in: str) -> str | None:
    """Шаблон для чата: вопрос про время за ПК → ответ без модели. None — не про это."""
    if not _SPENT_RX.match(text_in):
        return None
    low = text_in.lower()
    days = 7 if re.search(r"недел", low) else 1
    day = datetime.now() - timedelta(days=1) if re.search(r"\bвчера\b", low) else None
    m = re.search(r"(ютуб\w*|youtube|телег\w*|telegram|премьер\w*|premiere|игр\w*)", low)
    if m and not re.search(r"сидел|провёл|провел|день|экранное", low):
        d = summary(day, days)
        key = {"ю": "youtube", "y": "youtube", "т": "telegram", "п": "premiere", "и": "игра"}[m.group(1)[0]]
        mins = sum(mm for n, mm, c, s in d["apps"] if key in n.lower() or (key == "игра" and c == "игра") or (key == "premiere" and "premiere" in n.lower()))
        if not d["recording"]:
            return text(day, days)
        return f"{m.group(1).capitalize()}: **{fmt_min(mins)}** {'за неделю' if days == 7 else ('вчера' if day else 'сегодня')}."
    return text(day, days)


def nudge_facts(now: datetime | None = None) -> list[dict]:
    """Поводы для проактивных подколов (в общий список proactive.candidates). Только по факту, редко, без нотаций."""
    if not enabled() or not nudges_enabled():
        return []
    now = now or datetime.now()
    d = summary(now)
    out: list[dict] = []
    if d["active_min"] < 30:
        return out
    rows = [r for r in slots(now) if not r.idle]
    if not rows:
        return out
    cur = rows[-1]
    streak = (cur.end - cur.start).total_seconds() / 60 if (now - cur.end).total_seconds() < 120 else 0
    # 1. YouTube/медиа больше часа подряд днём при открытом дедлайне на сегодня-завтра
    if cur.category == "медиа" and streak >= 60:
        try:
            from ..db import Task
            with session() as s:
                due = [t.title for t in s.exec(select(Task).where(Task.done == False, Task.due != None, Task.due <= now + timedelta(days=1)))]  # noqa: E711,E712
        except Exception:
            due = []
        out.append({"key": f"screen:media:{now:%Y%m%d}:{int(streak // 60)}", "topic": "экранное время " + cur.app,
                    "fact": {"kind": "screen_media", "app": cur.app, "minutes": int(streak), "deadline_tasks": due[:2], "urgency": "low",
                             "question": "продолжаем или пора?"},
                    "text": f"{cur.app} уже {fmt_min(streak)} подряд" + (f", а «{due[0]}» ждёт." if due else ". Я не осуждаю, просто фиксирую."),
                    "buttons": [("🔕 Не надо про это", "pro:mute:0:screen")]})
    # 2. игра в рабочее время при дедлайне сегодня
    if cur.category == "игра" and 10 <= now.hour < 19 and now.weekday() < 5:
        try:
            from ..db import Task
            with session() as s:
                due_today = [t.title for t in s.exec(select(Task).where(Task.done == False, Task.due != None, Task.due <= now.replace(hour=23, minute=59)))]  # noqa: E711,E712
        except Exception:
            due_today = []
        if due_today:
            out.append({"key": f"screen:game:{now:%Y%m%d}", "topic": "игра при дедлайне",
                        "fact": {"kind": "screen_game", "app": cur.app, "deadline_tasks": due_today[:2], "time": f"{now:%H:%M}", "urgency": "normal"},
                        "text": f"{cur.app} в {now:%H:%M}, а «{due_today[0]}» сегодня. Одна катка — и за дело?",
                        "buttons": [("🔕 Не надо про это", "pro:mute:0:screen")]})
    # 3. 6+ часов без перерыва
    if d["sessions"]:
        a, b = d["sessions"][-1]
        if (b - a).total_seconds() >= 6 * 3600 and (now - b).total_seconds() < 300:
            out.append({"key": f"screen:marathon:{now:%Y%m%d}", "topic": "долго за ПК",
                        "fact": {"kind": "screen_marathon", "hours": round((b - a).total_seconds() / 3600, 1), "since": f"{a:%H:%M}",
                                 "top_app": d["apps"][0][0] if d["apps"] else "", "urgency": "low", "question": "перерыв?"},
                        "text": f"С {a:%H:%M} без перерыва. Стул уже принял вашу форму — встаньте на пять минут.",
                        "buttons": [("🔕 Не надо про это", "pro:mute:0:screen")]})
    # 4. рабочая программа впервые открылась после 16:00 (с утра — только браузер/общение/медиа)
    first_work = next((r for r in rows if r.category == "работа"), None)
    if first_work and first_work.start.hour >= 16 and (now - first_work.start).total_seconds() < 900 and d["active_min"] >= 180:
        before = {c: m for c, m in d["cats"].items() if c != "работа"}
        top = max(before.items(), key=lambda kv: kv[1])[0] if before else ""
        out.append({"key": f"screen:latework:{now:%Y%m%d}", "topic": "поздний старт работы",
                    "fact": {"kind": "screen_late_work", "app": first_work.app, "time": f"{first_work.start:%H:%M}", "before": top,
                             "before_minutes": int(before.get(top, 0)), "urgency": "low"},
                    "text": f"{first_work.app} открылся в {first_work.start:%H:%M}. Разминка ({top}, {fmt_min(before.get(top, 0))}) была основательной.",
                    "buttons": [("🔕 Не надо про это", "pro:mute:0:screen")]})
    return out
