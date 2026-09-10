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
from ..services import calendar, finance, tasks
from ..services.finance import money
from ..db import get_setting, set_setting

log = logging.getLogger("assistant.sched")
Notifier = Callable[[str], Awaitable[None]]


def morning_digest_text() -> str:
    d = datetime.now()
    wd = ["понедельник", "вторник", "среда", "четверг", "пятница", "суббота", "воскресенье"][d.weekday()]
    lines = [f"☀️ Доброе утро, сэр. {wd.capitalize()}, {d:%d.%m}."]
    evs = calendar.events_today()
    lines.append("📅 " + ("\n".join(f"{e.start:%H:%M} — {e.title}" for e in evs) if evs else "Встреч нет. Подозрительно спокойно."))
    ts = tasks.list_tasks(limit=5)
    if ts:
        lines.append("✅ Задачи: " + "; ".join(t.title for t in ts))
    pays = finance.upcoming_payments(3)
    if pays:
        lines.append("💳 Скоро платежи: " + "; ".join(f"{p.title} {money(p.amount)} ({p.next_date:%d.%m})" for p in pays))
    s = finance.summary(1)
    lines.append(f"💰 Баланс: {money(s['total_balance'])}")
    return "\n".join(lines)


def backup_db() -> Path | None:
    if not cfg.backup.enabled or not DB_PATH.exists():
        return None
    bdir = (ROOT / cfg.backup.dir).resolve() if not Path(cfg.backup.dir).is_absolute() else Path(cfg.backup.dir)
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
    bdir = (ROOT / cfg.backup.dir).resolve() if not Path(cfg.backup.dir).is_absolute() else Path(cfg.backup.dir)
    files = sorted(bdir.glob("backup-*.db"), key=lambda f: f.stat().st_mtime) if bdir.exists() else []
    if not files:
        return {"enabled": bool(cfg.backup.enabled), "last": None, "dir": str(bdir), "count": 0, "extra_dir": getattr(cfg.backup, "extra_dir", None) or None}
    f = files[-1]
    return {"enabled": bool(cfg.backup.enabled), "last": datetime.fromtimestamp(f.stat().st_mtime).isoformat(), "dir": str(bdir),
            "count": len(files), "size": f.stat().st_size, "extra_dir": getattr(cfg.backup, "extra_dir", None) or None}


