"""Планировщик: напоминания о событиях, утренний дайджест, регулярные платежи, бэкапы."""
from __future__ import annotations

import asyncio

import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..config import DB_PATH, ROOT, cfg
from ..brain.dates import is_all_day
from ..services import calendar, finance, tasks
from ..services.finance import money
from ..db import get_setting, set_setting

log = logging.getLogger("assistant.sched")
Notifier = Callable[[str], Awaitable[None]]


def morning_facts() -> dict:
    """Факты утра одним словарём — для живой первой строки (persona.opener). Без сумм и балансов."""
    from ..brain.dates import is_all_day
    d = datetime.now()
    evs = calendar.events_today()
    ts = tasks.list_tasks(limit=50)
    today = [t for t in ts if t.due and t.due.date() <= d.date()]
    return {"when": "утро", "weekday": ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][d.weekday()],
            "events": [f"{e.start:%H:%M} {e.title}" for e in evs[:4]],
            "day_tasks": [t.title for t in today if is_all_day(t.due)][:5],
            "overdue": [t.title for t in today if t.due.date() < d.date()][:3],
            "open_tasks": len(ts)}


def morning_digest_text(head: str | None = None) -> str:
    """Короткий утренний текст: подпись к картинке (и запасной вариант, если картинка не собралась).
    head — живая первая строка от персоны; без неё — нейтральное приветствие."""
    d = datetime.now()
    wd = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][d.weekday()]
    addr = (getattr(getattr(cfg, "owner", None), "name", None) or "сэр").strip().lower()
    lines = [f"☀️ {head}" if head else f"☀️ Доброе утро, {addr}. {wd.capitalize()}, {d:%d.%m}."]
    evs = calendar.events_today()
    if evs:
        first = evs[0]
        more = f" и ещё {len(evs) - 1}" if len(evs) > 1 else ""
        lines.append(f"📅 {first.start:%H:%M} — {first.title}{more}.")
    else:
        lines.append("📅 Встреч нет. Подозрительно спокойно.")
    ts = tasks.list_tasks(limit=50)
    if ts:
        today = [t for t in ts if t.due and t.due.date() <= d.date()]
        lines.append(f"✅ Задач: {len(ts)}" + (f", с дедлайном сегодня — {len(today)}." if today else "."))
        # дела «на день» (без времени) — по именам: отдельных напоминаний по ним не будет, это единственное место утром
        day = [t for t in today if is_all_day(t.due)]
        if day:
            lines.append("📋 На сегодня: " + ", ".join(t.title for t in day[:5]) + (f" и ещё {len(day) - 5}" if len(day) > 5 else "") + ".")
    pays = finance.upcoming_payments(3)
    if pays:
        lines.append(f"💳 Платежей на днях: {len(pays)} на {money(sum(p.amount for p in pays))}.")
    try:
        from . import orders
        for n in orders.deadline_nudges()[:3]:
            lines.append(n)
        from . import pulse
        lines += pulse.late_lines(2)
        from . import people
        for pt in people.people_today()[:2]:
            if pt.get("hint"):
                lines.append(pt["hint"])
    except Exception as e:  # pragma: no cover
        log.debug("orders nudges: %s", e)
    try:
        from . import aims
        f = aims.focus()
        if f["items"]:
            lines.append("🎯 Фокус: " + "; ".join(p["title"] for p in f["items"][:2]) + f" — к цели «{f['items'][0]['aim']}».")
        for a in aims.stale_aims()[:1]:
            lines.append(f"🎯 «{a.title}» стоит уже давно — либо шаг, либо честно закрыть.")
    except Exception as e:  # pragma: no cover
        log.debug("aims focus: %s", e)
    s = finance.summary(1)
    safe = s.get("safe") or {}
    tail = f"💰 Баланс {money(s['total_balance'])}"
    if safe.get("per_day") is not None:
        tail += f" · можно тратить {money(safe['per_day'])} в день"
    lines.append(tail + ".")
    return "\n".join(lines)


