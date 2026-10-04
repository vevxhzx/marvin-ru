"""F4-short: предикат расхождения TZ. Полный clock.now() рефактор вне скоупа."""
from core.timezone import TZ_WARN, apply_owner_timezone, is_tz_mismatch


def test_same_zone_no_mismatch():
    assert is_tz_mismatch("Europe/Moscow", "Europe/Moscow") is False


def test_different_zone_mismatch():
    assert is_tz_mismatch("Europe/Moscow", "UTC") is True


def test_empty_owner_no_mismatch():
    assert is_tz_mismatch("", "UTC") is False
    assert is_tz_mismatch(None, "UTC") is False


def test_warn_text_mentions_day_overdue():
    assert "день/просрочка" in TZ_WARN and "system TZ" in TZ_WARN


def test_apply_sets_tz_env(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    assert apply_owner_timezone("Europe/Moscow") is True
    import os
    assert os.environ["TZ"] == "Europe/Moscow"
