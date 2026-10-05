# -*- coding: utf-8 -*-
"""Время встречи в API: 10:59 должны остаться 10:59, а не превратиться в 07:59.

Веб слал время как `new Date(...).toISOString()` — строку с зоной («Z»: 10:59 Москвы =
07:59Z). БД и весь бэкенд живут в локальном «наивном» времени, зона при записи терялась,
и встреча вместе со сроком привязанной задачи уезжала на 3 часа назад.

Держим оба входа: локальное поле (то, что теперь шлёт веб) и момент с зоной (на будущее —
любой сторонний клиент может прислать ISO с offset).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.usefixtures("fresh_db")

TITLE = "забежать забрать приписное"
# 10:59 в Москве — тот самый случай из бага (UTC это 07:59)
WALL = datetime(2026, 10, 6, 7, 59, tzinfo=timezone.utc)


def test_naive_local_time_passes_through():
    """Локальное поле без зоны («2026-10-06T10:59») остаётся как есть."""
    from core.api.schemas import EventIn
    e = EventIn(title=TITLE, start="2026-10-06T10:59")
    assert e.start == datetime(2026, 10, 6, 10, 59)
    assert e.start.tzinfo is None


def test_aware_time_becomes_local_wall_clock():
    """Момент с зоной откатывается в локальные часы, а не пишется «как есть без зоны».

    Ожидание считаем от зоны самой машины: в Москве это 10:59, на сервере в UTC — 07:59.
    Старое поведение (просто отбросить зону) давало бы 07:59 везде и тут бы не прошло.
    """
    from core.api.schemas import EventIn
    e = EventIn(title=TITLE, start=WALL)
    assert e.start == WALL.astimezone().replace(tzinfo=None)
    assert e.start.tzinfo is None


def test_api_update_moves_event_and_linked_task_together():
    """Путь целиком: тело PUT /api/events → событие → срок привязанной задачи."""
    from core.api.routers.tasks import update_event as put_event
    from core.api.schemas import EventIn
    from core.services import calendar, tasks

    t = tasks.add_task(TITLE, due=datetime(2026, 10, 6, 9, 0))
    ev = calendar.add_event(TITLE, datetime(2026, 10, 6, 9, 0), task_id=t.id)

    want = WALL.astimezone().replace(tzinfo=None)
    # task_id шлём обязательно — веб его передаёт, а PUT перезаписывает привязки целиком
    put_event(ev.id, EventIn(title=ev.title, start=WALL, task_id=t.id))

    assert calendar.find_event(ev.id).start == want
    assert tasks.find_task(t.id).due == want
