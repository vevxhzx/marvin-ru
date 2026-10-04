"""Системные роуты (ФАЗА 7, шаг 7.6). Перенос механический из core/api/app.py, логика не менялась."""
from __future__ import annotations

import asyncio as _asyncio
import json as _json
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from ...db import (
    Event,
    Link,
    Note,
    Task,
    Transaction,
    get_setting,
    session,
    set_setting,
)
from ...services import (
    brain_notes,
    calendar,
    finance,
    goals,
    insights,
    orders,
    pc,
    pulse,
    screen,
    tasks,
)
from ...services.scheduler import morning_digest_text
from .._shared import _ev_out, broadcast
from ..schemas import BackupRestoreIn, EditionIn, GameBody, SettingsIn, TgLogin, UiPrefsIn

router = APIRouter()
log = logging.getLogger("jarvis.api.system")
# Облачные бэкапы живут в отдельном роутере: базовый `router` выше сверяется тестом
# tests/test_review_a_contract.py со списком SYSTEM_ROUTES (роуты «до разбиения app.py»),
# новые маршруты его не должны ломать. Регистрируем ПЕРВЫМ — иначе
# GET /api/backups/cloud/download съедается параметрическим /api/backups/{name:path}/download.
cloud_router = APIRouter()


def register(app) -> None:
    app.include_router(cloud_router)
    app.include_router(router)


@router.get("/api/health")
async def health():
    from ...brain import llm
    from ... import VERSION, BUILD
    from ...brain import persona
    return {"ok": True, "ollama": await llm.ollama_available(), "mode": llm.MODE, "time": datetime.now().isoformat(), "version": VERSION, "build": BUILD,
            "name": persona.display_name()}


# ---------------- дашборд ----------------
@router.get("/api/dashboard")
async def dashboard():
    s = finance.summary(30)
    debts = []
    for d in finance.list_debts():
        f = finance.debt_forecast(d)
        debts.append({**d.model_dump(), **f})
    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    pulse.auto_enable_if_used()
    fl = pulse.freelance_settings()
    return {
        "today": [_ev_out(e) for e in calendar.events_today()],
        "week": [e.model_dump() for e in calendar.list_events(start, start + timedelta(days=7))],
        "tasks": [t.model_dump() for t in tasks.list_tasks(limit=10)],
        "finance": s,
        "debts": debts,
        "upcoming": [r.model_dump() for r in finance.upcoming_payments(7)],
        "memory": [m.model_dump() for m in brain_notes.memory_feed(3, 15)],
        "digest": morning_digest_text(card=False),
        "streak": {**insights.streak(), "heatmap": insights.activity_heatmap(26)},
        "birthdays": insights.upcoming_birthdays(14),
        "forecast": insights.cash_forecast(30),
        "pc": {"alive": pc.alive(), "seen": pc.last_seen_iso(), "age_sec": pc.age_sec(), **pc.STATE},
        "timer": orders.timer_state(),
        "orders": {"open": [o for o in orders.list_orders() if o["status"] in ("new", "work", "review")][:5],
                   "unpaid": orders.unpaid_total(),
                   "expected": orders.expected_income(30),
                   "late": pulse.late_payments()[:3] if fl["enabled"] and fl["late_nudge"] else []},
        "freelance": fl["enabled"],
        "screen_time": screen.enabled(),
        "goals": goals.list_goals()[:4],
        "runway": goals.runway(),
        "payments": goals.payment_check(7),
    }

# ---------------- присутствие / события / лента / самопроверка ----------------
@router.get("/api/state")
def get_state():
    from ...services import state
    from ...brain import attention
    sn = state.snapshot()
    return {**sn, "line": state.line(), "budget_left": attention.budget_left(), "deferred": attention.queue_size(),
            "pc_alive": pc.alive()}


@router.get("/api/presence/events")
def get_presence_events(limit: int = 30):
    from ...services import events
    return [{"kind": e.kind, "key": e.key, "at": e.at.isoformat(), "quiet": e.quiet, "text": e.text, "data": e.data}
            for e in reversed(events.recent(max(1, min(limit, 200))))]


