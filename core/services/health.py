"""Самодиагностика: ассистент проверяет себя и говорит человеческим языком, что не так и что сделать.

Отличие от /api/status: там сырое состояние систем для настроек, здесь — выводы («ПК молчит 40 минут — heartbeat
не запущен: start.bat → окно «Голос»»). Используется командой «проверь себя» и ночным self_check в планировщике,
который раньше молча ронял ошибки в лог.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from sqlmodel import select

from ..db import Run, get_setting, session
from . import pc, state

log = logging.getLogger("jarvis.health")


async def diagnose() -> dict:
    """{ok: bool, items: [{level: ok|warn|bad, what, fix}], text}."""
    from ..brain import llm
    from ..config import cfg
    items: list[dict] = []

    def add(level: str, what: str, fix: str = ""):
        items.append({"level": level, "what": what, "fix": fix})

    # мозг: отвечает выбранный движок — всё хорошо; иначе честно какой именно лежит
    lms_role = llm.lmstudio_role()
    lms_up = bool(lms_role) and await llm.lmstudio_available()
    if lms_up:
        add("ok", f"локально отвечает {await llm.lmstudio_active_model()} (LM Studio)")
    else:
        if lms_role:
            add("warn", f"LM Studio не отвечает ({llm.lms_last_error() or 'сервер закрыт или модель не загружена'})",
                "запустите сервер в LM Studio; пока отвечаю через запасной путь")
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
    if llm.SMALL_MODEL and not llm.small_model_active() and not llm.lmstudio_role():
        add("warn", f"малая модель {llm.SMALL_MODEL} не найдена в Ollama — мини-задачи идут на основную (медленнее)",
            f"ollama pull {llm.SMALL_MODEL}")

    # ПК-агент
    if pc.alive():
        add("ok", f"ПК на связи (последний пульс {int(pc.age_sec() or 0)} с назад)")
    else:
        age = pc.age_sec()
        if age is None:
            add("warn", "ПК-клиент ещё не выходил на связь",
                "⚙ Настройки → «голос и ПК» → карточка «пк-клиент» → «запустить»; или окно voice.bat")
        else:
            add("bad", f"ПК-клиент молчит {int(age / 60)} мин (последний пульс {pc.last_seen_iso()})",
                "проверьте окно voice.bat; перезапустить можно из ⚙ Настройки → «голос и ПК»")

    # Telegram
    tg = bool(cfg.telegram.token and cfg.telegram.owner_id)
    if not tg:
        add("warn", "Telegram не настроен", "telegram.token и telegram.owner_id в config.yaml")
    try:  # F4-short: doctor/check-предупреждение (полный clock.now() рефактор вне скоупа)
        from ..timezone import TZ_WARN, is_tz_mismatch
        if is_tz_mismatch(getattr(getattr(cfg, "owner", None), "timezone", "") or ""):
            add("warn", TZ_WARN, "системная зона и owner.timezone должны совпадать; перезапусти ядро")
    except Exception as e: log.debug("tz check: %s", e)

    # ходы агента за сутки — одним флагом на строку, а не все колонки (текст хода тут не нужен)
    since = datetime.now() - timedelta(hours=24)
    with session() as s:
        oks = s.exec(select(Run.ok).where(Run.created_at >= since)).all()
    total, bad_n = len(oks), sum(1 for ok in oks if not ok)
    if total and bad_n / total > 0.3 and bad_n >= 3:
        add("warn", f"за сутки провалено {bad_n} из {total} ходов",
            "посмотри «журнал» — если это одно и то же, скажи мне формулировку, добавлю правило")
    elif total:
        add("ok", f"за сутки {total} ходов, провалов {bad_n}")

    # календарь-очередь
    try:
        q = get_setting("gcal.queue") or ""
        n = len([x for x in q.split("\n") if x.strip()]) if q else 0
        if n:
            add("warn", f"в очереди к Google Calendar {n} событий — не ушли", "проверь интернет/токен Google; уйдут сами при следующем тике")
    except Exception as e:
        # раньше здесь был `except Exception: pass` — очередь Google молча не проверялась
        log.warning("очередь Google Calendar не проверена: %s", e)
        add("warn", f"не удалось проверить очередь Google Calendar: {type(e).__name__}: {e}",
            "обычно битая настройка gcal.queue в базе — проверь модуль календаря")

    # бэкап: возраст, размер и результат последней проверки целостности
    lb = None
    try:
        from .scheduler import last_backup
        lb = last_backup()
    except Exception as e:
        log.warning("не удалось получить состояние бэкапов: %s", e)
        add("warn", f"не удалось проверить бэкапы: {type(e).__name__}: {e}",
            "обычно недоступна папка бэкапов — проверь backup.dir в настройках")
    if isinstance(lb, dict):
        at = lb.get("last")   # last_backup() отдаёт «last», не «at»
        age_h = None
        if at:
            try:
                age_h = (datetime.now() - datetime.fromisoformat(str(at))).total_seconds() / 3600
            except ValueError as e:
                log.warning("нечитаемая дата последнего бэкапа %r: %s", at, e)
        if age_h is not None:
            size = f" · {_mb(lb.get('size'))}" if lb.get("size") else ""
            if age_h > 48:
                add("warn", f"последний бэкап базы {int(age_h)} ч назад{size}",
                    "ночной бэкап не сработал — проверь, что ассистент работал ночью")
            else:
                add("ok", f"бэкап свежий ({int(age_h)} ч назад{size})")
        elif lb.get("enabled"):
            add("warn", "бэкапов ещё нет", "нажми «бэкап сейчас» в настройках и проверь, что ночной бэкап включён")
        chk = lb.get("check")
        if isinstance(chk, dict) and chk.get("result"):
            if chk.get("ok"):
                add("ok", f"проверка бэкапа {chk.get('file', '')}: integrity_check — ok")
            else:
                add("bad", f"бэкап {chk.get('file', '')} не прошёл integrity_check: {chk.get('result')}",
                    "снимок повреждён — сделай «бэкап сейчас» заново и проверь диск")

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
    except Exception as e:
        # раньше здесь было `except Exception: pass` — неполадка с диском молчала
        log.warning("не удалось проверить диск: %s", e)
        add("warn", f"не удалось проверить свободное место на диске: {type(e).__name__}: {e}",
            "проверь, что папка data/ доступна на чтение")

    ok = not any(i["level"] == "bad" for i in items)
    return {"ok": ok, "items": items, "text": _text(items, ok), "at": datetime.now().isoformat()}


def _mb(size) -> str:
    """Байты → «12,3 МБ» для человеческих строк."""
    try:
        return f"{int(size) / 1e6:.1f} МБ"
    except (TypeError, ValueError):
        return ""


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
