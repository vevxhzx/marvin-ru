"""F4-short: часы процесса и owner.timezone. Полный clock.now() рефактор вне скоупа.

FIX 05.10 (Windows): раньше здесь записывали `os.environ["TZ"] = "Europe/Moscow"`.
На POSIX это корректно (есть `time.tzset`), а на Windows `tzset` нет и именованная
зона (IANA) криво разбирается CRT — часы процесса уходили на **UTC (−3 ч)**.
Симптомы, из-за которых сюда и зашли: утренний дайджест приходил с заголовком
«05:30» при реальных 08:30 (Telegram показывал 8:30), все created_at в БД были
на 3 часа позади, день/просрочка/«сегодня» считались по UTC.

Поэтому: на Windows TZ больше НЕ выставляем — процесс живёт в системной зоне ОС,
а реальное расхождение зон (смещениями, а не названиями) ругается в health.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timedelta

log = logging.getLogger("jarvis.tz")
TZ_WARN = "system TZ != owner.timezone, день/просрочка считаются по системной зоне"


def system_zone() -> str:
    return os.environ.get("TZ") or (time.tzname[0] if time.tzname else "")


def _process_offset() -> timedelta | None:
    """Текущее смещение локальных часов процесса от UTC (с учётом перехода на летнее время)."""
    try:
        return datetime.now().astimezone().utcoffset()
    except Exception:
        return None


def _zone_offset(name: str) -> timedelta | None:
    """Смещение зоны `name` сейчас. zoneinfo может отсутствовать (нет tzdata) — тогда None."""
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo

        return datetime.now(ZoneInfo(name)).utcoffset()
    except Exception:
        return None


def is_tz_mismatch(owner_tz: str | None, system_tz: str | None = None) -> bool:
    """True, если часы владельца и процесса реально расходятся.

    По умолчанию сравниваем СМЕЩЕНИЯ, а не названия: на Windows системная зона
    выглядит как «Russia TZ 2 Standard Time» и с «Europe/Moscow» не совпадает
    никогда, хотя смещение одинаковое — раньше это давало вечный ложный warn.
    Строка `system_tz` переданная явно (диагностика/тесты) сравнивается как раньше.
    """
    if not owner_tz or not owner_tz.strip():
        return False
    owner = owner_tz.strip()
    if system_tz is not None:
        return bool(system_tz.strip()) and system_tz.strip() != owner
    off_owner, off_sys = _zone_offset(owner), _process_offset()
    if off_owner is None or off_sys is None:  # не смогли вычислить — прежнее поведение по названию
        sys_name = system_zone().strip()
        return bool(sys_name) and sys_name != owner
    return off_owner != off_sys


def apply_owner_timezone(owner_tz: str | None) -> bool:
    """Перевести процесс в зону владельца. False — менять нечего (или нельзя на этой ОС)."""
    if not owner_tz or not is_tz_mismatch(owner_tz):
        return False
    if not hasattr(time, "tzset"):
        # Windows: без tzset запись IANA-имени в TZ ломает часы (см. докстринг модуля) —
        # не трогаем. Если зоны действительно разные, это подскажет health.
        log.warning(
            "Windows: TZ не выставляем (система=%s, owner=%s) — без time.tzset это уводило время в UTC. "
            "Процесс живёт в системной зоне ОС.", system_zone(), owner_tz,
        )
        return False
    prev = os.environ.get("TZ")
    os.environ["TZ"] = owner_tz
    time.tzset()
    # страховка: зона не распозналась и часы поехали — откатываем, чтобы не повторить баг с UTC
    off_proc, off_owner = _process_offset(), _zone_offset(owner_tz)
    if off_owner is not None and off_proc != off_owner:
        if prev is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = prev
        time.tzset()
        log.warning("TZ=%s не применился (процесс %s, ожидалось %s) — вернули как было",
                    owner_tz, off_proc, off_owner)
        return False
    log.info("TZ=%s из owner.timezone", owner_tz)
    return True