@router.get("/api/diagnose")
async def diagnose():
    from ...services import health
    res = await health.diagnose()
    health.record(res)
    return res


# ---------------- настройки, статус, экспорт, поиск ----------------
# ---------------- оформление сайта: одно на все устройства ----------------
@router.get("/api/ui-prefs")
def ui_prefs_get():
    """Тема, акцент, шрифт, обращение, порядок блоков — хранятся в базе, чтобы телефон и ПК выглядели одинаково."""
    raw = get_setting("ui.prefs")
    try:
        return {"prefs": _json.loads(raw) if raw else {}, "updated_at": get_setting("ui.prefs.at")}
    except ValueError:
        return {"prefs": {}, "updated_at": None}


@router.put("/api/ui-prefs")
def ui_prefs_put(p: UiPrefsIn, request: Request):
    if len(_json.dumps(p.prefs)) > 20_000:
        raise HTTPException(413, "слишком большие настройки")
    now_iso = datetime.now().isoformat(timespec="seconds")
    set_setting("ui.prefs", _json.dumps(p.prefs, ensure_ascii=False))
    set_setting("ui.prefs.at", now_iso)
    broadcast("ui_prefs", {"updated_at": now_iso, "origin": request.headers.get("x-client-id", "")})
    return {"ok": True, "updated_at": now_iso}


# ---------------- профиль издания, LLM-ключ, карточка клиента ----------------
# Раньше этих роутов в Python-сервере не было (они есть в Node-стенде server.ts),
# и раздел «Настройки → Windows-клиент» показывал ошибку. Формы — как в server.ts.
def _edition_payload(ed: str) -> dict:
    is_marvin = ed == "marvin"
    return {"edition": ed,
            "name": "Марвин",
            "name_latin": "Marvin",
            "is_marvin": is_marvin, "is_jarvis": not is_marvin}


@router.get("/api/edition")
def edition_get():
    ed = get_setting("edition") or "jarvis"
    return _edition_payload(ed if ed in ("marvin", "jarvis") else "jarvis")


@router.post("/api/edition")
def edition_put(p: EditionIn):
    if p.edition not in ("marvin", "jarvis"):
        raise HTTPException(400, "edition: marvin|jarvis")
    set_setting("edition", p.edition)
    broadcast("state")
    return _edition_payload(p.edition)


@router.get("/api/client/info")
def client_info():
    """Карточка десктоп-клиента в настройках (WebView2 / App Mode)."""
    import platform as _platform
    from ... import identity, VERSION
    return {"app_name": identity.NAME or "Марвин", "version": VERSION,
            "platform": _platform.system().lower(), "mode": "desktop_projection",
            "single_instance": True, "tray_enabled": True, "webview2_ready": True}


@router.get("/api/llm")
async def llm_info():
    """Статус LLM-ключа для карточки «Подключить LLM» (ожидает {enabled, model})."""
    from ...brain import llm
    on = await llm.ollama_available() if llm.OLLAMA_MODEL else False
    cloud = llm.cloud_enabled()
    model = llm.OLLAMA_MODEL if on else (llm.cloud_title() if cloud else None)
    return {"enabled": bool(on or cloud), "model": model,
            "mode": ("cloud" if cloud and not on else "hybrid" if cloud else "local" if on else "off")}


@router.get("/api/settings")
def settings_get():
    from ...config import read_settings
    return read_settings()


