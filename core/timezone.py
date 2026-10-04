"""SHORT фикс часового пояса: процесс живёт в owner.timezone. Полный clock.now() рефактор вне скоупа."""
from __future__ import annotations
import logging, os, time
log = logging.getLogger("jarvis.tz")
TZ_WARN = "system TZ != owner.timezone, день/просрочка считаются по системной зоне"
def system_zone() -> str:
    return os.environ.get("TZ") or (time.tzname[0] if time.tzname else "")
def is_tz_mismatch(owner_tz: str | None, system_tz: str | None = None) -> bool:
    if not owner_tz: return False
    sys_tz = system_tz if system_tz is not None else system_zone()
    return bool(sys_tz) and sys_tz.strip() != owner_tz.strip()
def apply_owner_timezone(owner_tz: str | None) -> bool:
    if not owner_tz or not is_tz_mismatch(owner_tz): return False
    os.environ["TZ"] = owner_tz
    if hasattr(time, "tzset"): time.tzset(); log.info("TZ=%s из owner.timezone", owner_tz)
    else: log.warning("Windows: tzset нет — %s", TZ_WARN)
    return True