def build(notify: Notifier) -> AsyncIOScheduler:
    # misfire_grace_time: ПК спал/ноут был закрыт — задача, пропущенная меньше чем на час, всё равно выполнится один раз
    # (coalesce), а не молча пропадёт (по умолчанию у APScheduler 1 секунда) и не выстрелит пачкой.
    sch = AsyncIOScheduler(timezone=cfg.owner.timezone,
                           job_defaults={"misfire_grace_time": 3600, "coalesce": True, "max_instances": 1})
    # «через N секунд после старта» — с часовым поясом планировщика, иначе на ПК с другим системным TZ задачи считаются «пропущенными»
    from datetime import datetime as _dtm
    _tz = sch.timezone
    _soon = lambda sec: _dtm.now(_tz) + timedelta(seconds=sec)  # noqa: E731

    async def _notify(text: str, buttons=None, urgent: bool = False):
        """notify может быть старым (только text) — кнопки передаём, если умеет.
        Тихие часы (notifications.quiet_from..quiet_to, по умолчанию 23–8): инициативные сообщения ассистента
        (бюджет, подписки, дни рождения, вечерний обзор) ночью не шлём — они догонят днём или не нужны вовсе.
        urgent=True (напоминание о событии, которое человек сам поставил на это время) — шлём всегда."""
        if not urgent and _quiet_now():
            log.info("тихие часы — пропускаю уведомление: %s", text[:60])
            return
        try:
            await notify(text, buttons)  # type: ignore[call-arg]
        except TypeError:
            await notify(text)

    def ping(kind, **payload):
        from ..brain import agent
        if agent.on_change:
            agent.on_change(kind, payload)

    async def reminders():
        for e in calendar.due_reminders():
            mins = max(0, int((e.start - datetime.now()).total_seconds() // 60))
            when = "уже сейчас" if mins == 0 else f"через {mins} мин"
            text = f"⏰ «{e.title}» — {when} ({e.start:%H:%M})" + (f", {e.location}" if e.location else "") + ". Не подведите меня, сэр."
            ping("reminder", text=text, id=f"ev{e.id}-{e.start:%Y%m%d%H%M}")
            await _notify(text, [("✅ Иду", f"ev:{e.id}:ok"), ("⏰ +1 час", f"ev:{e.id}:hour"), ("📅 Завтра", f"ev:{e.id}:tomorrow")], urgent=True)

    async def task_reminders():
        for t, text in tasks.due_task_reminders():
            ping("reminder", text=text, id=f"task{t.id}-{t.remind_stage}")
            await _notify(text, [("✅ Сделал", f"task:{t.id}:done"), ("⏰ +1 час", f"task:{t.id}:hour"), ("📅 Завтра", f"task:{t.id}:tomorrow")], urgent=True)

    async def semantic_job():
        from . import semantic
        try:
            await semantic.index_pending()
        except Exception as e:  # pragma: no cover
            log.warning("semantic index failed: %s", e)

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
        text = morning_digest_text()
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

    async def backup():
        try:
            backup_db()
        except Exception as e:  # pragma: no cover
            log.warning("backup failed: %s", e)

    async def polish_job():
        from . import polish
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
        from . import insights
        try:
            txt = await insights.weekly_digest()
        except Exception as e:  # pragma: no cover
            log.warning("weekly digest failed: %s", e); return
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
        """Тихая самодиагностика раз в день — только в лог и в статус (в Telegram НЕ шлём, по просьбе владельца)."""
        from ..brain import llm
        try:
            ok_ollama = await llm.ollama_available()
            cloud = await llm.cloud_check() if llm.cloud_enabled() else {"ok": None}
            lb = last_backup()
            log.info("Самопроверка: Ollama %s · облако %s · бэкап %s · ПК-клиент %s",
                     "ок" if ok_ollama else "нет", "ок" if cloud.get("ok") else ("выкл" if cloud.get("ok") is None else "НЕТ"),
                     lb.get("last", "не было")[:16] if lb.get("last") else "не было", "на связи" if __import__("core.services.pc", fromlist=["alive"]).alive() else "нет")
        except Exception as e:  # pragma: no cover
            log.warning("self-check failed: %s", e)

    async def evening_review():
        """21:00 — незакрытые дела с дедлайном сегодня/просроченные: одно сообщение, кнопки «сделал / завтра» под каждым.
        Не чаще раза в день (переживает перезапуск), не шлём, если список пуст."""
        key = f"evening_review:{datetime.now():%Y-%m-%d}"
        if get_setting(key):
            return
        due = tasks.evening_review()
        if not due:
            return
        set_setting(key, "1")
        n = len(due)
        head = f"🌙 Вечер, сэр. {'Осталась' if n == 1 else 'Остались'} {n} {'задача' if n == 1 else 'задачи' if n < 5 else 'задач'} с дедлайном:"
        ping("reminder", text=head, id=key)
        await _notify(head)
        for t in due[:5]:
            when = "сегодня" if t.due.date() == datetime.now().date() else f"было {t.due:%d.%m}"
            await _notify(f"• «{t.title}» — {when}", [("✅ Сделал", f"task:{t.id}:done"), ("📅 Завтра", f"task:{t.id}:tomorrow")])
        if n > 5:
            await _notify(f"…и ещё {n - 5}. Полный список — «мои задачи».")

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
    sch.add_job(backup, CronTrigger(hour=3, minute=0), id="backup")
    sch.add_job(gcal_flush, "interval", minutes=3, id="gcal_flush", next_run_time=_soon(60))
    md = cfg.telegram.morning_digest
    if md:
        h, m = md.split(":")
        sch.add_job(digest, CronTrigger(hour=int(h), minute=int(m)), id="digest")
    return sch
