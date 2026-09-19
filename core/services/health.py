"""Самодиагностика: Марвин проверяет себя и говорит человеческим языком, что не так и что сделать.

Отличие от /api/status: там сырое состояние систем для настроек, здесь — выводы («ПК молчит 40 минут — heartbeat
не запущен: start.bat → окно «Голос»»). Используется командой «проверь себя» и ночным self_check в планировщике,
который раньше молча ронял ошибки в лог.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

from sqlmodel import select

from ..db import Run, Setting, session, get_setting
from . import pc, state


async def diagnose() -> dict:
    """{ok: bool, items: [{level: ok|warn|bad, what, fix}], text}."""
    from ..brain import llm
    from ..config import cfg
    items: list[dict] = []

    def add(level: str, what: str, fix: str = ""):
        items.append({"level": level, "what": what, "fix": fix})

    # мозг
    ollama = await llm.ollama_available(force=True)
    if ollama:
        add("ok", f"локальная модель {llm.OLLAMA_MODEL} на месте")
    else:
        diag = await llm.ollama_diagnose()
        add("bad", "Ollama не отвечает", diag or "запусти Ollama (иконка в трее) или start.bat заново")
    if llm.cloud_enabled():
        if llm.LAST_CLOUD_ERROR:
            add("warn", f"облако ({llm.cloud_title()}): последний сбой — {llm.LAST_CLOUD_ERROR[:120]}",
                "если это 403/timeout — нужен VPN или прокси в telegram.proxy")
        else:
            add("ok", f"облако {llm.cloud_title()} подключено")
    elif llm.MODE != "local":
        add("warn", "облако не настроено — работает только локальная модель", "brain.cloud.key в config.yaml, если нужно")
    if llm.SMALL_MODEL and not llm.small_model_active():
        add("warn", f"малая модель {llm.SMALL_MODEL} не найдена в Ollama — мини-задачи идут на основную (медленнее)",
            f"ollama pull {llm.SMALL_MODEL}")

    # ПК-агент
    if pc.alive():
        add("ok", "ПК на связи")
    else:
        seen = pc.STATE.get("seen")
        ago = f"молчит {int((time.time() - seen) / 60)} мин" if seen else "ни разу не выходил на связь"
        add("bad" if seen else "warn", f"ПК-агент {ago}", "start.bat → окно «Голос» должно быть открыто; проверь, что voice_client запущен")

    # Telegram
    tg = bool(cfg.telegram.token and cfg.telegram.owner_id)
    if not tg:
        add("warn", "Telegram не настроен", "telegram.token и telegram.owner_id в config.yaml")

    # ходы агента за сутки
    since = datetime.now() - timedelta(hours=24)
    with session() as s:
        runs = s.exec(select(Run).where(Run.created_at >= since)).all()
    bad = [r for r in runs if not r.ok]
    if runs and len(bad) / len(runs) > 0.3 and len(bad) >= 3:
        add("warn", f"за сутки провалено {len(bad)} из {len(runs)} ходов",
            "посмотри «журнал» — если это одно и то же, скажи мне формулировку, добавлю правило")
    elif runs:
        add("ok", f"за сутки {len(runs)} ходов, провалов {len(bad)}")

    # календарь-очередь
    try:
        from . import gcal
        q = get_setting("gcal.queue") or ""
        n = len([x for x in q.split("\n") if x.strip()]) if q else 0
        if n:
            add("warn", f"в очереди к Google Calendar {n} событий — не ушли", "проверь интернет/токен Google; уйдут сами при следующем тике")
    except Exception:
        pass

    # бэкап
    try:
        from .scheduler import last_backup
        lb = last_backup()
        at = lb.get("at") if isinstance(lb, dict) else None
        if at:
            age = (datetime.now() - datetime.fromisoformat(at)).total_seconds() / 3600
            if age > 48:
                add("warn", f"последний бэкап базы {int(age)} ч назад", "ночной бэкап не сработал — проверь, что Марвин работал ночью")
            else:
                add("ok", "бэкап свежий")
    except Exception:
        pass

    # застрявшие тяжёлые задачи
    for j in state.jobs():
        if j.get("running") and time.time() - j["started"] > 6 * 3600:
            add("warn", f"«{j['name']}» крутится уже {int((time.time() - j['started']) / 3600)} ч", "если это не так — скажи «стоп»")

    # диск
    try:
        import shutil
        from ..config import DB_PATH
        free_gb = shutil.disk_usage(DB_PATH.parent).free / 1e9
        if free_gb < 3:
            add("bad", f"на диске с базой осталось {free_gb:.1f} ГБ", "почисти место — при 0 база перестанет писаться")
    except Exception:
        pass

    ok = not any(i["level"] == "bad" for i in items)
    return {"ok": ok, "items": items, "text": _text(items, ok), "at": datetime.now().isoformat()}


def _text(items: list[dict], ok: bool) -> str:
    bad = [i for i in items if i["level"] != "ok"]
    if not bad:
        return "Проверил себя: всё на месте — модель, ПК, бэкап. Работаю."
    icon = {"bad": "✗", "warn": "△"}
    lines = ["Всё живо, но есть нюансы:" if ok else "Есть проблемы:"]
    for i in bad:
        lines.append(f"{icon[i['level']]} {i['what']}" + (f" → {i['fix']}" if i["fix"] else ""))
    return "\n".join(lines)


def record(res: dict) -> None:
    """Запоминаем последний результат и, если состояние ухудшилось, — событие (чтобы сказать один раз, а не каждый час)."""
    from ..db import set_setting
    from . import events
    prev = get_setting("health.last_ok")
    set_setting("health.last_ok", "1" if res["ok"] else "0")
    set_setting("health.last_at", res["at"])
    if not res["ok"] and prev != "0":
        events.emit("health_bad", key="health", dedup_sec=6 * 3600, text=res["text"], quiet=False)
    elif res["ok"] and prev == "0":
        events.emit("health_ok", key="health", dedup_sec=3600, quiet=True)


import re
SELF_RX = re.compile(r"^\s*(?:проверь\s+себя|самопроверк\w*|диагностик\w*|что\s+с\s+тобой|ты\s+в\s+порядке|всё\s+работает)\s*\??\s*$", re.I)
