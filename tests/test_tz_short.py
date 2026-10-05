"""F4-short: часы процесса и owner.timezone. Полный clock.now() рефактор вне скоупа.

REGRESSION 05.10: на Windows запись IANA-имени в os.environ["TZ"] уводила часы
процесса на UTC (−3 ч) — дайджест приходил «05:30» при реальных 08:30.
"""
import os
import time
from datetime import datetime, timedelta

from core.timezone import TZ_WARN, apply_owner_timezone, is_tz_mismatch

HAS_TZSET = hasattr(time, "tzset")
WINDOWS = os.name == "nt"


def test_same_zone_no_mismatch():
    assert is_tz_mismatch("Europe/Moscow", "Europe/Moscow") is False


def test_different_zone_mismatch():
    assert is_tz_mismatch("Europe/Moscow", "UTC") is True


def test_empty_owner_no_mismatch():
    assert is_tz_mismatch("", "UTC") is False
    assert is_tz_mismatch(None, "UTC") is False
    assert is_tz_mismatch("   ") is False


def test_warn_text_mentions_day_overdue():
    assert "день/просрочка" in TZ_WARN and "system TZ" in TZ_WARN


def test_mismatch_compares_offsets_not_names():
    """Системное имя («Russia TZ 2 Standard Time») никогда != «Europe/Moscow»,
    но если смещения равны — расхождения нет (иначе вечный ложный warn в health)."""
    try:
        from zoneinfo import ZoneInfo
    except Exception:
        return  # нет tzdata — проверить смещения не можем
    same = datetime.now().astimezone().utcoffset() == datetime.now(ZoneInfo("Europe/Moscow")).utcoffset()
    assert is_tz_mismatch("Europe/Moscow") is (not same)


def test_apply_does_not_break_clock_on_windows(monkeypatch):
    """На Windows TZ не выставляем: без time.tzset это уводило время на UTC (−3 ч)."""
    if not WINDOWS:
        return
    monkeypatch.delenv("TZ", raising=False)
    before = datetime.now()
    apply_owner_timezone("Europe/Moscow")
    after = datetime.now()
    assert "TZ" not in os.environ, "на Windows TZ ставить нельзя — это ломает часы процесса"
    assert abs(after - before) < timedelta(minutes=1), "часы процесса сдвинулись после apply_owner_timezone"


def test_apply_sets_tz_env_posix(monkeypatch):
    """На POSIX (есть tzset) зона владельца применяется как раньше."""
    if not HAS_TZSET:
        return
    monkeypatch.setenv("TZ", "UTC")
    assert apply_owner_timezone("Europe/Moscow") is True
    assert os.environ["TZ"] == "Europe/Moscow"


def test_apply_noop_when_zone_matches(monkeypatch):
    """Если текущее смещение процесса уже равно владельцу — ничего не меняем."""
    from core.timezone import _process_offset, _zone_offset

    off_own = _zone_offset("Europe/Moscow")
    if off_own is None or _process_offset() != off_own:
        return  # машина реально в другой зоне — тут применение и ожидается
    monkeypatch.delenv("TZ", raising=False)
    assert apply_owner_timezone("Europe/Moscow") is False
    assert "TZ" not in os.environ
