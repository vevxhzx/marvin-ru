"""Память: ночная уборка слоёв и разбор важности (ядро)."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import select

from ...db import Fact, session

from .extract import _ask, _cloud_sees_stored
from .portrait import rebuild_portrait, rebuild_style
from .store import (
    CORE_MAX, IMPORTANCE_PROMPT, PROMOTE_PROMPT, UNUSED_DAYS, decay_days,
    decay_max_mentions, enabled, fact_meta, index_pending, log,
    set_fact_meta, short_days,
)



async def nightly() -> dict:
    """Уборка: short старше N дней → long/archive (нейронка; без неё — long, если факт всплывал повторно, иначе archive);
    long без единого использования за 60 дней и не ядро → archive; портрет раз в неделю.
    Плюс затухание: неподтверждённые, старше decay_days и почти не упоминавшиеся → archive («затухло»)."""
    if not enabled():
        return {}
    await index_pending()
    cutoff = datetime.now() - timedelta(days=short_days())
    with session() as s:
        old_short = list(s.exec(select(Fact).where(Fact.layer == "short", Fact.created_at < cutoff)))
    promoted = archived = 0
    stamp_archived: list[int] = []   # id, которым проставим archived_at ПОСЛЕ коммита (вложенная сессия — это deadlock)
    if old_short:
        hide_private = await _cloud_sees_stored()
        shown = [f for f in old_short if not (hide_private and f.is_private)]
        d, via = await _ask(PROMOTE_PROMPT, "\n".join(f"[{f.id}] {f.text}" for f in shown))
        keep: set[int] = set()
        if hide_private:
            # спрятанные от облака приватные модель не видела — вслепую не архивируем, оставляем
            keep |= {f.id for f in old_short if f.is_private}
        if d is not None:
            for x in d.get("keep") or []:
                try:
                    keep.add(int(str(x).strip("[] ")))
                except ValueError:
                    pass
        else:
            keep = {f.id for f in old_short if f.uses >= 2 or f.updated_at > f.created_at + timedelta(hours=1)}
        with session() as s:
            for f in old_short:
                row = s.get(Fact, f.id)
                if not row:
                    continue
                if row.id in keep:
                    row.layer = "long"; promoted += 1
                else:
                    row.layer, row.archive_reason = "archive", "устарело"; archived += 1; stamp_archived.append(row.id)
                row.updated_at = datetime.now(); s.add(row)
            s.commit()
    stale = datetime.now() - timedelta(days=UNUSED_DAYS)
    with session() as s:
        for f in s.exec(select(Fact).where(Fact.layer == "long", Fact.core == False, Fact.created_at < stale)):  # noqa: E712
            if not f.last_used and f.uses == 0:
                f.layer, f.archive_reason, f.updated_at = "archive", "не пригодился", datetime.now()
                s.add(f); archived += 1; stamp_archived.append(f.id)
        s.commit()
    # --- затухание: неподтверждённый факт, который за год почти не вспоминали, уходит в архив
    now = datetime.now()
    fade_cut = now - timedelta(days=decay_days())
    max_mentions = decay_max_mentions()
    with session() as s:
        live = list(s.exec(select(Fact).where(Fact.layer != "archive", Fact.core == False)))
    meta = fact_meta()
    faded = 0
    for f in live:
        m = meta.get(f.id) or {}
        if m.get("confirmed") is not None:
            continue                       # подтверждён («да» в тосте / восстановление) — не гаснет
        ref = m.get("last_seen") or f.created_at
        if ref <= fade_cut and f.uses < max_mentions:
            with session() as s:
                row = s.get(Fact, f.id)
                if row and row.layer != "archive":
                    row.layer, row.archive_reason, row.updated_at = "archive", "затухло", now
                    s.add(row); s.commit()
                    archived += 1; faded += 1; stamp_archived.append(f.id)
    for fid in dict.fromkeys(stamp_archived):   # без дублей: факт мог попасть в два прохода
        set_fact_meta(fid, archived=now)
    # разбор важности — внутри ночи, отдельной кнопки нет; счёт в логе, наружу не тянем
    await review_importance()
    await rebuild_portrait()
    await rebuild_style()
    return {"promoted": promoted, "archived": archived}


async def review_importance() -> int:
    """Ночной разбор важности: нейронка смотрит живые факты и помечает ядром самые
    устойчивые (предпочтения, люди, здоровье) — такие не гаснут никогда. Только
    добавляет (свободные слоты до CORE_MAX), существующее ядро не трогает."""
    if not enabled():
        return 0
    with session() as s:
        core_now = [f for f in s.exec(select(Fact).where(Fact.layer != "archive", Fact.core == True)).all()]  # noqa: E712
        cands = list(s.exec(select(Fact).where(Fact.layer != "archive", Fact.core == False)  # noqa: E712
                            .order_by(Fact.created_at)).all())
    free = CORE_MAX - len(core_now)
    if free <= 0 or not cands:
        return 0
    if await _cloud_sees_stored():
        cands = [f for f in cands if not f.is_private]   # замок: приватное в облако не уходит
        if not cands:
            return 0
    lines = [f"[{f.id}] {f.text} ({f.category})" for f in cands[:60]]
    d, via = await _ask(IMPORTANCE_PROMPT.format(n=min(free, 6)), "\n".join(lines))
    want: list[int] = []
    for x in (d.get("core") if isinstance(d, dict) else None) or []:
        try:
            want.append(int(str(x).strip("[] ")))
        except ValueError:
            continue
    by_id = {f.id: f for f in cands}
    n = 0
    with session() as s:
        for fid in want[:free]:
            row = s.get(Fact, fid)
            if row and not row.core and row.layer != "archive" and row.id in by_id:
                row.core, row.updated_at = True, datetime.now()
                s.add(row); n += 1
        s.commit()
    if n:
        log.info("важность: ядром помечено %d фактов (%s)", n, via)
    return n