def _backup_dir() -> Path:
    return (ROOT / cfg.backup.dir).resolve() if not Path(cfg.backup.dir).is_absolute() else Path(cfg.backup.dir)


def backup_db(force: bool = False) -> Path | None:
    """Снимок базы. force=True — кнопка «бэкап сейчас» даже если ночной выключен."""
    if (not force and not cfg.backup.enabled) or not DB_PATH.exists():
        return None
    bdir = _backup_dir()
    bdir.mkdir(parents=True, exist_ok=True)
    dst = bdir / f"backup-{datetime.now():%Y%m%d-%H%M}.db"
    # безопасная копия SQLite через backup API
    import sqlite3
    src = sqlite3.connect(DB_PATH)
    out = sqlite3.connect(dst)
    with out:
        src.backup(out)
    out.close(); src.close()
    # чистим старые
    cutoff = datetime.now() - timedelta(days=int(cfg.backup.keep_days))
    for f in bdir.glob("backup-*.db"):
        if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
            f.unlink(missing_ok=True)
    # вторая копия — на другой диск / в папку облака (Яндекс.Диск, Google Drive), если указана
    extra = getattr(cfg.backup, "extra_dir", None)
    if extra:
        try:
            edir = Path(extra)
            edir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dst, edir / dst.name)
            for f in edir.glob("backup-*.db"):
                if datetime.fromtimestamp(f.stat().st_mtime) < cutoff:
                    f.unlink(missing_ok=True)
        except Exception as e:  # pragma: no cover
            log.warning("extra backup failed: %s", e)
    # картинки заметок/чеков (data/media): без них восстановленная база ссылается в пустоту.
    # Копируем зеркалом в backups/media — только новые/изменённые файлы, поэтому дёшево даже при тысячах фото.
    try:
        n = _sync_media(bdir / "media")
        if extra:
            _sync_media(Path(extra) / "media")
        if n:
            log.info("backup media: +%d файлов", n)
    except Exception as e:  # pragma: no cover
        log.warning("media backup failed: %s", e)
    log.info("backup -> %s", dst)
    return dst


def _sync_media(dst_dir: Path) -> int:
    """Зеркало data/media → dst_dir: копируются файлы, которых нет или которые отличаются размером/временем. Ничего не удаляет."""
    from .brain_notes import MEDIA_DIR
    if not MEDIA_DIR.exists():
        return 0
    copied = 0
    for src in MEDIA_DIR.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(MEDIA_DIR)
        dst = dst_dir / rel
        try:
            st = src.stat()
            if dst.exists():
                dt = dst.stat()
                if dt.st_size == st.st_size and int(dt.st_mtime) >= int(st.st_mtime):
                    continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied += 1
        except Exception as e:  # pragma: no cover
            log.warning("media copy %s: %s", rel, e)
    return copied


def _quiet_now() -> bool:
    """Тихие часы для инициативных уведомлений. notifications.quiet_from / quiet_to в config.yaml (часы, 0–23)."""
    n = getattr(cfg, "notifications", None)
    try:
        start = int(getattr(n, "quiet_from", 23) if getattr(n, "quiet_from", 23) is not None else 23) % 24
        end = int(getattr(n, "quiet_to", 8) if getattr(n, "quiet_to", 8) is not None else 8) % 24
    except (TypeError, ValueError):
        start, end = 23, 8
    h = datetime.now().hour
    if start == end:
        return False
    return (h >= start or h < end) if start > end else (start <= h < end)


