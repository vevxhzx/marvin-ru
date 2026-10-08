"""Google Календарь — двусторонняя синхронизация: ассистент → Google и обратно.

Всё, что появляется в календаре ассистента (с сайта, из Telegram, голосом), зеркалится в Google Календарь,
чтобы видеть его на телефоне/часах/в любом приложении. Обратно (google.pull): созданное в Google
появляется у ассистента, правки зеркалятся (Google главнее), удаления зеркалятся тоже.

Как устроено:
  • OAuth 2.0 «Desktop app» — свой client_id/secret в config.yaml (google.client_id / google.client_secret),
    кнопка «подключить» на сайте → браузер → Google → возврат на http://localhost:8765/api/google/callback.
  • refresh_token хранится в data/google_token.json (только на вашем ПК).
  • Каждое событие: event.google_id ↔ id события в Google. Создание / изменение / удаление / повторы → push.
  • Pull идёт напрямую в базу (мимо calendar.add/update — те сами пушат в Google, было бы эхо).
    Галочки и напоминания pull не трогает: done и reminded живут только локально.
  • Сеть недоступна — операция ставится в очередь (таблица settings: gcal_queue) и повторяется планировщиком.
  • Работает на чистом httpx: никакого тяжёлого google-api-python-client.

Зачем свой client_id: Google требует «приложение», а публиковать общий ключ на всех пользователей нельзя.
Инструкция — README → «Google Календарь» (5 минут, бесплатно, карта не нужна).
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlmodel import select

from ..config import DATA_DIR, TZ, cfg
from ..db import Event, get_setting, session, set_setting

log = logging.getLogger("jarvis.gcal")

TOKEN_PATH = DATA_DIR / "google_token.json"
SCOPE = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/userinfo.email"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://www.googleapis.com/calendar/v3"
_WD = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

_state: dict[str, Any] = {"oauth_state": None, "last_error": None, "last_sync": None}
_access: dict[str, Any] = {"token": None, "exp": 0.0}


# ---------------------------------------------------------------- настройки
def _g():
    return getattr(cfg, "google", None)


def enabled() -> bool:
    g = _g()
    return bool(g and getattr(g, "enabled", False) and client_id() and client_secret())


def client_id() -> str:
    g = _g()
    return str(getattr(g, "client_id", "") or "").strip()


def client_secret() -> str:
    g = _g()
    return str(getattr(g, "client_secret", "") or "").strip()


def calendar_id() -> str:
    g = _g()
    return str(getattr(g, "calendar_id", "") or "").strip() or "primary"


def proxy() -> str | None:
    g = _g()
    p = str(getattr(g, "proxy", "") or "").strip()
    if p:
        return p
    # из России Google иногда не отвечает — берём прокси Telegram/облака, если задан
    tg = str(getattr(cfg.telegram, "proxy", "") or "").strip()
    return tg or None


def _client(timeout: float = 20) -> httpx.AsyncClient:
    kw: dict[str, Any] = {"timeout": timeout, "trust_env": False}
    if proxy():
        kw["proxy"] = proxy()
    return httpx.AsyncClient(**kw)


def redirect_uri() -> str:
    port = int(getattr(cfg.server, "port", 8765))
    return f"http://localhost:{port}/api/google/callback"


def connected() -> bool:
    return TOKEN_PATH.exists() and bool(_load_token().get("refresh_token"))


def _load_token() -> dict:
    try:
        return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_token(tok: dict) -> None:
    TOKEN_PATH.write_text(json.dumps(tok, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(TOKEN_PATH, 0o600)
    except Exception:  # Windows
        pass


def status() -> dict:
    tok = _load_token() if TOKEN_PATH.exists() else {}
    with session() as s:
        total = len(s.exec(select(Event)).all())
        synced = len(s.exec(select(Event).where(Event.google_id != None)).all())  # noqa: E711
    return {"configured": bool(client_id() and client_secret()), "enabled": enabled(), "pull": pull_enabled(),
            "connected": connected(),
            "email": tok.get("email"), "calendar_id": calendar_id(), "redirect_uri": redirect_uri(),
            "last_error": _state["last_error"], "last_sync": _state["last_sync"], "last_pull": _state.get("last_pull"),
            "queued": len(_queue()), "synced": synced, "total": total, "proxy": bool(proxy())}


def pull_enabled() -> bool:
    """Забор из Google включён: вкл + подключено + google.pull (по умолчанию выкл — только отправка)."""
    g = _g()
    return bool(enabled() and connected() and getattr(g, "pull", False))


# ---------------------------------------------------------------- OAuth
def auth_url() -> str:
    _state["oauth_state"] = secrets.token_urlsafe(16)
    q = {"client_id": client_id(), "redirect_uri": redirect_uri(), "response_type": "code", "scope": SCOPE,
         "access_type": "offline", "prompt": "consent", "state": _state["oauth_state"]}
    return AUTH_URL + "?" + urlencode(q)


async def finish_auth(code: str, state: str | None) -> dict:
    if not _state["oauth_state"] or state != _state["oauth_state"]:
        raise RuntimeError("Неверный state — начните подключение заново с сайта")
    async with _client(30) as c:
        r = await c.post(TOKEN_URL, data={"code": code, "client_id": client_id(), "client_secret": client_secret(),
                                          "redirect_uri": redirect_uri(), "grant_type": "authorization_code"})
    if r.status_code != 200:
        raise RuntimeError(f"Google не выдал токен: {r.status_code} {r.text[:200]}")
    tok = r.json()
    if not tok.get("refresh_token"):
        raise RuntimeError("Google не вернул refresh_token. Отзовите доступ на myaccount.google.com/permissions и подключите снова.")
    tok["obtained_at"] = time.time()
    # почта — чтобы показать, какой аккаунт подключён
    try:
        async with _client(15) as c:
            me = await c.get("https://www.googleapis.com/oauth2/v2/userinfo", headers={"Authorization": f"Bearer {tok['access_token']}"})
            if me.status_code == 200:
                tok["email"] = me.json().get("email")
    except Exception:
        pass
    _save_token(tok)
    _access["token"], _access["exp"] = tok["access_token"], time.time() + int(tok.get("expires_in", 3600)) - 60
    _state["last_error"] = None
    _state["oauth_state"] = None
    log.info("Google Календарь подключён (%s)", tok.get("email") or "аккаунт")
    return {"ok": True, "email": tok.get("email")}


def disconnect() -> None:
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
    _access["token"], _access["exp"] = None, 0.0
    set_setting("gcal_queue", "")


async def _token() -> str:
    if _access["token"] and time.time() < _access["exp"]:
        return _access["token"]
    tok = _load_token()
    if not tok.get("refresh_token"):
        raise RuntimeError("Google Календарь не подключён")
    async with _client(20) as c:
        r = await c.post(TOKEN_URL, data={"refresh_token": tok["refresh_token"], "client_id": client_id(),
                                          "client_secret": client_secret(), "grant_type": "refresh_token"})
    if r.status_code != 200:
        detail = r.text[:200]
        if "invalid_grant" in detail:
            detail = ("доступ отозван или истёк (у приложений в статусе «Testing» токен живёт 7 дней — "
                      "в Google Cloud Console нажмите «Publish app»). Подключите заново на сайте.")
        raise RuntimeError(f"Не обновил токен Google: {detail}")
    data = r.json()
    _access["token"], _access["exp"] = data["access_token"], time.time() + int(data.get("expires_in", 3600)) - 60
    return _access["token"]


# ---------------------------------------------------------------- преобразование события
def _body(ev: Event) -> dict:
    end = ev.end or (ev.start + timedelta(hours=1))
    body: dict[str, Any] = {
        "summary": ("✓ " if ev.done and not ev.repeat else "") + ev.title,
        "start": {"dateTime": ev.start.replace(microsecond=0).isoformat(), "timeZone": TZ},
        "end": {"dateTime": end.replace(microsecond=0).isoformat(), "timeZone": TZ},
        "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": int(ev.remind_minutes or 0)}]},
        "extendedProperties": {"private": {"assistant_id": str(ev.id)}},
    }
    if ev.location:
        body["location"] = ev.location
    if ev.notes:
        body["description"] = ev.notes
    if ev.repeat:
        rule = {"daily": "RRULE:FREQ=DAILY", "weekly": "RRULE:FREQ=WEEKLY", "monthly": "RRULE:FREQ=MONTHLY", "yearly": "RRULE:FREQ=YEARLY"}[ev.repeat]
        if ev.repeat == "weekly":
            days = [int(x) for x in (ev.repeat_days or "").split(",") if x.strip().isdigit()] or [ev.start.weekday()]
            rule += ";BYDAY=" + ",".join(_WD[d] for d in sorted(days))
        if ev.repeat_until:
            rule += ";UNTIL=" + ev.repeat_until.strftime("%Y%m%dT235959Z")
        rec = [rule]
        skip = [d for d in (ev.skip_dates or "").split(",") if d.strip()]
        if skip:
            rec.append("EXDATE;TZID=" + TZ + ":" + ",".join(datetime.fromisoformat(d).strftime("%Y%m%d") + ev.start.strftime("T%H%M%S") for d in skip))
        body["recurrence"] = rec
    return body


# ---------------------------------------------------------------- очередь (офлайн-устойчивость)
def _queue() -> list[dict]:
    try:
        return json.loads(get_setting("gcal_queue") or "[]")
    except Exception:
        return []


def _enqueue(op: str, event_id: int, google_id: str | None = None) -> None:
    q = [x for x in _queue() if not (x["event_id"] == event_id and x["op"] == op)]
    q.append({"op": op, "event_id": event_id, "google_id": google_id, "ts": datetime.now().isoformat()})
    set_setting("gcal_queue", json.dumps(q[-500:], ensure_ascii=False))


# ---------------------------------------------------------------- push
async def push(event_id: int) -> bool:
    """Создать или обновить событие в Google. Возвращает True при успехе (иначе ставит в очередь)."""
    if not enabled() or not connected():
        return False
    with session() as s:
        ev = s.get(Event, event_id)
        if not ev:
            return False
        body, gid = _body(ev), ev.google_id
    try:
        tok = await _token()
        async with _client(25) as c:
            h = {"Authorization": f"Bearer {tok}"}
            if gid:
                r = await c.put(f"{API}/calendars/{calendar_id()}/events/{gid}", headers=h, json=body)
                if r.status_code == 404:
                    gid = None   # удалили руками в Google — создаём заново
            if not gid:
                r = await c.post(f"{API}/calendars/{calendar_id()}/events", headers=h, json=body)
            if r.status_code >= 300:
                raise RuntimeError(f"{r.status_code} {r.text[:200]}")
            new_gid = r.json().get("id")
        with session() as s:
            ev = s.get(Event, event_id)
            if ev and ev.google_id != new_gid:
                ev.google_id = new_gid
                s.add(ev); s.commit()
        _state["last_error"], _state["last_sync"] = None, datetime.now().isoformat()
        return True
    except Exception as e:
        _state["last_error"] = str(e)[:300]
        log.warning("Google Календарь: не отправил событие %s: %s", event_id, e)
        _enqueue("push", event_id)
        return False


async def remove(event_id: int, google_id: str | None) -> bool:
    if not enabled() or not connected() or not google_id:
        return False
    try:
        tok = await _token()
        async with _client(20) as c:
            r = await c.delete(f"{API}/calendars/{calendar_id()}/events/{google_id}", headers={"Authorization": f"Bearer {tok}"})
            if r.status_code not in (200, 204, 404, 410):
                raise RuntimeError(f"{r.status_code} {r.text[:200]}")
        _state["last_error"], _state["last_sync"] = None, datetime.now().isoformat()
        return True
    except Exception as e:
        _state["last_error"] = str(e)[:300]
        log.warning("Google Календарь: не удалил %s: %s", google_id, e)
        _enqueue("delete", event_id, google_id)
        return False


async def flush_queue() -> int:
    """Повторить отложенные операции. Вызывается планировщиком раз в несколько минут."""
    if not enabled() or not connected():
        return 0
    q = _queue()
    if not q:
        return 0
    set_setting("gcal_queue", "[]")
    done = 0
    for item in q:
        ok = await (remove(item["event_id"], item.get("google_id")) if item["op"] == "delete" else push(item["event_id"]))
        done += int(ok)
        if not ok:
            break   # сеть лежит — остальное уже снова в очереди, не долбим
    return done


async def sync_all(days_back: int = 1) -> dict:
    """Первичная выгрузка: все будущие события (и повторы) без google_id → в Google."""
    if not enabled() or not connected():
        return {"ok": False, "error": "не подключено"}
    since = datetime.now() - timedelta(days=days_back)
    with session() as s:
        ids = [e.id for e in s.exec(select(Event).where((Event.start >= since) | (Event.repeat != "")))]
    ok = 0
    for i in ids:
        if await push(i):
            ok += 1
        elif _state["last_error"]:
            break
    return {"ok": True, "pushed": ok, "total": len(ids), "error": _state["last_error"]}


# ---------------------------------------------------------------- pull (Google → ассистент)
_GDAY = ("MO", "TU", "WE", "TH", "FR", "SA", "SU")


def _parse_when(raw: dict | None, all_day_end: bool = False) -> datetime | None:
    """dateTime с зоной → локальное наивное (как хранит БД); date → полночь (концу — 23:59)."""
    if not raw:
        return None
    if raw.get("dateTime"):
        dt = datetime.fromisoformat(str(raw["dateTime"]))
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        return dt.replace(microsecond=0)
    if raw.get("date"):
        d = datetime.fromisoformat(str(raw["date"]))
        return d.replace(hour=23, minute=59) if all_day_end else d.replace(hour=0, minute=0)
    return None


def _parse_rrule(recurrence: list | None) -> tuple[str, str, datetime | None]:
    """RRULE из Google → (repeat, repeat_days, repeat_until). Не умеем (HOURLY…) — одиночное."""
    rule = next((r for r in (recurrence or []) if str(r).startswith("RRULE:")), "")
    m = re.search(r"FREQ=(DAILY|WEEKLY|MONTHLY|YEARLY)", rule)
    if not m:
        return "", "", None
    rep = {"DAILY": "daily", "WEEKLY": "weekly", "MONTHLY": "monthly", "YEARLY": "yearly"}[m.group(1)]
    days = ""
    if rep == "weekly":
        byday = re.search(r"BYDAY=([A-Z,]+)", rule)
        if byday:
            days = ",".join(str(_GDAY.index(d)) for d in byday.group(1).split(",") if d in _GDAY)
    until = None
    mu = re.search(r"UNTIL=(\d{8}T\d{6})Z?", rule)
    if mu:
        try:
            until = datetime.strptime(mu.group(1)[:15], "%Y%m%dT%H%M%S")
        except ValueError:
            until = None
    return rep, days, until


async def pull() -> dict:
    """Забрать события из Google: новые → создать, изменённые → обновить (Google главнее),
    удалённые там → удалить и у себя. Пишем напрямую в базу (мимо calendar.add/update —
    те сами пушат в Google, было бы эхо). Галочки и напоминания не трогаем."""
    from ..db import remember
    if not pull_enabled():
        return {"ok": False, "error": "забор выключен (google.pull)"}
    now = datetime.now()
    params = {"timeMin": (now - timedelta(days=7)).isoformat() + "Z",
              "timeMax": (now + timedelta(days=90)).isoformat() + "Z",
              "singleEvents": "false", "showDeleted": "true", "maxResults": "250", "orderBy": "updated"}
    try:
        tok = await _token()
        async with _client(30) as c:
            r = await c.get(f"{API}/calendars/{calendar_id()}/events", headers={"Authorization": f"Bearer {tok}"},
                            params=params)
            if r.status_code >= 300:
                raise RuntimeError(f"{r.status_code} {r.text[:200]}")
            items = r.json().get("items", [])
    except Exception as e:
        _state["last_error"] = str(e)[:300]
        log.warning("Google Календарь: не забрал события: %s", e)
        return {"ok": False, "error": str(e)[:200]}
    with session() as s:
        by_gid = {e.google_id: e for e in s.exec(select(Event).where(Event.google_id != None)).all()}  # noqa: E711
    created = updated = deleted = 0
    with session() as s:
        for it in items:
            gid = it.get("id")
            if not gid:
                continue
            if it.get("status") == "cancelled":
                ev = by_gid.get(gid)
                if ev:
                    remember(s, "event", f"Удалено в Google — снёс и у себя: «{ev.title}» {ev.start:%d.%m %H:%M}", "event", ev.id, "gcal")
                    s.delete(s.get(Event, ev.id))
                    s.commit()
                    deleted += 1
                continue
            title = (it.get("summary") or "Без названия").strip()
            start = _parse_when(it.get("start"))
            if not start:
                continue
            end = _parse_when(it.get("end"), all_day_end=True) or (start + timedelta(hours=1))
            location = (it.get("location") or "").strip() or None
            notes = (it.get("description") or "").strip() or None
            rep, days, until = _parse_rrule(it.get("recurrence"))
            ev = by_gid.get(gid)
            if not ev:
                ev = Event(title=title, start=start, end=end, location=location, notes=notes,
                           remind_minutes=30, source="gcal", google_id=gid,
                           repeat=rep, repeat_days=days, repeat_until=until)
                s.add(ev); s.commit(); s.refresh(ev)
                remember(s, "event", f"Из Google: «{title}» {start:%d.%m %H:%M}", "event", ev.id, "gcal")
                s.commit()
                created += 1
                continue
            row = s.get(Event, ev.id)
            if not row:
                continue
            same = ((row.title or "").lstrip("✓ ") == title and row.start == start and row.end == end
                    and (row.location or None) == location and (row.notes or None) == notes
                    and row.repeat == rep and row.repeat_days == days and row.repeat_until == until)
            if same:
                continue
            moved = row.start != start
            row.title, row.start, row.end = title, start, end
            row.location, row.notes, row.repeat, row.repeat_days, row.repeat_until = location, notes, rep, days, until
            if moved:
                row.reminded = False   # время уехало — напомнить заново
            s.add(row)
            remember(s, "event", f"Google обновил: «{title}» {start:%d.%m %H:%M}", "event", row.id, "gcal")
            s.commit()
            updated += 1
    _state["last_error"], _state["last_pull"] = None, now.isoformat()
    log.info("Google Календарь: забрал — новых %d, обновлено %d, удалено %d", created, updated, deleted)
    return {"ok": True, "created": created, "updated": updated, "deleted": deleted,
            "total": len(items)}


# ---------------------------------------------------------------- хуки из calendar.py (не блокируют основной поток)
def schedule_push(event_id: int) -> None:
    _fire(push(event_id), "push", event_id)


def schedule_remove(event_id: int, google_id: str | None) -> None:
    if google_id:
        _fire(remove(event_id, google_id), "delete", event_id, google_id)


def _fire(coro, op: str, event_id: int, google_id: str | None = None) -> None:
    if not enabled() or not connected():
        coro.close()
        return
    import asyncio
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(coro)
    except RuntimeError:
        coro.close()
        _enqueue(op, event_id, google_id)   # нет event loop (скрипт/тест) — доедет через планировщик
