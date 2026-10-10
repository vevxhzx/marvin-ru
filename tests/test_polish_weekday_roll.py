# -*- coding: utf-8 -*-
"""День недели без времени: если дефолтные 10:00 сегодня уже прошли — следующая неделя, а не прошедшее."""
from __future__ import annotations

from datetime import datetime


def _parse(text: str, now: datetime):
    from core.brain.dates import parse_datetime_ex

    return parse_datetime_ex(text, now)


def test_weekday_no_time_past_default_rolls():
    sat_11 = datetime(2026, 10, 10, 11, 0)  # суббота, 10:00 уже прошло
    dt, _, time_set = _parse("ужин с родителями в субботу", sat_11)
    assert not time_set
    assert (dt.year, dt.month, dt.day) == (2026, 10, 17)


def test_weekday_no_time_future_default_stays():
    sat_8 = datetime(2026, 10, 10, 8, 0)  # суббота, 10:00 ещё впереди
    dt, _, _ = _parse("ужин с родителями в субботу", sat_8)
    assert (dt.year, dt.month, dt.day) == (2026, 10, 10)


def test_weekday_explicit_future_time_stays_today():
    sat_15 = datetime(2026, 10, 10, 15, 0)
    dt, _, time_set = _parse("встреча в субботу в 19:00", sat_15)
    assert time_set
    assert (dt.year, dt.month, dt.day, dt.hour) == (2026, 10, 10, 19)


def test_weekday_explicit_past_time_rolls():
    sat_15 = datetime(2026, 10, 10, 15, 0)
    dt, _, _ = _parse("встреча в субботу в 10:00", sat_15)
    assert (dt.year, dt.month, dt.day) == (2026, 10, 17)
