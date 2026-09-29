"""Единое «сейчас» Марвина: чем занят человек, давно ли за ПК, что крутится в фоне, чего Марвин ждёт.

До 0.10 это было размазано: пульс в pc.STATE, экран в ScreenSlot, «человек пишет» в llm, незакрытые уточнения
в Setting pending:*. Ни агент, ни инициативы не знали, что человек 3 часа в Premiere или только что сел.

Здесь:
• presence: offline (клиент не на связи) / active / idle (нет мыши idle_min) / away (нет 30+ мин) — lifecycle
  active → idle → away → active. Переходы порождают события (events.emit): user_idle, user_back, user_arrived (утром /
  после 6+ ч), long_session (3 ч подряд без перерыва), heavy_job_started/finished (рендер/тяжёлая программа).
• activity: программа/сайт/категория и сколько подряд в этом занятии (по ScreenSlot, если экранное время включено;
  иначе — только presence по пульсу).
• jobs: фоновые работы ядра с прогрессом (register/progress/done/fail) — для статуса и события background_failed.
• snapshot(): словарь для API/сайта; line(): одна строка для промпта агента (~30 токенов, без заголовков окон).
• Переживает перезапуск: последний снимок хранится в Setting("state.last"); restore() при старте отличает
  «первый запуск» от «перезапуск после 3 мин» и порождает событие restart с длительностью паузы.

Данные берутся ТОЛЬКО из того, что уже приходит (пульс ПК, ScreenSlot). Ничего нового не собирается.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta

from sqlmodel import select

from ..db import ScreenSlot, get_setting, session, set_setting
from . import events

log = logging.getLogger("marvin.state")

IDLE_AFTER_MIN = 5        # столько минут без мыши/клавы = idle (перекрывается voice.pc.screen_time.idle_min)
AWAY_AFTER_MIN = 30       # столько минут idle = away
ARRIVE_GAP_H = 6          # вернулся после 6+ ч отсутствия = «сел за компьютер» (утро / новый день)
LONG_SESSION_H = 3        # без перерыва дольше — событие long_session (раз в сессию)
HEAVY_APPS = {"Media Encoder", "DaVinci Resolve", "Blender", "After Effects"}   # длинная фоновая работа = рендер
HEAVY_MIN = 4             # рендер считается «тяжёлой работой», если программа в фокусе/жива ≥ этого (иначе просто открыл)

_S: dict = {
    "presence": "offline",            # offline / active / idle / away
    "since": None,                    # datetime: с какого момента в этом presence
    "last_seen": None,                # datetime последнего пульса
    "app": "", "sub": "", "cat": "",  # текущее занятие (по ScreenSlot)
    "act_since": None,                # с какого момента в текущем занятии
    "session_start": None,            # начало текущей сессии за ПК (сел)
    "last_talk": None,                # datetime последнего сообщения/фразы человека (присутствие без ПК-клиента)
    "long_flagged": False,            # long_session уже отправлено в этой сессии
    "heavy": {},                      # app → datetime начала (тяжёлая работа сейчас)
    "restarted_at": None,             # datetime старта ядра
    "prev_shutdown": None,            # datetime последнего снимка до перезапуска
}
_JOBS: dict[str, dict] = {}           # name → {"started", "progress", "note", "ok", "error", "finished"}
_last_persist = 0.0


# ----------------------------------------------------------------- lifecycle
def _idle_threshold() -> int:
    try:
        from . import screen
        return int(screen.idle_min() or IDLE_AFTER_MIN)
    except Exception:  # pragma: no cover
        return IDLE_AFTER_MIN


def _set_presence(p: str, now: datetime) -> None:
    prev = _S["presence"]
    if prev == p:
        return
    prev_since = _S["since"] or now
    _S["presence"], _S["since"] = p, now
    gap_min = int((now - prev_since).total_seconds() // 60)
    if p == "active":
        if prev in ("away", "offline"):
            long_gap = gap_min >= ARRIVE_GAP_H * 60 or prev == "offline" and _S["session_start"] is None
            _S["session_start"] = now
            _S["long_flagged"] = False
            if long_gap:
                events.emit("user_arrived", key=now.strftime("%Y-%m-%d"), dedup_sec=3600, gap_min=gap_min)
            else:
                events.emit("user_back", key="back", dedup_sec=120, minutes=gap_min)
        elif prev == "idle":
            events.emit("user_back", key="back", dedup_sec=120, minutes=gap_min, quiet=gap_min < 10)
    elif p == "idle":
        events.emit("user_idle", key="idle", dedup_sec=120, quiet=True)
    elif p == "away":
        events.emit("user_away", key="away", dedup_sec=600, minutes=gap_min, quiet=True)
        _S["session_start"] = None


def tick(app: str = "", sub: str = "", cat: str = "", idle_sec: int | None = None, now: datetime | None = None) -> dict:
    """Один пульс от ПК-клиента (зовётся из /api/pc/ping ПОСЛЕ screen.record). idle_sec=None — клиент без экранного времени:
    тогда presence считается только по факту пульса (active/offline), занятие неизвестно."""
    now = now or datetime.now()
    _S["last_seen"] = now
    if idle_sec is None:
        _set_presence("active", now)
    else:
        thr = _idle_threshold() * 60
        if idle_sec >= AWAY_AFTER_MIN * 60:
            _set_presence("away", now)
        elif idle_sec >= thr:
            _set_presence("idle", now)
        else:
            _set_presence("active", now)
        # занятие
        if _S["presence"] == "active" and app:
            if (app, sub) != (_S["app"], _S["sub"]):
                _S["app"], _S["sub"], _S["cat"], _S["act_since"] = app, sub, cat, now
                events.emit("app_focus", key=app, dedup_sec=60, quiet=True, journal=False, app=app, cat=cat)
        # тяжёлая работа: программа из HEAVY_APPS в фокусе ≥ HEAVY_MIN → started; ушла из фокуса и не вернулась 3 мин → finished
        _heavy(app, now)
    # долгая сессия
    if _S["presence"] == "active" and _S["session_start"] and not _S["long_flagged"]:
        hours = (now - _S["session_start"]).total_seconds() / 3600
        if hours >= LONG_SESSION_H:
            _S["long_flagged"] = True
            events.emit("long_session", key=_S["session_start"].isoformat(), hours=int(hours))
    _persist(now)
    return snapshot(now)


def _heavy(app: str, now: datetime) -> None:
    heavy = _S["heavy"]
    if app in HEAVY_APPS:
        if app not in heavy:
            heavy[app] = {"start": now, "seen": now, "flagged": False}
        else:
            heavy[app]["seen"] = now
            if not heavy[app]["flagged"] and (now - heavy[app]["start"]).total_seconds() >= HEAVY_MIN * 60:
                heavy[app]["flagged"] = True
                events.emit("heavy_job_started", key=app, dedup_sec=600, app=app)
    for name, h in list(heavy.items()):
        if name != app and (now - h["seen"]).total_seconds() >= 180:
            minutes = int((h["seen"] - h["start"]).total_seconds() // 60)
            if h["flagged"]:
                events.emit("heavy_job_finished", key=name, dedup_sec=600, app=name, minutes=minutes)
            heavy.pop(name, None)


def offline_check(now: datetime | None = None) -> None:
    """Планировщик раз в минуту: пульса нет 90 с → offline (клиент выключен/ПК спит)."""
    now = now or datetime.now()
    ls = _S["last_seen"]
    if ls and (now - ls).total_seconds() > 90 and _S["presence"] != "offline":
        _set_presence("offline", now)
        _S["session_start"] = None
        _persist(now, force=True)


def mark_conversation(now: datetime | None = None) -> None:
    """Человек написал/сказал — это тоже присутствие (если нет ПК-клиента, это единственный сигнал)."""
    _S["last_talk"] = now or datetime.now()


def talking(now: datetime | None = None, minutes: int = 10) -> bool:
    """Писал/говорил за последние N минут — «рядом», даже если ПК-клиента нет (Telegram с телефона)."""
    lt = _S.get("last_talk")
    return bool(lt and ((now or datetime.now()) - lt).total_seconds() <= minutes * 60)


# ----------------------------------------------------------------- фоновые работы
def job_start(name: str, note: str = "", announce: bool = False) -> None:
    """announce=True — по завершении сказать человеку («готово»); иначе успех тихий, а провал — событие всё равно."""
    _JOBS[name] = {"started": datetime.now(), "progress": 0.0, "note": note, "ok": None, "error": "", "finished": None, "announce": announce}
    events.emit("background_started", key=name, quiet=True, journal=False, job=name)


def job_progress(name: str, progress: float, note: str = "") -> None:
    j = _JOBS.get(name)
    if j:
        j["progress"] = max(0.0, min(1.0, progress))
        if note:
            j["note"] = note


def job_done(name: str, note: str = "") -> None:
    if name not in _JOBS:
        job_start(name)
    j = _JOBS[name]
    j.update(progress=1.0, ok=True, finished=datetime.now(), note=note or j["note"])
    events.emit("background_done", key=name, quiet=True, journal=bool(j.get("announce")), job=name, note=note, announce=bool(j.get("announce")))


def job_fail(name: str, error: str) -> None:
    if name not in _JOBS:
        job_start(name)
    j = _JOBS[name]
    j.update(ok=False, finished=datetime.now(), error=str(error)[:200])
    events.emit("background_failed", key=name, dedup_sec=3600, job=name, error=str(error)[:120])


def tracked(name: str, announce: bool = False):
    """Обёртка для фоновых корутин планировщика: старт/финиш/ошибка попадают в jobs и события, исключение — дальше."""
    def deco(fn):
        async def wrapper(*a, **kw):
            job_start(name, announce=announce)
            try:
                r = await fn(*a, **kw)
            except Exception as e:
                job_fail(name, str(e) or type(e).__name__)
                raise
            job_done(name)
            return r
        wrapper.__name__ = getattr(fn, "__name__", name)
        return wrapper
    return deco


def jobs(active_only: bool = False) -> list[dict]:
    out = []
    for name, j in _JOBS.items():
        if active_only and j["finished"]:
            continue
        out.append({"name": name, **{k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in j.items()}})
    return out


def running_job() -> dict | None:
    for name, j in _JOBS.items():
        if not j["finished"]:
            return {"name": name, **j}
    return None


# ----------------------------------------------------------------- снимок и строка для промпта
def _fmt_dur(sec: float) -> str:
    m = int(sec // 60)
    return f"{m // 60} ч {m % 60:02d} мин" if m >= 60 else f"{m} мин"


def snapshot(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    since = _S["since"]
    act_since = _S["act_since"]
    ss = _S["session_start"]
    return {
        "presence": _S["presence"],
        "presence_min": int((now - since).total_seconds() // 60) if since else None,
        "session_min": int((now - ss).total_seconds() // 60) if ss and _S["presence"] == "active" else None,
        "app": _S["app"] if _S["presence"] == "active" else "", "sub": _S["sub"] if _S["presence"] == "active" else "",
        "cat": _S["cat"] if _S["presence"] == "active" else "",
        "act_min": int((now - act_since).total_seconds() // 60) if act_since and _S["presence"] == "active" else None,
        "heavy": [n for n, h in _S["heavy"].items() if h["flagged"]],
        "jobs": jobs(active_only=True),
        "restarted_at": _S["restarted_at"].isoformat() if _S["restarted_at"] else None,
        "pending": _pending_summary(),
        "last_seen": _S["last_seen"].isoformat() if _S["last_seen"] else None,
    }


def _pending_summary() -> str:
    """Чего Марвин ждёт от человека (незакрытое подтверждение/уточнение) — коротко."""
    try:
        from ..db import Setting
        with session() as s:
            rows = s.exec(select(Setting).where(Setting.key.like("pending:%"))).all()   # type: ignore[attr-defined]
        for r in rows:
            if not r.value or "|" not in r.value:
                continue
            ts, text = r.value.split("|", 1)
            try:
                if (datetime.now() - datetime.fromisoformat(ts)).total_seconds() > 300:
                    continue
            except ValueError:
                continue
            if text.startswith("confirm|"):
                try:
                    d = json.loads(text[8:])
                    what = {"shutdown": "выключение ПК", "reboot": "перезагрузку ПК"}.get(d.get("pc"), "") or ("уборку папки" if "tidy" in d else "") or d.get("name", "действие")
                    return f"жду «да» на {what}"
                except json.JSONDecodeError:
                    return "жду подтверждения"
            return "жду ответа на уточнение"
    except Exception:  # pragma: no cover
        pass
    return ""


def line(now: datetime | None = None) -> str:
    """Одна строка для промпта: «Сейчас: за ПК 2 ч 40 мин, Premiere Pro (работа) последние 50 мин.» Заголовков окон
    здесь нет никогда (в них может быть что угодно, в т.ч. инструкции модели). Пусто — если ничего не знаем."""
    sn = snapshot(now)
    p = sn["presence"]
    if p == "offline":
        return ""
    if p in ("idle", "away"):
        return f"Сейчас: человека нет за ПК {sn['presence_min']} мин."
    parts = []
    if sn["session_min"] is not None:
        parts.append(f"за ПК {_fmt_dur(sn['session_min'] * 60)}")
    if sn["app"]:
        label = sn["app"] if sn["cat"] != "браузер" else "браузер"
        cat = f" ({sn['cat']})" if sn["cat"] and sn["cat"] != "браузер" else ""
        parts.append(f"{label}{cat}" + (f" последние {_fmt_dur(sn['act_min'] * 60)}" if sn["act_min"] else ""))
    if sn["heavy"]:
        parts.append("идёт рендер в " + ", ".join(sn["heavy"]))
    return ("Сейчас: " + ", ".join(parts) + ".") if parts else ""


# ----------------------------------------------------------------- перезапуск
def _persist(now: datetime, force: bool = False) -> None:
    global _last_persist
    if not force and time.monotonic() - _last_persist < 60:
        return
    _last_persist = time.monotonic()
    try:
        set_setting("state.last", json.dumps({"at": now.isoformat(), "presence": _S["presence"],
                                              "session_start": _S["session_start"].isoformat() if _S["session_start"] else None,
                                              "app": _S["app"], "cat": _S["cat"]}, ensure_ascii=False))
    except Exception as e:  # pragma: no cover
        log.debug("state persist: %s", e)


def restore(now: datetime | None = None) -> dict:
    """При старте ядра: прочитать последний снимок. Возвращает {'first_run', 'gap_min', 'was'} и шлёт событие restart."""
    now = now or datetime.now()
    _S["restarted_at"] = now
    raw = get_setting("state.last", "") or ""
    info = {"first_run": not raw, "gap_min": None, "was": None}
    if raw:
        try:
            d = json.loads(raw)
            at = datetime.fromisoformat(d["at"])
            info["gap_min"] = int((now - at).total_seconds() // 60)
            info["was"] = d.get("presence")
            info["clean"] = bool(d.get("clean"))
            _S["prev_shutdown"] = at
            # короткий перезапуск (< 10 мин) во время работы — сессия продолжается, а не начинается заново
            if d.get("presence") == "active" and info["gap_min"] < 10 and d.get("session_start"):
                _S["session_start"] = datetime.fromisoformat(d["session_start"])
                _S["app"], _S["cat"] = d.get("app", ""), d.get("cat", "")
                _S["presence"], _S["since"], _S["last_seen"] = "active", at, at   # пульс придёт через ≤20 с; не придёт — offline_check вернёт offline
        except (KeyError, ValueError, json.JSONDecodeError):
            info["first_run"] = True
    events.emit("restart", key=now.isoformat(), gap_min=info["gap_min"] or 0, clean=info.get("clean", False), quiet=True)
    _persist(now, force=True)
    return info


def shutdown(now: datetime | None = None) -> None:
    """Штатное завершение: последний снимок с пометкой clean — при следующем старте restore() знает, что это не падение."""
    now = now or datetime.now()
    _persist(now, force=True)
    raw = get_setting("state.last", "") or ""
    try:
        d = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        d = {}
    d["clean"] = True
    set_setting("state.last", json.dumps(d, ensure_ascii=False))


def reset() -> None:
    """Для тестов."""
    _S.update(presence="offline", since=None, last_seen=None, app="", sub="", cat="", act_since=None, session_start=None,
              last_talk=None, long_flagged=False, heavy={}, restarted_at=None, prev_shutdown=None)
    _JOBS.clear()