@router.put("/api/settings")
def settings_put(p: SettingsIn):
    from ...config import write_settings
    changed = write_settings(p.changes)
    # облако применяем на лету — перезапуск не нужен
    if any(k.startswith(("brain.cloud.", "brain.gemini.", "brain.mode", "brain.vision.", "brain.sorter.")) for k in changed):
        from ...brain import llm
        llm.reload_cloud_settings()
    if any(k.startswith("google.") for k in changed):
        _gcal_reload()
    if any(k.startswith(("owner.", "persona.")) for k in changed):
        from ...brain import persona
        persona.reload_persona()
        broadcast("settings", {"keys": changed})
    if any(k.startswith("brain.ollama.small_") for k in changed):
        from ...brain import llm
        llm.reload_small_settings()
    needs_restart = any(k.startswith(("telegram.", "backup.")) or (k.startswith("brain.ollama") and not k.startswith("brain.ollama.small_")) for k in changed)
    return {"changed": changed, "restart": needs_restart}


def _voice_status() -> dict:
    try:
        from ...voice import stt, tts
        return {"stt": stt.available(), "stt_model": stt.STT_MODEL, "stt_ready": stt._model is not None, "stt_error": stt.LAST_ERROR,
                "tts": tts.enabled(), "tts_engine": tts.ENGINE, "tts_ready": tts._model is not None or tts.ENGINE == "edge",
                "tts_error": tts.LAST_ERROR, "speaker": tts.SPEAKER, "reply": tts.REPLY_VOICE}
    except Exception as e:  # pragma: no cover
        return {"stt": False, "tts": False, "error": str(e)}


@router.get("/api/status")
async def status():
    """Состояние систем — показывается внутри настроек, отдельной страницы нет."""
    from ...brain import llm
    from ...config import cfg, DB_PATH
    from ...services.scheduler import last_backup
    from ...db import ChatMessage
    from sqlmodel import select
    ollama = await llm.ollama_available()
    diag = None if ollama else await llm.ollama_diagnose()
    with session() as s:
        last_tg = s.exec(select(ChatMessage).where(ChatMessage.channel.in_(["tg", "tg-voice"])).order_by(ChatMessage.id.desc())).first()
        counts = {"events": len(s.exec(select(Event)).all()), "tasks": len(s.exec(select(Task)).all()),
                  "notes": len(s.exec(select(Note)).all()), "links": len(s.exec(select(Link)).all()),
                  "transactions": len(s.exec(select(Transaction)).all())}
        from ...db import ActionLog as _AL, Memory as _Mem  # F6: размеры retention-таблиц + last (retention выключен, только чтение)
        from sqlalchemy import func as _f
        ret = {"chatmessage": int(s.exec(select(_f.count()).select_from(ChatMessage)).one() or 0), "memory": int(s.exec(select(_f.count()).select_from(_Mem)).one() or 0), "actionlog": int(s.exec(select(_f.count()).select_from(_AL)).one() or 0), "last": get_setting("retention:last")}
    tg_enabled = bool(cfg.telegram.token and cfg.telegram.owner_id)
    from ... import VERSION
    from ..app import app  # тот же объект FastAPI (нужен для app.state)
    return {
        "time": datetime.now().isoformat(),
        "version": VERSION,
        "game_mode": llm.GAME_MODE,
        "voice": _voice_status(),
        "pc": {"alive": pc.alive(), "seen": pc.last_seen_iso(), "age_sec": pc.age_sec(), **pc.STATE},
        "screen": {"enabled": screen.enabled(), "today_min": screen.summary()["active_min"] if screen.enabled() else 0,
                   "last": (lambda r: r[-1].end.isoformat() if r else None)(screen.slots())},
        "vision": llm.vision_status(),
        "ollama": {"ok": ollama, "model": llm.OLLAMA_MODEL, "url": llm.OLLAMA_URL, "diag": diag, "gpu": llm.GPU_NOTE,
                   "embed": await llm.embed_available(), "embed_model": llm.EMBED_MODEL,
                   "small_model": llm.SMALL_MODEL, "small_ok": llm.small_model_active(), "small_keep_alive": llm.SMALL_KEEP_ALIVE,
                   "small_last": llm.SMALL_LAST or None},
        "gemini": {"enabled": llm.cloud_enabled(), "provider": llm.CLOUD_PROVIDER or "gemini", "title": llm.cloud_title(),
                   "model": (llm._cloud_model() if llm.CLOUD_PROVIDER not in ("", "gemini") else (llm._RESOLVED_MODEL or llm.GEMINI_MODEL)),
                   "auto": llm.GEMINI_AUTO, "mode": llm.MODE,
                   "proxy": (llm.CLOUD_PROXY if llm.CLOUD_PROVIDER not in ("", "gemini") else (llm.GEMINI_PROXY or ((getattr(cfg.telegram, "proxy", "") or "").strip() or None))),
                   "last_error": llm.LAST_CLOUD_ERROR or (llm.LAST_GEMINI_ERROR if llm.CLOUD_PROVIDER in ("", "gemini") else None),
                   "model_last": llm.LAST_CLOUD_MODEL or None,
                   "providers": {k: {"title": v["title"], "model": v["model"], "free": v["free"], "key_url": v["key_url"]} for k, v in llm.PROVIDERS.items()}},
        "telegram": {"configured": tg_enabled, "running": bool(getattr(app.state, "tg_running", False)),
                     "last_message": last_tg.created_at.isoformat() if last_tg else None},
        "backup": last_backup(),
        "db": {"path": str(DB_PATH), "size": DB_PATH.stat().st_size if DB_PATH.exists() else 0, **counts},
        "retention": ret,
        # ошибка миграций: ставит init_db при сбое, очищает после успешного старта
        "migration_error": get_setting("migration:error"),
        "errors": list(getattr(app.state, "errors", []))[-10:],
    }


