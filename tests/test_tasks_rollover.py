"""Автоперенос задач на следующий день (TDD).

Флаг Task.auto_roll: задача с флагом, не закрытая к ночи, сама переезжает
на завтра. Без флага — только вечерний вопрос (existing evening_review).
"""
import os
from datetime import datetime, timedelta

os.environ.setdefault("ASSISTANT_TEST", "1")

import pytest  # noqa: E402

from core import db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from sqlmodel import create_engine
    from sqlalchemy import event
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


NOW = datetime(2026, 10, 10, 1, 0)  # суббота ночью (после пятницы)


def test_add_task_saves_auto_roll_flag():
    from core.services import tasks
    t = tasks.add_task("Полить цветы", datetime(2026, 10, 9, 23, 59), auto_roll=True)
    assert t.auto_roll is True
    t2 = tasks.add_task("Обычное дело", datetime(2026, 10, 9, 23, 59))
    assert t2.auto_roll is False


def test_update_task_toggles_auto_roll():
    from core.services import tasks
    t = tasks.add_task("Переключатель", datetime(2026, 10, 9, 23, 59))
    assert tasks.update_task(t.id, auto_roll=True).auto_roll is True
    assert tasks.update_task(t.id, auto_roll=False).auto_roll is False


def test_rollover_moves_only_overdue_flagged():
    from core.services import tasks
    yesterday_all = tasks.add_task("Вчера весь день", datetime(2026, 10, 9, 23, 59), auto_roll=True)
    yesterday_timed = tasks.add_task("Вчера в 15", datetime(2026, 10, 9, 15, 0), auto_roll=True)
    old = tasks.add_task("Старая", datetime(2026, 10, 8, 10, 0), auto_roll=True)
    noflag = tasks.add_task("Без флага просрочена", datetime(2026, 10, 9, 23, 59))
    today = tasks.add_task("Сегодняшняя", datetime(2026, 10, 10, 23, 59), auto_roll=True)
    today_timed = tasks.add_task("Сегодня в 10", datetime(2026, 10, 10, 10, 0), auto_roll=True)
    done = tasks.add_task("Закрытая вчера", datetime(2026, 10, 9, 23, 59), auto_roll=True)
    tasks.update_task(done.id, done=True)

    moved = tasks.rollover_overdue(NOW)
    ids = {t.id for t in moved}
    assert yesterday_all.id in ids
    assert yesterday_timed.id in ids
    assert old.id in ids
    assert noflag.id not in ids
    assert today.id not in ids
    assert today_timed.id not in ids
    assert done.id not in ids

    with db.session() as s:
        a = s.get(db.Task, yesterday_all.id)
        assert (a.due.day, a.due.hour, a.due.minute) == (11, 23, 59), a.due  # all-day stays all-day
        b = s.get(db.Task, yesterday_timed.id)
        assert (b.due.day, b.due.hour, b.due.minute) == (11, 15, 0), b.due  # timed keeps time
        c = s.get(db.Task, old.id)
        assert c.due.date() == datetime(2026, 10, 11).date(), c.due
        n = s.get(db.Task, noflag.id)
        assert n.due == datetime(2026, 10, 9, 23, 59)
        assert a.remind_stage == 0


def test_rollover_is_idempotent_and_skips_done():
    from core.services import tasks
    t = tasks.add_task("Идемпотент", datetime(2026, 10, 9, 23, 59), auto_roll=True)
    first = tasks.rollover_overdue(NOW)
    assert {x.id for x in first} == {t.id}
    with db.session() as s:
        due1 = s.get(db.Task, t.id).due
    second = tasks.rollover_overdue(NOW)
    assert second == []
    with db.session() as s:
        assert s.get(db.Task, t.id).due == due1
    # закрыли — больше не едет даже на следующий день
    tasks.update_task(t.id, done=True)
    third = tasks.rollover_overdue(NOW + timedelta(days=1))
    assert third == []


def test_rollover_writes_journal():
    from sqlmodel import select
    from core.services import tasks
    t = tasks.add_task("Журнал", datetime(2026, 10, 9, 10, 0), auto_roll=True)
    tasks.rollover_overdue(NOW)
    with db.session() as s:
        mem = s.exec(select(db.Memory).where(db.Memory.ref_table == "task", db.Memory.ref_id == t.id)
                     .order_by(db.Memory.id.desc())).first()
    assert mem is not None and "автоперенос" in mem.text.lower()
