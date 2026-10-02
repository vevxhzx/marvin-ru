"""Надёжность ночной уборки: ретеншн по retention.*, чистка кэшей, компактификация БД
и регистрация задач `retention` / `db_compact` в планировщике.

Всё на временной БД (`fresh_db`): настоящие data/jarvis.db и config.yaml не трогаются —
настройки retention подменяются через monkeypatch на объект cfg."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta


def _seed(days_old: int):
    """Старая и свежая запись в каждую растущую таблицу + Memory/Fact (их чистить нельзя)."""
    from core.db import ActionLog, ChatMessage, Fact, Lesson, Memory, Session, engine

    old = datetime.now() - timedelta(days=days_old)
    with Session(engine, expire_on_commit=False) as s:
        s.add(ChatMessage(role="user", text="старый", created_at=old))
        s.add(ChatMessage(role="user", text="свежий"))
        s.add(ActionLog(kind="add_task", ref_table="task", ref_id=1, created_at=old))
        s.add(ActionLog(kind="add_task", ref_table="task", ref_id=2))
        s.add(Lesson(text="старый урок", kind="task", created_at=old))
        s.add(Lesson(text="свежий урок", kind="task"))
        s.add(Memory(kind="event", text="старое событие", created_at=old))
        s.add(Fact(text="старый факт", layer="long", created_at=old))
        s.commit()


def _count(model) -> int:
    from sqlalchemy import func, select
    from core.db import Session, engine
    with Session(engine, expire_on_commit=False) as s:
        return s.execute(select(func.count()).select_from(model)).scalar()


# ---------------------------------------------------------------- 1. выключено по умолчанию
def test_retention_disabled_without_config(fresh_db, monkeypatch):
    """Без retention.* в config.yaml (значение по умолчанию) ничего не удаляется."""
    from core import config as cfgmod
    from core.db import ActionLog, ChatMessage, Fact, Lesson, Memory
    from core.services import scheduler

    monkeypatch.setattr(cfgmod.cfg, "retention", None, raising=False)
    _seed(days_old=400)
    assert scheduler.retention_cleanup() == {}
    for m in (ChatMessage, ActionLog, Lesson):   # по две строки в каждой растущей таблице
        assert _count(m) == 2, f"{m.__name__}: при выключенном ретеншне строки должны остаться"
    for m in (Memory, Fact):                     # по одной — их ретеншн вообще не трогает
        assert _count(m) == 1, f"{m.__name__}: память и знания не удаляются"


# ---------------------------------------------------------------- 2. ретеншн по retention.*
def test_retention_respects_days_and_spares_memory_fact(fresh_db, monkeypatch):
    """chat_days удаляет только старый чат, lesson_days — старый урок; action_days=0 выключает
    таблицу; Memory и Fact не трогаются никогда."""
    from core import config as cfgmod
    from core.db import ActionLog, ChatMessage, Fact, Lesson, Memory
    from core.services import scheduler

    monkeypatch.setattr(cfgmod.cfg, "retention",
                        {"chat_days": 30, "action_days": 0, "lesson_days": 10}, raising=False)
    _seed(days_old=400)

    res = scheduler.retention_cleanup()
    assert res == {"chat_days": 1, "lesson_days": 1}, f"неожиданный результат: {res}"
    # старое удалено, свежее осталось
    assert _count(ChatMessage) == 1
    assert _count(Lesson) == 1
    # action_days=0 → таблица не чистится, несмотря на 400-дневные строки
    assert _count(ActionLog) == 2
    # память и знания о хозяине — неприкосновенны
    assert _count(Memory) == 1 and _count(Fact) == 1

    # повторный запуск: удалять уже нечего (идемпотентно)
    assert scheduler.retention_cleanup() == {}


# ---------------------------------------------------------------- 3. чистка кэшей
def test_clean_caches_by_age_then_size(monkeypatch, tmp_path):
    """Сначала всё старше лимита по возрасту, потом лишнее по размеру (старые файлы первыми)."""
    from core import config as cfgmod
    from core.services import scheduler

    data = tmp_path / "data"
    cards = data / "card_cache"
    tmpd = data / "tmp"
    cards.mkdir(parents=True)
    tmpd.mkdir(parents=True)
    old_f = cards / "old.png"
    fresh_f = cards / "fresh.png"
    old_f.write_bytes(b"x")
    fresh_f.write_bytes(b"y")
    ts = datetime.now().timestamp() - 40 * 86400
    os.utime(old_f, (ts, ts))
    for i in range(3):
        (tmpd / f"f{i}.tmp").write_bytes(b"z" * 10)

    monkeypatch.setattr(cfgmod, "DATA_DIR", data)
    # возраст 30 дней для card_cache; лимит 0 МБ для tmp — весь свежий «хвост» уходит по размеру
    monkeypatch.setattr(scheduler, "_CACHE_RULES", (("card_cache", 30, 500), ("tmp", 7, 0)))

    res = scheduler.clean_caches()
    assert res.get("card_cache") == 1, "400-дневного старика надо убрать по возрасту"
    assert not old_f.exists() and fresh_f.exists(), "свежий файл по возрасту не трогаем"
    assert res.get("tmp") == 3 and not any(tmpd.iterdir()), "лимит 0 МБ — весь tmp убран"
    # каталогов больше нет — выходим молча
    assert scheduler.clean_caches() == {}


# ---------------------------------------------------------------- 4. компактификация
def test_db_compact_ok(fresh_db):
    from core.services import scheduler

    res = scheduler.db_compact()
    assert res["ok"] is True and res["result"] == "ok"
    assert res["checkpoint"], "wal_checkpoint(TRUNCATE) должен вернуть результат"


# ---------------------------------------------------------------- 5. задачи в планировщике
def test_build_registers_nightly_jobs(fresh_db):
    from core.services import scheduler

    async def notify(text, buttons=None):
        pass

    sch = scheduler.build(notify)
    jobs = {j.id: j for j in sch.get_jobs()}
    assert "retention" in jobs and "db_compact" in jobs, "ночные задачи уборки не зарегистрированы"

    def cron(job):
        return {f.name: str(f) for f in job.trigger.fields}

    r = cron(jobs["retention"])
    assert (r["hour"], r["minute"]) == ("4", "20"), f"ретеншн — в 04:20, получено {r}"
    c = cron(jobs["db_compact"])
    assert (c["day_of_week"], c["hour"], c["minute"]) == ("sun", "4", "30"), \
        f"компактификация — вс 04:30, получено {c}"

    # обёртки действительно вызывают наши функции (подменяем — ночная уборка не ходит по дискам)
    called = []
    orig_ret, orig_cc, orig_dc = scheduler.retention_cleanup, scheduler.clean_caches, scheduler.db_compact
    try:
        scheduler.retention_cleanup = lambda: called.append("retention") or {}
        scheduler.clean_caches = lambda: called.append("caches") or {}
        scheduler.db_compact = lambda: called.append("compact") or {"ok": True}
        asyncio.run(jobs["retention"].func())
        asyncio.run(jobs["db_compact"].func())
    finally:
        scheduler.retention_cleanup, scheduler.clean_caches, scheduler.db_compact = orig_ret, orig_cc, orig_dc
    assert called == ["retention", "caches", "compact"], f"задачи вызвали не то: {called}"