@router.get("/api/phone")
async def phone_access(request: Request):
    """Адреса для телефона (Tailscale / домашний Wi-Fi) + QR-коды. Показывается в настройках."""
    import socket
    import subprocess
    from ...config import cfg
    port = int(getattr(getattr(cfg, "server", None), "port", 8765) or 8765)

    def tailscale_ip():
        for exe in ("tailscale", r"C:\Program Files\Tailscale\tailscale.exe"):
            try:
                out = subprocess.run([exe, "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.strip()
                if out:
                    return out.splitlines()[0].strip()
            except Exception:
                continue
        return None

    def lan_ip():
        try:
            so = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            so.connect(("8.8.8.8", 80))
            ip = so.getsockname()[0]
            so.close()
            return ip
        except Exception:
            return None

    def qr(url):
        try:
            import segno
            return segno.make(url, error="m").svg_data_uri(scale=6, border=1, dark="#1c1c1e", light=None)
        except Exception:
            return None

    ts, lan = await _asyncio.to_thread(tailscale_ip), lan_ip()
    host = socket.gethostname().lower()
    # в ссылку зашит токен доступа: первый заход по ней ставит cookie на год, дальше адрес можно открывать без ?t=
    from ..auth import token as _tok, is_local as _is_lb
    if not _is_lb(request):
        raise HTTPException(403, "Ссылки для телефона выдаются только с самого компьютера")
    t = _tok()
    items = []
    if ts:
        items.append({"kind": "tailscale", "title": "Tailscale — из любой сети", "url": f"http://{ts}:{port}/?t={t}",
                      "alt": f"http://{host}:{port}/?t={t}", "qr": qr(f"http://{ts}:{port}/?t={t}")})
    if lan:
        items.append({"kind": "lan", "title": "Домашний Wi-Fi — телефон в той же сети", "url": f"http://{lan}:{port}/?t={t}", "qr": qr(f"http://{lan}:{port}/?t={t}")})
    # с какого адреса открыт сайт сейчас: если не localhost — телефон уже может так же
    opened_from = request.headers.get("host", "")
    return {"tailscale": bool(ts), "host": host, "port": port, "items": items, "opened_from": opened_from,
            "is_windows": __import__("os").name == "nt",
            "note": "Ссылка содержит ключ доступа — не публикуйте её. Отозвать все старые ссылки: кнопка «новый ключ»."}


@router.get("/api/runs")
def runs(limit: int = 50, channel: str | None = None, only_bad: bool = False):
    """Журнал работы: последние ходы — путь, инструменты, время, где переспросил и где его поправили."""
    from ...services import trace
    return {"items": trace.recent(limit, channel, only_bad), "enabled": trace.enabled()}


@router.get("/api/runs/report")
def runs_report(days: int = 7):
    """Сводка «как я работал» за период + текст для чата."""
    from ...services import trace
    return {**trace.report(days), "text": trace.report_text(days)}


@router.post("/api/phone/rotate")
def phone_rotate(request: Request):
    """Новый ключ доступа: все телефоны, где сайт был открыт по старой ссылке, потеряют доступ до нового QR."""
    from ..auth import rotate, is_local as _is_lb
    if not _is_lb(request):
        raise HTTPException(403, "Только с самого компьютера")
    rotate()
    return {"ok": True}


@router.post("/api/tg/login")
async def tg_login(body: TgLogin, request: Request):
    """Вход из Telegram Mini App: проверяем подпись initData, что это владелец — и ставим сессионную cookie.
    Публичный эндпоинт (сам является проверкой). Подробности — core/api/tg_auth.py."""
    from .. import tg_auth
    from ..auth import is_https
    try:
        tok, data = tg_auth.login(request, body.init_data)
    except ValueError as e:
        raise HTTPException(403, str(e))
    user = data.get("user") or {}
    resp = JSONResponse({"ok": True, "name": user.get("first_name") or "", "days": tg_auth.TG_SESSION_DAYS})
    # SameSite=None нужен webview Telegram (сайт открыт «внутри» другого приложения); допустим только с Secure
    https = is_https(request)
    resp.set_cookie(tg_auth.SESSION_COOKIE, tok, max_age=tg_auth.TG_SESSION_DAYS * 86400, httponly=True, path="/",
                    secure=https, samesite="none" if https else "lax")
    return resp


@router.post("/api/tg/logout")
def tg_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("jarvis_tg", path="/")
    return resp


@router.get("/api/tg/miniapp")
async def tg_miniapp(request: Request):
    """Состояние Mini App для настроек: настроен ли адрес, поднят ли Funnel. Без секретов."""
    import subprocess
    from ...config import cfg
    from ..auth import is_local as _is_lb
    url = (getattr(cfg.telegram, "webapp_url", "") or "").strip()

    def funnel_status():
        for exe in ("tailscale", r"C:\Program Files\Tailscale\tailscale.exe"):
            try:
                r = subprocess.run([exe, "funnel", "status"], capture_output=True, text=True, timeout=5)
                out = (r.stdout or "") + (r.stderr or "")
                if r.returncode != 0 and "not" in out.lower() and "found" in out.lower():
                    continue
                on = "funnel on" in out.lower()
                # первая строка вида "https://pc.tail1234.ts.net (Funnel on)"
                addr = next((ln.split()[0] for ln in out.splitlines() if ln.strip().startswith("https://")), None)
                return {"installed": True, "on": on, "url": addr}
            except FileNotFoundError:
                continue
            except Exception:
                return {"installed": True, "on": None, "url": None}
        return {"installed": False, "on": False, "url": None}

    st = await _asyncio.to_thread(funnel_status) if _is_lb(request) else {"installed": None, "on": None, "url": None}
    return {"webapp_url": url, "bot_configured": bool(cfg.telegram.token and cfg.telegram.owner_id),
            "funnel": st, "local": _is_lb(request)}


@router.post("/api/game")
async def game_mode(body: GameBody):
    from ...brain import llm
    return {"text": await llm.set_game_mode(body.on), "game_mode": llm.GAME_MODE}


@router.post("/api/status/small")
async def small_check():
    """«Проверить» у карточки малой модели: есть ли, отвечает ли, за сколько."""
    from ...brain import llm
    return await llm.small_check()


@router.post("/api/status/gemini")
async def gemini_check():
    from ...brain import llm
    llm.reload_cloud_settings()   # «проверить» = перечитать настройки + сбросить кэш + живой запрос
    return await llm.cloud_check()


# ---------------- Google Календарь (push-only) ----------------
def _gcal_reload():
    """Настройки Google меняются с сайта без перезапуска: перечитываем config."""
    from ... import config as _cfg
    from ...services import gcal
    fresh = _cfg._load()
    # Обновляем существующий объект, а не подменяем: модули, сделавшие
    # `from config import cfg`, держат ссылку на него — подмена оставляла
    # их (планировщик и др.) со старым конфигом после смены настроек с сайта.
    _cfg.cfg.__dict__.clear()
    _cfg.cfg.__dict__.update(fresh.__dict__)
    gcal.cfg = _cfg.cfg
    return gcal


@router.get("/api/google/status")
def google_status():
    return _gcal_reload().status()


@router.get("/api/google/connect")
def google_connect():
    """Кнопка «подключить» на сайте: отдаём ссылку на согласие Google (открывать на этом же ПК — редирект на localhost)."""
    gcal = _gcal_reload()
    if not gcal.client_id() or not gcal.client_secret():
        raise HTTPException(400, "Сначала вставьте Client ID и Client secret в настройках (раздел «Google Календарь»)")
    return {"url": gcal.auth_url()}


def _esc(value: object) -> str:
    """Экранировать текст для вставки в HTML-страницу.

    Страница ниже собирается строковой подстановкой, а `error` приходит из query-параметра
    (публичный /api/google/callback, без ключа). Без экранирования это отражённый XSS:
    злоумышленник присылает жертве ссылку вида …/api/google/callback?error=<script>…,
    и скрипт выполняется от имени сайта — может дёрнуть /api/… с её cookie-сессией."""
    import html
    return html.escape(str(value), quote=True)


@router.get("/api/google/callback", response_class=HTMLResponse)
async def google_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    gcal = _gcal_reload()
    page = "<html><head><meta charset='utf-8'><title>Марвин · Google</title></head><body style='font-family:-apple-system,Segoe UI,sans-serif;background:#f4f3f1;color:#1d1d1f;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'><div style='text-align:center;max-width:520px;padding:32px'>{}</div></body></html>"
    if error or not code:
        return page.format(f"<h1 style='font-weight:500'>Не вышло</h1><p>{_esc(error or 'Google не вернул код')}.</p><p><a href='/settings'>← назад в настройки</a></p>")
    try:
        res = await gcal.finish_auth(code, state)
    except Exception as e:
        # текст ошибки наружу не отдаём целиком (в нём могут быть детали обмена с Google) — только свой
        log.warning("Google OAuth не завершился: %s", type(e).__name__)
        return page.format("<h1 style='font-weight:500'>Не вышло</h1><p>Google не подтвердил вход. Попробуйте ещё раз.</p><p><a href='/settings'>← назад в настройки</a></p>")
    # включаем флаг, если забыли
    from ...config import write_settings
    write_settings({"google.enabled": True})
    _gcal_reload()
    _asyncio.get_running_loop().create_task(gcal.sync_all())
    broadcast("google", {"connected": True})
    email = _esc(res.get("email")) if res.get("email") else ""
    return page.format(f"<h1 style='font-weight:500'>Готово, сэр</h1><p>Google Календарь подключён{f' · {email}' if email else ''}. Выгружаю события — это займёт минуту.</p><p><a href='/settings'>← назад в настройки</a></p><script>setTimeout(()=>location.href='/settings',2500)</script>")


@router.post("/api/google/sync")
async def google_sync():
    gcal = _gcal_reload()
    if not gcal.connected():
        raise HTTPException(400, "Google Календарь не подключён")
    return await gcal.sync_all(days_back=30)


@router.post("/api/google/disconnect")
def google_disconnect():
    gcal = _gcal_reload()
    gcal.disconnect()
    from ...config import write_settings
    write_settings({"google.enabled": False})
    return {"ok": True}


@router.post("/api/backup")
def backup_now():
    """Ручной снимок — даже если ночной бэкап выключен (force). check — результат integrity_check свежего файла."""
    from ...services.scheduler import backup_db, last_backup
    dst = backup_db(force=True)
    return {"ok": dst is not None, "file": str(dst) if dst else None, "name": dst.name if dst else None,
            "check": last_backup().get("check")}


@router.get("/api/backups")
def backups_list():
    """Список бэкапов: снимки базы (в т.ч. «перед миграцией») + копии конфигов/ключей."""
    from ...services.scheduler import list_backups, list_config_backups
    return list_backups() + list_config_backups()


# ---------------- облачные бэкапы (WebDAV, cloud_backup.py) ----------------
# Пути под /api/backups/ — LOCAL_ONLY_PREFIXES в auth.py уже делает их «только с этого
# компьютера». Роуты лежат в cloud_router (см. выше): он подключается раньше `router`,
# поэтому /api/backups/cloud/download не съедается параметрическим {name:path}/download.
@cloud_router.get("/api/backups/cloud")
def backups_cloud_get():
    """Статус и настройки облака. Секреты — только флагами «задан/не задан»."""
    from ...services import cloud_backup
    return cloud_backup.status()


@cloud_router.put("/api/backups/cloud")
async def backups_cloud_put(request: Request):
    """Сохранить настройки облака. Пустая строка в пароле/токене = «не менять»."""
    from ...services import cloud_backup
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "тело запроса должно быть JSON")
    if not isinstance(body, dict):
        raise HTTPException(400, "ожидался объект настроек")
    try:
        return cloud_backup.save_settings(body)
    except ValueError as e:
        raise HTTPException(400, str(e))


@cloud_router.post("/api/backups/cloud/test")
def backups_cloud_test():
    """«Проверить соединение»: доступ к корню, каталог, список файлов. Ответ {ok, detail|error}."""
    from ...services import cloud_backup
    return cloud_backup.verify_connection()


@cloud_router.post("/api/backups/cloud/upload")
def backups_cloud_upload():
    """Отправить свежий снимок в облако (нет локального — сначала backup_db())."""
    from ...services import cloud_backup
    try:
        return cloud_backup.upload_latest()
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except cloud_backup.CloudError as e:
        raise HTTPException(502, str(e))


@cloud_router.get("/api/backups/cloud/download")
def backups_cloud_download(name: str):
    """Скачать файл из облака в локальные backups/ (шифрованный — расшифровать в .db),
    после чего его подхватывает существующий POST /api/backups/restore."""
    from ...services import cloud_backup
    try:
        return cloud_backup.download_to_backups(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except LookupError as e:
        raise HTTPException(404, str(e))
    except cloud_backup.CloudError as e:
        raise HTTPException(502, str(e))


@cloud_router.post("/api/backups/cloud/delete")
def backups_cloud_delete(name: str):
    """Удалить файл из облака (нужно для ротации cloud.keep; только свои backup-*)."""
    from ...services import cloud_backup
    try:
        return cloud_backup.delete_remote(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except cloud_backup.CloudError as e:
        raise HTTPException(502, str(e))


@router.get("/api/backups/{name:path}/download")
def backup_download(name: str):
    """Скачать файл бэкапа (снимок базы, копия перед миграцией или файл из backups/config-<дата>/).
    Доступ — тот же, что у всего /api (AuthMiddleware); путь валидируется как в restore_backup."""
    from ...services.scheduler import resolve_backup_file
    try:
        path = resolve_backup_file(name)
    except LookupError:
        raise HTTPException(404, "Такого бэкапа нет")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return FileResponse(path, filename=path.name, media_type="application/octet-stream")


@router.post("/api/backups/restore")
def backups_restore(body: BackupRestoreIn):
    """Восстановить data/jarvis.db из выбранного backup-*.db. После — перезапуск start.bat."""
    from ...services.scheduler import restore_backup
    try:
        return restore_backup(body.name)
    except LookupError:
        raise HTTPException(404, "Такого бэкапа нет")
    except ValueError as e:
        raise HTTPException(400, str(e))