def last_backup() -> dict:
    """Когда был последний бэкап и где лежит (для статуса в настройках)."""
    bdir = _backup_dir()
    files = sorted(bdir.glob("backup-*.db"), key=lambda f: f.stat().st_mtime) if bdir.exists() else []
    # pre-restore — служебные, в «последний» не считаем
    files = [f for f in files if not f.name.startswith("backup-pre-restore-")]
    if not files:
        return {"enabled": bool(cfg.backup.enabled), "last": None, "dir": str(bdir), "count": 0, "extra_dir": getattr(cfg.backup, "extra_dir", None) or None}
    f = files[-1]
    return {"enabled": bool(cfg.backup.enabled), "last": datetime.fromtimestamp(f.stat().st_mtime).isoformat(), "dir": str(bdir),
            "count": len(files), "size": f.stat().st_size, "extra_dir": getattr(cfg.backup, "extra_dir", None) or None}


_BACKUP_NAME_RX = __import__("re").compile(r"^backup-(?:pre-restore-)?\d{8}-\d{4}\.db$")


def list_backups(limit: int = 40) -> list[dict]:
    """Список файлов backup-*.db (новые сверху) — для «восстановить» в настройках."""
    bdir = _backup_dir()
    if not bdir.exists():
        return []
    out = []
    for f in sorted(bdir.glob("backup-*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not _BACKUP_NAME_RX.match(f.name):
            continue
        st = f.stat()
        out.append({
            "name": f.name,
            "at": datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
            "size": st.st_size,
            "pre_restore": f.name.startswith("backup-pre-restore-"),
        })
        if len(out) >= limit:
            break
    return out


def restore_backup(name: str) -> dict:
    """Подменить data/assistant.db выбранным снимком. Текущая база → backup-pre-restore-… .
    Картинки (data/media) не откатываются по дате — зеркало media в backups/ актуально «как сейчас».
    После вызова нужен перезапуск ядра: открытые SQLite-соединения держат старый файл."""
    name = (name or "").strip()
    if not _BACKUP_NAME_RX.match(name) or ".." in name or "/" in name or "\\" in name:
        raise ValueError("Неверное имя бэкапа")
    bdir = _backup_dir()
    src = (bdir / name).resolve()
    if not str(src).startswith(str(bdir.resolve())) or not src.is_file():
        raise LookupError("Такого бэкапа нет")
    bdir.mkdir(parents=True, exist_ok=True)
    safety = None
    if DB_PATH.exists():
        safety = bdir / f"backup-pre-restore-{datetime.now():%Y%m%d-%H%M}.db"
        # безопасная копия через sqlite backup API (на случай WAL)
        import sqlite3
        s = sqlite3.connect(DB_PATH)
        o = sqlite3.connect(safety)
        with o:
            s.backup(o)
        o.close(); s.close()
    # подмена: сначала во временный, потом replace — атомарнее на одном томе
    tmp = DB_PATH.with_suffix(".db.restoring")
    shutil.copy2(src, tmp)
    tmp.replace(DB_PATH)
    # рядом лежат -wal/-shm от старой сессии — иначе SQLite может подмешать старый журнал
    for suf in ("-wal", "-shm"):
        p = Path(str(DB_PATH) + suf)
        p.unlink(missing_ok=True)
    log.info("restore backup %s → %s (safety %s)", name, DB_PATH, safety.name if safety else "—")
    return {
        "ok": True,
        "restored": name,
        "safety": safety.name if safety else None,
        "needs_restart": True,
        "dir": str(bdir),
    }


def build(notify: Notifier) -> AsyncIOScheduler:
    # misfire_grace_time: ПК спал/ноут был закрыт — задача, пропущенная меньше чем на час, всё равно выполнится один раз
    # (coalesce), а не молча пропадёт (по умолчанию у APScheduler 1 секунда) и не выстрелит пачкой.
    sch = AsyncIOScheduler(timezone=cfg.owner.timezone,
                           job_defaults={"misfire_grace_time": 3600, "coalesce": True, "max_instances": 1})
    # «через N секунд после старта» — с часовым поясом планировщика, иначе на ПК с другим системным TZ задачи считаются «пропущенными»
    from datetime import datetime as _dtm
    _tz = sch.timezone
    _soon = lambda sec: _dtm.now(_tz) + timedelta(seconds=sec)  # noqa: E731

    async def _send(text: str, buttons=None, channel: str = "text"):
        from ..brain import persona
        voice_fn = getattr(notify, "voice", None)
        if channel == "voice" and voice_fn:
            try:
                if await voice_fn(text, buttons):
                    persona.mark_voice_used()
                    return
            except Exception as e:  # pragma: no cover
                log.debug("voice notify: %s", e)
        try:
            await notify(text, buttons)  # type: ignore[call-arg]
        except TypeError:
            await notify(text)

    async def _notify(text: str, buttons=None, urgent: bool = False, kind: str = "", importance: int = 3, spend: bool = False):
        """Единая точка «сказать или промолчать» (0.10, attention.decide):
        · urgent — напоминание, которое человек сам поставил на это время: всегда и сразу;
        · importance 3 (по умолчанию) — плановые сводки (вечер, неделя, платежи): ночью не шлём, днём — сразу (как раньше);
        · importance 2 — инициатива (событие, повод, «пока тебя не было»): решает attention — сейчас / отложить до
          возвращения за ПК / молча, с учётом бюджета в день, занятости (рендер, игра) и того, что человек только сел;
        · importance 1 — мелочь: только если момент идеальный и бюджет не на исходе.
        spend=True — списать из дневного бюджета инициатив (proactive.tick списывает сам).
        kind — повод (evening / stale_task / late_pay …): по нему persona.choose_channel решает, не озвучить ли голосом."""
        from ..brain import attention, persona
        if urgent:
            await _send(text, buttons, persona.choose_channel(kind, text, True) if kind else "text")
            return
        if importance >= 3:
            if _quiet_now():
                log.info("тихие часы — пропускаю уведомление: %s", text[:60])
                return
            await _send(text, buttons, persona.choose_channel(kind, text, False) if kind else "text")
            return
        d = attention.decide(kind or "notify", importance, False, text=text)
        if d.verdict == "silent":
            log.info("молчу (%s): %s", d.why, text[:60])
            return
        if d.verdict == "later":
            nb = datetime.now() + timedelta(minutes=d.delay_min) if d.delay_min else None
            attention.defer(kind or "notify", text, importance, buttons, key=kind if importance >= 3 else "", not_before=nb)
            log.info("отложил (%s): %s", d.why, text[:60])
            return
        await _send(text, buttons, d.channel if kind else "text")
        if spend:
            attention.spend()

    def ping(kind, **payload):
        from ..brain import agent
        if agent.on_change:
            agent.on_change(kind, payload)

    async def reminders():
        for e in calendar.due_reminders():
            mins = max(0, int((e.start - datetime.now()).total_seconds() // 60))
            when = "уже сейчас" if mins == 0 else f"через {mins} мин"
            text = f"⏰ «{e.title}» — {when} ({e.start:%H:%M})" + (f", {e.location}" if e.location else "") + "."
            ping("reminder", text=text, id=f"ev{e.id}-{e.start:%Y%m%d%H%M}")
            await _notify(text, [("✅ Иду", f"ev:{e.id}:ok"), ("⏰ +1 час", f"ev:{e.id}:hour"), ("📅 Завтра", f"ev:{e.id}:tomorrow")], urgent=True)

    async def task_reminders():
        for t, text in tasks.due_task_reminders():
            ping("reminder", text=text, id=f"task{t.id}-{t.remind_stage}")
            await _notify(text, [("✅ Сделал", f"task:{t.id}:done"), ("⏰ +1 час", f"task:{t.id}:hour"), ("📅 Завтра", f"task:{t.id}:tomorrow")], urgent=True)

    async def semantic_job():
        from . import relations, semantic
        from ..brain import llm
        if llm.user_recent() and not llm.cloud_enabled():
            return   # человек в чате, а связи считала бы та же локальная модель — не встаём в очередь перед ним
        try:
            await semantic.index_pending()
        except Exception as e:  # pragma: no cover
            log.warning("semantic index failed: %s", e)
        try:
            from . import judge, memory
            await memory.index_pending()
            await judge.index_pending()
        except Exception as e:  # pragma: no cover
            log.warning("memory index failed: %s", e)
        try:
            # связи — по 3 записи за проход (раз в 10 минут): новая заметка получает «связано:» в пределах четверти часа,
            # старые пересчитываются постепенно, не упираясь в лимиты облака
            await relations.job(3)
        except Exception as e:  # pragma: no cover
            log.warning("relations job failed: %s", e)

    async def gcal_flush():
        from . import gcal
        try:
            n = await gcal.flush_queue()
            if n:
                log.info("Google Календарь: досинхронизировано %d", n)
        except Exception as e:  # pragma: no cover
            log.warning("gcal flush failed: %s", e)

    async def recurring():
        for r in finance.process_due_recurring():
            ping("recurring")
            await _notify(f"💳 Провёл регулярный платёж: «{r.title}» {money(r.amount)}. Следующий {r.next_date:%d.%m}.")

    async def _photo(path, caption):
        """Картинка владельцу, если notify умеет (атрибут .photo); иначе — текст."""
        fn = getattr(notify, "photo", None)
        if fn and path:
            try:
                await fn(str(path), caption)
                return True
            except Exception as e:
                log.warning("photo notify failed: %s", e)
        return False

    async def digest():
        from . import cards, insights
        from ..brain import persona
        try:
            head = await persona.opener(morning_facts(), "")
        except Exception as e:  # pragma: no cover
            log.debug("morning opener: %s", e); head = ""
        text = morning_digest_text(head or None)
        bd = insights.upcoming_birthdays(0)
        if bd:
            text += "\n🎂 Сегодня " + ", ".join(b["title"] for b in bd) + "!"
        path = await asyncio.to_thread(cards.morning_card)
        if not await _photo(path, text):
            await notify(text)

    async def weekly_card():
        from . import cards
        path = await asyncio.to_thread(cards.report_card, 7)
        await _photo(path, "📊 Итоги недели, сэр.")

    async def monthly_card():
        from . import cards
        path = await asyncio.to_thread(cards.report_card, 30)
        await _photo(path, "📊 Итоги месяца, сэр. Цифры не врут — в отличие от ощущений.")

    from . import state as _state

    @_state.tracked("бэкап базы")
    async def backup():
        backup_db()

    async def polish_job():
        from . import polish
        from ..brain import llm
        if llm.user_recent():
            return   # уборка заметок идёт на локальной модели — через 5 минут попробует снова
        try:
            await polish.polish_pending()
        except Exception as e:  # pragma: no cover
            log.warning("polish failed: %s", e)

    async def evening_budget():
        from . import insights
        for text in insights.budget_alerts():
            ping("reminder", text=text, id=f"budget-{hash(text)}")
            await _notify(text)

    async def weekly():
        from . import insights, trace
        try:
            txt = await insights.weekly_digest()
        except Exception as e:  # pragma: no cover
            log.warning("weekly digest failed: %s", e); return
        try:
            # раз в неделю ассистент сам докладывает, где тупил (молчит, если неделя была спокойной)
            txt = (txt or "") + "\n".join(trace.weekly_block())
        except Exception as e:  # pragma: no cover
            log.warning("trace weekly block failed: %s", e)
        if txt:
            await notify(txt)

    async def monthly_subs():
        from . import insights
        try:
            txt = insights.subscriptions_nudge()
        except Exception as e:  # pragma: no cover
            log.warning("subs nudge failed: %s", e); return
        if txt:
            await notify(txt)

    async def birthdays():
        from . import insights
        from ..db import get_setting, set_setting
        for b in insights.upcoming_birthdays(3):
            key = f"bday_told:{b['id']}:{b['date'][:10]}"
            if get_setting(key):
                continue
            set_setting(key, "1")
            when = "сегодня" if b["in_days"] == 0 else "завтра" if b["in_days"] == 1 else f"через {b['in_days']} дн."
            text = (f"🎂 {when.capitalize()} — {b['title']}. Идеи подарка, если ещё не купили: что-то по его увлечению, "
                    f"впечатление (билеты, мастер-класс) или подарочная карта — беспроигрышно, хоть и скучно. Сказать «задача: купить подарок {b['who']}» — и я напомню.")
            ping("reminder", text=text, id=key)
            await _notify(text)

    async def self_check():
        """Самодиагностика (health.diagnose) раз в день: в лог всегда; в чат — только когда состояние ухудшилось
        (событие health_bad один раз на 6 часов), а не «всё ок» каждое утро."""
        from . import health
        try:
            res = await health.diagnose()
            log.info("Самопроверка: %s", res["text"].replace("\n", " · "))
            health.record(res)
        except Exception as e:  # pragma: no cover
            log.warning("self-check failed: %s", e)

    async def evening_review():
        """21:00 — итоги дня: короткая карточка (закрыто / потрачено / завтра) + под ней незакрытые дела с дедлайном,
        кнопки «сделал / завтра» под каждым. Не чаще раза в день (переживает перезапуск).
        Если день пустой (ничего не закрыто, не потрачено, дедлайнов нет) — молчим."""
        from . import cards
        key = f"evening_review:{datetime.now():%Y-%m-%d}"
        if get_setting(key):
            return
        if _quiet_now():
            return
        data = cards.evening_data()
        due = data["due"]
        if not due and not data["done"] and not data["spent"] and not data["earned"]:
            return
        set_setting(key, "1")
        from ..brain import persona
        try:
            facts = {"when": "вечер", "done": [t.title for t in data["done"][:5]], "due_left": [t.title for t in due[:5]],
                     "spent": bool(data["spent"]), "top_category": (data["top"][0] if data.get("top") else None),
                     "tomorrow": [f"{e.start:%H:%M} {e.title}" for e in data["tomorrow"][:3]]}
            first = await persona.opener(facts, "")
        except Exception as e:  # pragma: no cover
            log.debug("evening opener: %s", e); first = ""
        head = cards.evening_text(data, first or None)
        ping("reminder", text=head, id=key)
        path = await asyncio.to_thread(cards.evening_card, None, data)
        if first and persona.choose_channel("evening", head) == "voice":
            # вечерний итог голосом — как акцент дня; картинка ниже всё равно приходит
            await _notify(head, kind="evening")
            await _photo(path, "")
        elif not await _photo(path, head):
            await _notify(head)
        n = len(due)
        for t in due[:5]:
            when = "сегодня" if t.due.date() == datetime.now().date() else f"было {t.due:%d.%m}"
            await _notify(f"• «{t.title}» — {when}", [("✅ Сделал", f"task:{t.id}:done"), ("📅 Завтра", f"task:{t.id}:tomorrow")])
        if n > 5:
            await _notify(f"…и ещё {n - 5}. Полный список — «мои задачи».")

    async def timer_tick():
        """Помодоро истёк → одно сообщение всем каналам (сайт — тост, TG — кнопки, голос — озвучка через kind=reminder)."""
        from . import orders
        ev = orders.due_timer_ping()
        if not ev:
            return
        st = ev.get("settings") or {}
        if st.get("voice", True):
            ping("reminder", text="🍅 " + ev["text"], id=f"timer-{datetime.now():%Y%m%d%H%M%S}")
        ping("timer", done=ev.get("session_kind"), text=ev["text"], sound=st.get("sound", "bell"), volume=st.get("volume", 0.6), auto_break=ev.get("auto_break", False))
        oid = ev.get("order_id") or 0
        focus = st.get("focus", 25)
        if ev.get("session_kind") == "break":
            btns = [(f"▶ Ещё {focus}", f"pomo:{oid}:{focus}"), ("⏹ Хватит", "pomo:0:stop")]
        elif ev.get("auto_break"):
            btns = [(f"▶ Без перерыва, ещё {focus}", f"pomo:{oid}:{focus}"), ("⏹ Хватит", "pomo:0:stop")]
        else:
            btns = [(f"▶ Ещё {focus}", f"pomo:{oid}:{focus}"), (f"☕ Перерыв {ev.get('break_min', 5)}", f"pomo:{oid}:break"), ("⏹ Хватит", "pomo:0:stop")]
        await _notify("🍅 " + ev["text"], btns, urgent=True)

    async def payment_check():
        from . import goals
        try:
            text = goals.payment_alert()
        except Exception as e:  # pragma: no cover
            log.warning("payment check failed: %s", e); return
        if text:
            ping("reminder", text=text, id=f"payshort-{datetime.now():%Y%m%d}")
            await _notify(text)

    sch.add_job(timer_tick, "interval", seconds=20, id="timer_tick", next_run_time=_soon(20))
    sch.add_job(payment_check, CronTrigger(hour=10, minute=30), id="payment_check")
    sch.add_job(evening_review, CronTrigger(hour=21, minute=0), id="evening_review")
    sch.add_job(evening_budget, CronTrigger(hour=21, minute=2), id="evening_budget")
    sch.add_job(weekly, CronTrigger(day_of_week="sun", hour=19, minute=0), id="weekly_digest")
    sch.add_job(weekly_card, CronTrigger(day_of_week="sun", hour=19, minute=2), id="weekly_card")
    sch.add_job(monthly_card, CronTrigger(day=1, hour=11, minute=0), id="monthly_card")
    sch.add_job(monthly_subs, CronTrigger(day=1, hour=12, minute=0), id="monthly_subs")
    sch.add_job(birthdays, CronTrigger(hour=10, minute=0), id="birthdays")
    sch.add_job(self_check, CronTrigger(hour=9, minute=5), id="self_check")
    sch.add_job(reminders, "interval", minutes=1, id="reminders")
    sch.add_job(task_reminders, "interval", minutes=5, id="task_reminders", next_run_time=_soon(30))
    sch.add_job(semantic_job, "interval", minutes=10, id="semantic", next_run_time=_soon(90))
    sch.add_job(polish_job, "interval", minutes=5, id="polish", next_run_time=_soon(40))
    sch.add_job(recurring, "interval", hours=1, id="recurring", next_run_time=_soon(20))
    @_state.tracked("ночная уборка памяти")
    async def memory_nightly():
        from . import memory, trace
        res = await memory.nightly()
        if res:
            log.info("память: уборка %s", res)
        try:
            n = trace.cleanup()
            if n:
                log.info("журнал работы: удалено %d старых строк", n)
        except Exception as e:  # pragma: no cover
            log.warning("trace cleanup failed: %s", e)

    async def proactive_tick():
        """Раз в час: один повод из proactive.candidates — не в тихие часы, не больше лимита в день."""
        from . import proactive
        try:
            c = await proactive.tick(quiet=_quiet_now())
        except Exception as e:  # pragma: no cover
            log.warning("proactive failed: %s", e); return
        if c:
            ping("reminder", text=c["text"], id="pro-" + c["key"])
            await _notify("💡 " + c["text"], c.get("buttons"), kind=str((c.get("fact") or {}).get("kind") or "proactive"), importance=2)

    async def presence_tick():
        """Раз в минуту: нет пульса → offline; человек за ПК и «отогрелся» → отдать отложенное (attention.due)."""
        from . import state
        from ..brain import attention
        _loop_box["loop"] = asyncio.get_running_loop()
        try:
            state.offline_check()
            sn = state.snapshot()
            if sn["presence"] != "active" or (sn.get("session_min") or 0) < 2 or _quiet_now():
                return
            items = attention.due()
            if not items:
                return
            if len(items) >= 3:
                # пачка — одним сообщением, а не очередью пингов
                body = "\n".join("· " + i["text"].lstrip("💡 ") for i in items)
                await _notify("Пока тебя не было:\n" + body, None, kind="catchup", importance=3)
                attention.spend()
                return
            for i in items:
                await _notify(i["text"], i.get("buttons") or None, kind=i.get("kind") or "", importance=i.get("importance", 2), spend=i.get("importance", 2) < 3)
        except Exception as e:  # pragma: no cover
            log.warning("presence tick: %s", e)

    _loop_box: dict = {}   # цикл событий планировщика — события (events.emit) прилетают и из потоков API

    def _fire(coro):
        loop = _loop_box.get("loop")
        if loop is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                coro.close(); return
        loop.call_soon_threadsafe(lambda: loop.create_task(coro))

    def _on_event(e):
        """Реакции на события (events.emit) — что из них вообще стоит озвучивать. Остальное живёт в ленте."""
        from . import state
        if (e.kind == "background_done" and e.data.get("announce")) or e.kind == "background_failed":
            name = e.data.get("job", "работа")
            txt = (f"«{name}» — готово." if e.kind == "background_done" else f"Фоновая работа «{name}» упала: {e.data.get('error', '')[:120]}")
            ping("reminder", text=txt, id=f"job-{name}")
            _fire(_notify(txt, None, kind="job", importance=2, spend=True))
        elif e.kind == "restart" and e.data.get("gap_min", 0) >= 10:
            pend = state.snapshot().get("pending")
            if pend:
                txt = f"Перезапустился (не было {e.data['gap_min']} мин). Висело без ответа: {pend}. Актуально ещё?"
                _fire(_notify(txt, None, kind="restart", importance=2, spend=True))
        elif e.kind == "health_bad":
            _fire(_notify(e.data.get("text", "Есть проблемы — «проверь себя»."), None, kind="health", importance=2, spend=True))
        elif e.kind == "milestone_done":
            txt = f"Веха «{e.data.get('milestone', '')}» закрыта (цель «{e.data.get('aim', '')}»)." + (f" Дальше: «{e.data['next']}»." if e.data.get("next") else " Следующую веху ты пока не ставил.")
            _fire(_notify(txt, None, kind="goal", importance=2, spend=True))
        elif e.kind == "aim_ready":
            txt = f"По цели «{e.data.get('aim', '')}» все вехи закрыты. Она достигнута — или ставим следующую веху? Скажи «цель {e.data.get('aim', '')[:25]} достигнута» или «веха: …»."
            _fire(_notify(txt, None, kind="goal", importance=2, spend=True))
        elif e.kind == "long_session":
            _fire(_notify(f"{e.data.get('hours', 4)} часа за ПК без перерыва. Не нотация — просто встань на пять минут.", None, kind="care", importance=1, spend=True))

    from . import events as _events
    _events.on("*", _on_event)
    sch.add_job(presence_tick, "interval", minutes=1, id="presence_tick", next_run_time=_soon(45))

    async def screen_cleanup():
        from . import screen
        try:
            n = screen.cleanup()
            if n:
                log.info("Экранное время: удалено %d старых отрезков", n)
        except Exception as e:  # pragma: no cover
            log.warning("screen cleanup: %s", e)
    sch.add_job(screen_cleanup, CronTrigger(hour=3, minute=20), id="screen_cleanup")
    sch.add_job(backup, CronTrigger(hour=3, minute=0), id="backup")
    sch.add_job(memory_nightly, CronTrigger(hour=4, minute=0), id="memory_nightly")
    sch.add_job(proactive_tick, "interval", hours=1, id="proactive", next_run_time=_soon(300))
    sch.add_job(gcal_flush, "interval", minutes=3, id="gcal_flush", next_run_time=_soon(60))
    md = cfg.telegram.morning_digest
    if md:
        h, m = md.split(":")
        sch.add_job(digest, CronTrigger(hour=int(h), minute=int(m)), id="digest")
    return sch
