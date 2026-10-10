# -*- coding: utf-8 -*-
"""Вечерний обзор не пристаёт с «перенести?» к задачам с автопереносом — они сами уедут ночью."""
from __future__ import annotations

from datetime import datetime, timedelta


def test_evening_review_skips_auto_roll(fresh_db):
    from core.services import tasks

    t1 = tasks.add_task("Ручная задача", datetime.now().replace(hour=23, minute=59, second=0, microsecond=0))
    t2 = tasks.add_task("Автозадача", datetime.now().replace(hour=23, minute=59, second=0, microsecond=0))
    tasks.update_task(t2.id, auto_roll=True)
    titles = [t.title for t in tasks.evening_review()]
    assert "Ручная задача" in titles
    assert "Автозадача" not in titles


def test_rollover_moves_only_flagged(fresh_db):
    from core.services import tasks

    yesterday = (datetime.now() - timedelta(days=1)).replace(hour=23, minute=59, second=0, microsecond=0)
    t1 = tasks.add_task("Ручная вчера", yesterday)
    t2 = tasks.add_task("Авто вчера", yesterday)
    tasks.update_task(t2.id, auto_roll=True)
    moved = tasks.rollover_overdue()
    assert t2.id in [t.id for t in moved]
    assert t1.id not in [t.id for t in moved]
    # повторный прогон идемпотентен — второй раз ничего не едет
    assert tasks.rollover_overdue() == []
