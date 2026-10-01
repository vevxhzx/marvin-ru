"""HTTP API ядра. Его используют: сайт (Этап 2) и голосовой клиент на ПК (Этап 3)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi.responses import JSONResponse, RedirectResponse
import asyncio
import logging
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlmodel import select

from ..brain import agent, persona
from ..config import ROOT
from ..db import session, Event, Task, Note, Link, Transaction, Debt, Recurring, Aim, Milestone, get_setting, set_setting
from ..services import brain_notes, calendar, finance, goals, insights, orders, pc, people, pulse, relations, tasks, screen
from ..services.scheduler import morning_digest_text
from .schemas import (  # ФАЗА 7 шаг 7.0: тела моделей вынесены в core/api/schemas.py, имена те же
   ChatIn, PcPing, PcAck, PcLaunch, PcResult, PcClip, VisionIn, CloudPreviewIn, RelationIn, EventIn,
   SkipIn, EventDoneIn, TaskIn, TaskPatch, AimIn, AimPatch, MilestoneIn, TxIn, TxPatch, CategoryIn,
   CategoryPatch, BalanceIn, AccountIn, AccountPatch, DebtIn, PayIn, DebtPatch, RecurringIn, RecurringPatch,
   ClientIn, OrderIn, OrderPatch, PaymentIn, TimerIn, ManualTimeIn, ScreenImportIn, PersonIn, PomoSettingsIn,
   FreelanceIn, GoalIn, GoalPatch, GoalPut, NoteIn, LinkIn, BoardIn, BoardPatch, BoardItemIn, BoardItemPatch,
   BoardBulk, BoardIds, BoardSync, NoteEdit, LinkEdit, FactIn, FactPatch, StyleIn, UiPrefsIn, EditionIn,
   SettingsIn, TgLogin, VoicePick, GameBody, BackupRestoreIn,
)

log = logging.getLogger("jarvis.api")

app = FastAPI(title="J.A.R.V.I.S. Core", version="0.1")
# CORS: сайт живёт на том же origin, что и API, — чужим сайтам доступ не нужен. Разрешаем только dev-сервер Vite.
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
# доступ с других устройств — только с токеном (см. core/api/auth.py); с самого ПК — свободно
from .auth import AuthMiddleware  # noqa: E402
app.add_middleware(AuthMiddleware)

# CRM (фаза 4) — отдельный роутер в core/crm/, подключается здесь; существующие пути не трогаются
from ..crm.router import router as _crm_router  # noqa: E402
app.include_router(_crm_router)


# ---------------- живые обновления (сайт узнаёт о действиях из Telegram/голоса мгновенно) ----------------
# ФАЗА 7 шаг 7.0: общее состояние роутов вынесено в core/api/_shared.py, здесь реэкспорт —
# core/crm/router.py и тесты импортируют `broadcast` из core.api.app, ломать нельзя.
import asyncio as _asyncio
import json as _json
from fastapi.responses import StreamingResponse

from ._shared import _ev_out, _pc_streams, _subscribers, broadcast  # noqa: F401  (реэкспорт)

PC_ORGANIZE_LOG: list[dict] = []
PC_ORGANIZE_PREVIEW: dict | None = None

agent.on_change = broadcast


@app.get("/api/events/stream")
async def stream(client: str = ""):
    """Живые события. `?client=pc` — так подключается voice.bat: по этим подключениям ядро знает, слушает ли кто-то ПК-команды."""
    from ..services import pc as _pc
    q: _asyncio.Queue = _asyncio.Queue()
    _subscribers.add(q)
    if client == "pc":
        _pc_streams.add(id(q)); _pc.SSE_CLIENTS = len(_pc_streams)

    async def gen():
        try:
            yield "retry: 3000\n\n"
            while True:
                try:
                    msg = await _asyncio.wait_for(q.get(), timeout=25)
                    yield f"data: {msg}\n\n"
                except _asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            _subscribers.discard(q)
            if client == "pc":
                _pc_streams.discard(id(q)); _pc.SSE_CLIENTS = len(_pc_streams)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------- чат ----------------
def _card_for(r) -> str | None:
    """URL карточки-картинки для важного ответа (или None). Одна логика с Telegram — cards.for_result."""
    try:
        from pathlib import Path
        from ..services import cards
        p = cards.for_result(getattr(r, "actions", []) or [], getattr(r, "text", "") or "")
        if p and Path(p).exists():
            return f"/api/cards/{Path(p).name}"
    except Exception:
        pass
    return None


@app.post("/api/chat/stream")
async def chat_stream(inp: ChatIn):
    """Тот же чат, но ответ LLM приходит по словам (SSE): event token / done."""
    from ..brain import llm
    q: _asyncio.Queue = _asyncio.Queue()

    async def sink(piece: str):
        await q.put(("token", piece))

    async def run():
        token = llm.token_sink.set(sink)
        try:
            r = await agent.handle(inp.text, inp.channel)
            card = await _asyncio.to_thread(_card_for, r)
            await q.put(("done", {"text": r.text, "actions": r.actions, "via": r.via, "card": card}))
        except Exception as e:  # pragma: no cover
            await q.put(("done", {"text": f"Ошибка: {e}", "actions": [], "via": "none"}))
        finally:
            llm.token_sink.reset(token)

    async def gen():
        task = _asyncio.create_task(run())
        try:
            while True:
                kind, data = await q.get()
                yield f"event: {kind}\ndata: {_json.dumps(data, ensure_ascii=False)}\n\n"
                if kind == "done":
                    break
        finally:
            if not task.done():
                task.cancel()
    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------- ПК-клиент (voice.bat): пульс, состояние, результаты команд, зрение ----------------
@app.post("/api/pc/ping")
def pc_ping(p: PcPing):
    """Голосовой клиент раз в 20 с сообщает, что жив и что делает (idle/listening/thinking/speaking/off).
    Тот же пульс кормит экранное время (screen) и состояние присутствия (state): сел/отошёл/что открыто/долго ли."""
    from ..services import pc, state
    was = pc.STATE.get("mode")
    pc.seen({"mode": p.mode, "text": p.text})
    if was != p.mode:
        broadcast("pc_state", {"mode": p.mode, "text": p.text})
    try:
        if p.screen:
            from ..services import screen
            screen.record(p.app, p.title, p.idle_sec)
            name, sub, cat = screen.classify(p.app, p.title, screen._GAMES)
            state.tick(name, sub, cat, p.idle_sec)
        else:
            state.tick()
    except Exception as e:  # pragma: no cover
        log.warning("pc ping state: %s", e)
    # Возвращаем клиенту актуальное значение «экранное время»: включение настройки применяется на лету (в течение пульса),
    # а не после перезапуска voice.bat — раньше это была причина «включено, но данных нет».
    want_screen = False
    try:
        from ..services import screen
        want_screen = screen.enabled()
    except Exception:  # pragma: no cover
        pass
    return {"ok": True, "screen": want_screen}


@app.get("/api/screen")
def screen_report(day: str | None = None, days: int = 1):
    """Экранное время: сводка за день (карточка на «Сегодня») или за несколько дней."""
    from ..services import screen
    d = datetime.fromisoformat(day) if day else None
    n = max(1, min(days, 31))
    r = screen.summary(d, n)
    return {**r, "first": r["first"].isoformat() if r["first"] else None, "last": r["last"].isoformat() if r["last"] else None,
            "sessions": [[a.isoformat(), b.isoformat()] for a, b in r["sessions"]], "idle_min_setting": screen.idle_min(),
            "pc_alive": pc.alive(), "projects": screen.project_sessions(d, n), "text": screen.text(d, n)}


@app.post("/api/pc/ack")
def pc_ack(a: PcAck):
    """ПК подтверждает: команду из SSE получил и выполняет (чтобы «Смотрю, что лежит…» не оставалось без продолжения)."""
    from ..services import pc
    pc.seen(); pc.ack(a.action)
    return {"ok": True}


@app.get("/api/pc/state")
def pc_state():
    from ..services import pc
    return {"alive": pc.alive(), "seen": pc.last_seen_iso(), "age_sec": pc.age_sec(), **pc.STATE}


@app.post("/api/pc/launch")
def pc_launch(p: PcLaunch, request: Request):
    """Открыть voice.bat из настроек. Только с самого компьютера — запуск процессов с телефона запрещён."""
    from .auth import is_local as _is_local
    if not _is_local(request):
        raise HTTPException(403, "Запуск голосового клиента доступен только с самого компьютера")
    from ..pc import launcher
    return launcher.launch(restart=bool(p.restart))


@app.get("/api/pc/organize/log")
def pc_organize_log():
    """Последние операции организации файлов, включая список перемещений."""
    return list(reversed(PC_ORGANIZE_LOG))


@app.get("/api/pc/organize/preview")
def pc_organize_preview():
    """Последний план, присланный Windows-клиентом, чтобы сайт не зависел от чата."""
    return PC_ORGANIZE_PREVIEW or {"status": "empty"}


@app.post("/api/pc/result")
async def pc_result(r: PcResult):
    """Результат команды с ПК (список найденных файлов, статус железа, план уборки) — в общий чат, чтобы было видно
    на сайте/в TG. План уборки ждёт «да» тем же механизмом подтверждения, что крупные суммы и выключение ПК."""
    from ..services import pc
    pc.seen()
    global PC_ORGANIZE_PREVIEW
    if r.kind == "organize_plan":
        PC_ORGANIZE_PREVIEW = {"status": "ready", "at": datetime.now().isoformat(timespec="seconds"), **r.extra, "text": r.text}
    if r.kind in ("tidy_plan", "organize_plan") and r.extra.get("plan_id") and r.extra.get("total"):
        key = "tidy" if r.kind == "tidy_plan" else "organize"
        agent._pending_set(r.channel, "confirm|" + _json.dumps({key: r.extra["plan_id"]}))
    agent._log_chat("assistant", r.text, r.channel)
    if r.kind in ("organize_done", "organize_undo"):
        PC_ORGANIZE_LOG.append({"at": datetime.now().isoformat(timespec="seconds"), "kind": r.kind, "text": r.text, "log": r.extra.get("log", {})})
        del PC_ORGANIZE_LOG[:-100]
    broadcast("chat", {"channel": r.channel, "actions": [f"pc_{r.kind}"]})
    if (r.channel.startswith("tg") or r.channel == "system") and agent.notify:   # system — ночная уборка: отчёт утром в Telegram
        try:
            await agent.notify(r.text)
        except Exception as e:  # pragma: no cover
            log.warning("pc_result → telegram: %s", e)
    return {"ok": True}


@app.post("/api/pc/clipboard")
async def pc_clipboard(c: PcClip):
    """«Запомни это»: содержимое буфера обмена → заметка или ссылка в Мозг."""
    txt = (c.text or "").strip()
    if not txt:
        return {"ok": False, "text": "В буфере обмена пусто, сэр."}
    urls = brain_notes.extract_urls(txt)
    if urls and len(txt) < 300:
        l = await brain_notes.add_link(urls[0], txt.replace(urls[0], "").strip() or None, source=c.channel)
        msg = f"Ссылка сохранена: {l.title or l.domain}."
        acts = ["add_link"]
    else:
        brain_notes.add_note(txt[:4000], source=c.channel)
        msg = f"Записал в Мозг: «{txt[:60]}{'…' if len(txt) > 60 else ''}»."
        acts = ["add_note"]
    agent._log_chat("assistant", msg, c.channel)
    broadcast("chat", {"channel": c.channel, "actions": acts})
    return {"ok": True, "text": msg}


@app.post("/api/vision/ask")
async def vision_ask(v: VisionIn):
    """Скриншот экрана с ПК → описание/перевод. Экран — приватный контент (как чеки): в облако он уходит
    только если пользователь явно выбрал brain.vision.where = cloud (а не «запасным путём» в auto).
    В local и в auto с недоступной локальной моделью — в облако НЕ отправляется (ФАЗА 6)."""
    from ..brain import llm
    ans = await llm.describe_image(v.image_b64, v.question, private=True)
    if not ans:
        st = llm.vision_status()
        ans = ("Зрение сейчас недоступно, сэр. " + ("Поставьте локальную vision-модель: ollama pull qwen2.5vl:3b и vision_model в настройках мозга."
                                                    if st == "выключено" else f"({st}) — не ответило, смотрите лог."))
    agent._log_chat("user", f"[скриншот] {v.question}", v.channel)
    agent._log_chat("assistant", ans, v.channel)
    broadcast("chat", {"channel": v.channel, "actions": ["vision"]})
    return {"text": ans}


@app.post("/api/cloud/preview")
def cloud_preview(body: CloudPreviewIn):
    """ФАЗА 6: «что именно уйдёт в облако» — ТОЛЬКО ЧТЕНИЕ. Ничего не отправляет и не пишет.
    Показывает текст так, как его увидит облако: с обезличиванием (brain.gemini.anonymize), если оно включено.
    В режиме local в облако не уходит ничего — will_send=false."""
    from ..brain import llm
    from ..config import cfg
    text = (body.text or "")[:8000]
    anonymized = bool(getattr(getattr(getattr(cfg, "brain", None), "gemini", None), "anonymize", False))
    shown = llm.anonymize(text) if anonymized else text
    cloud = llm.cloud_enabled()
    return {"text": shown, "anonymized": anonymized, "cloud_enabled": cloud, "mode": llm.MODE,
            "will_send": bool(cloud and llm.MODE in ("hybrid", "cloud") and text.strip()),
            # ФАЗА 6: в режиме cloud без brain.cloud.personal_tools облако не получает личные инструменты/память
            "personal_tools": bool(llm.cloud_personal_tools()),
            "note": "Черновик. Ничего не отправлено. В режиме local данные остаются на компьютере."}


@app.get("/api/health")
async def health():
    from ..brain import llm
    from .. import VERSION, BUILD
    from ..brain import persona
    return {"ok": True, "ollama": await llm.ollama_available(), "mode": llm.MODE, "time": datetime.now().isoformat(), "version": VERSION, "build": BUILD,
            "name": persona.display_name()}


# ---------------- дашборд ----------------
@app.get("/api/dashboard")
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
@app.get("/api/state")
def get_state():
    from ..services import state
    from ..brain import attention
    sn = state.snapshot()
    return {**sn, "line": state.line(), "budget_left": attention.budget_left(), "deferred": attention.queue_size(),
            "pc_alive": pc.alive()}


@app.get("/api/presence/events")
def get_presence_events(limit: int = 30):
    from ..services import events
    return [{"kind": e.kind, "key": e.key, "at": e.at.isoformat(), "quiet": e.quiet, "text": e.text, "data": e.data}
            for e in reversed(events.recent(max(1, min(limit, 200))))]


@app.get("/api/diagnose")
async def diagnose():
    from ..services import health
    res = await health.diagnose()
    health.record(res)
    return res


# ---------------- финансы ----------------
@app.exception_handler(finance.FinanceError)
async def _fin_err(_, exc: finance.FinanceError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/media/{path:path}", include_in_schema=False)
def media(path: str):
    from fastapi.responses import FileResponse
    f = (brain_notes.MEDIA_DIR / path).resolve()
    if not str(f).startswith(str(brain_notes.MEDIA_DIR.resolve())) or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"})


# ---------------- настройки, статус, экспорт, поиск ----------------
# ---------------- оформление сайта: одно на все устройства ----------------
@app.get("/api/ui-prefs")
def ui_prefs_get():
    """Тема, акцент, шрифт, обращение, порядок блоков — хранятся в базе, чтобы телефон и ПК выглядели одинаково."""
    raw = get_setting("ui.prefs")
    try:
        return {"prefs": _json.loads(raw) if raw else {}, "updated_at": get_setting("ui.prefs.at")}
    except ValueError:
        return {"prefs": {}, "updated_at": None}


@app.put("/api/ui-prefs")
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
            "name": "Марвин" if is_marvin else "Джарвис",
            "name_latin": "Marvin" if is_marvin else "Jarvis",
            "is_marvin": is_marvin, "is_jarvis": not is_marvin}


@app.get("/api/edition")
def edition_get():
    ed = get_setting("edition") or "jarvis"
    return _edition_payload(ed if ed in ("marvin", "jarvis") else "jarvis")


@app.post("/api/edition")
def edition_put(p: EditionIn):
    if p.edition not in ("marvin", "jarvis"):
        raise HTTPException(400, "edition: marvin|jarvis")
    set_setting("edition", p.edition)
    broadcast("state")
    return _edition_payload(p.edition)


@app.get("/api/client/info")
def client_info():
    """Карточка десктоп-клиента в настройках (WebView2 / App Mode)."""
    import platform as _platform
    from .. import identity, VERSION
    return {"app_name": identity.NAME or "Джарвис", "version": VERSION,
            "platform": _platform.system().lower(), "mode": "desktop_projection",
            "single_instance": True, "tray_enabled": True, "webview2_ready": True}


@app.get("/api/llm")
async def llm_info():
    """Статус LLM-ключа для карточки «Подключить LLM» (ожидает {enabled, model})."""
    from ..brain import llm
    on = await llm.ollama_available() if llm.OLLAMA_MODEL else False
    cloud = llm.cloud_enabled()
    model = llm.OLLAMA_MODEL if on else (llm.cloud_title() if cloud else None)
    return {"enabled": bool(on or cloud), "model": model,
            "mode": ("cloud" if cloud and not on else "hybrid" if cloud else "local" if on else "off")}


@app.get("/api/settings")
def settings_get():
    from ..config import read_settings
    return read_settings()


@app.put("/api/settings")
def settings_put(p: SettingsIn):
    from ..config import write_settings
    changed = write_settings(p.changes)
    # облако применяем на лету — перезапуск не нужен
    if any(k.startswith(("brain.cloud.", "brain.gemini.", "brain.mode", "brain.vision.", "brain.sorter.")) for k in changed):
        from ..brain import llm
        llm.reload_cloud_settings()
    if any(k.startswith("google.") for k in changed):
        _gcal_reload()
    if any(k.startswith(("owner.", "persona.")) for k in changed):
        from ..brain import persona
        persona.reload_persona()
        broadcast("settings", {"keys": changed})
    if any(k.startswith("brain.ollama.small_") for k in changed):
        from ..brain import llm
        llm.reload_small_settings()
    needs_restart = any(k.startswith(("telegram.", "backup.")) or (k.startswith("brain.ollama") and not k.startswith("brain.ollama.small_")) for k in changed)
    return {"changed": changed, "restart": needs_restart}


def _voice_status() -> dict:
    try:
        from ..voice import stt, tts
        return {"stt": stt.available(), "stt_model": stt.STT_MODEL, "stt_ready": stt._model is not None, "stt_error": stt.LAST_ERROR,
                "tts": tts.enabled(), "tts_engine": tts.ENGINE, "tts_ready": tts._model is not None or tts.ENGINE == "edge",
                "tts_error": tts.LAST_ERROR, "speaker": tts.SPEAKER, "reply": tts.REPLY_VOICE}
    except Exception as e:  # pragma: no cover
        return {"stt": False, "tts": False, "error": str(e)}


@app.get("/api/status")
async def status():
    """Состояние систем — показывается внутри настроек, отдельной страницы нет."""
    from ..brain import llm
    from ..config import cfg, DB_PATH
    from ..services.scheduler import last_backup
    from ..db import ChatMessage
    from sqlmodel import select
    ollama = await llm.ollama_available()
    diag = None if ollama else await llm.ollama_diagnose()
    with session() as s:
        last_tg = s.exec(select(ChatMessage).where(ChatMessage.channel.in_(["tg", "tg-voice"])).order_by(ChatMessage.id.desc())).first()
        counts = {"events": len(s.exec(select(Event)).all()), "tasks": len(s.exec(select(Task)).all()),
                  "notes": len(s.exec(select(Note)).all()), "links": len(s.exec(select(Link)).all()),
                  "transactions": len(s.exec(select(Transaction)).all())}
    tg_enabled = bool(cfg.telegram.token and cfg.telegram.owner_id)
    from .. import VERSION
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
        "errors": list(getattr(app.state, "errors", []))[-10:],
    }


@app.get("/api/phone")
async def phone_access(request: Request):
    """Адреса для телефона (Tailscale / домашний Wi-Fi) + QR-коды. Показывается в настройках."""
    import socket
    import subprocess
    from ..config import cfg
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
    from .auth import token as _tok, is_local as _is_lb
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


@app.get("/api/runs")
def runs(limit: int = 50, channel: str | None = None, only_bad: bool = False):
    """Журнал работы: последние ходы — путь, инструменты, время, где переспросил и где его поправили."""
    from ..services import trace
    return {"items": trace.recent(limit, channel, only_bad), "enabled": trace.enabled()}


@app.get("/api/runs/report")
def runs_report(days: int = 7):
    """Сводка «как я работал» за период + текст для чата."""
    from ..services import trace
    return {**trace.report(days), "text": trace.report_text(days)}


@app.post("/api/phone/rotate")
def phone_rotate(request: Request):
    """Новый ключ доступа: все телефоны, где сайт был открыт по старой ссылке, потеряют доступ до нового QR."""
    from .auth import rotate, is_local as _is_lb
    if not _is_lb(request):
        raise HTTPException(403, "Только с самого компьютера")
    rotate()
    return {"ok": True}


@app.post("/api/tg/login")
async def tg_login(body: TgLogin, request: Request):
    """Вход из Telegram Mini App: проверяем подпись initData, что это владелец — и ставим сессионную cookie.
    Публичный эндпоинт (сам является проверкой). Подробности — core/api/tg_auth.py."""
    from . import tg_auth
    from .auth import is_https
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


@app.post("/api/tg/logout")
def tg_logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("jarvis_tg", path="/")
    return resp


@app.get("/api/tg/miniapp")
async def tg_miniapp(request: Request):
    """Состояние Mini App для настроек: настроен ли адрес, поднят ли Funnel. Без секретов."""
    import subprocess
    from ..config import cfg
    from .auth import is_local as _is_lb
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


VOICES = [
    {"engine": "silero", "id": "eugene", "name": "Евгений", "kind": "мужской · спокойный, низкий (по умолчанию)"},
    {"engine": "silero", "id": "aidar", "name": "Айдар", "kind": "мужской · чуть моложе, бодрее"},
    {"engine": "silero", "id": "baya", "name": "Бая", "kind": "женский · мягкий"},
    {"engine": "silero", "id": "kseniya", "name": "Ксения", "kind": "женский · нейтральный"},
    {"engine": "silero", "id": "xenia", "name": "Ксения-2", "kind": "женский · звонче"},
    {"engine": "edge", "id": "ru-RU-DmitryNeural", "name": "Дмитрий (Microsoft)", "kind": "мужской · онлайн, самый естественный"},
    {"engine": "edge", "id": "ru-RU-SvetlanaNeural", "name": "Светлана (Microsoft)", "kind": "женский · онлайн"},
]
DEMO_TEXT = "Доброе утро, сэр. Минус семьсот рублей на такси, записал. Сегодня две встречи, первая в десять. Постарайтесь не опоздать."


@app.get("/api/voice/voices")
async def voice_list():
    from ..voice import tts
    return {"voices": VOICES, "current": {"engine": tts.ENGINE, "speaker": tts.SPEAKER, "edge_voice": tts.EDGE_VOICE, "reply": tts.REPLY_VOICE},
            "silero": tts.silero_available()}


@app.get("/api/voice/demo")
async def voice_demo(engine: str = "silero", voice: str = "eugene"):
    """Пример голоса (кэшируется в data/voice_demo)."""
    from fastapi.responses import FileResponse
    from ..config import DATA_DIR
    from ..voice import tts
    if not any(v["engine"] == engine and v["id"] == voice for v in VOICES):
        raise HTTPException(400, "unknown voice")
    out = DATA_DIR / "voice_demo" / f"{engine}_{voice}.{'wav' if engine == 'silero' else 'mp3'}"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        if engine == "silero":
            prev = tts.SPEAKER
            tts.SPEAKER = voice
            try:
                ok = await tts.speak_to_file(DEMO_TEXT, out)
            finally:
                tts.SPEAKER = prev
        else:
            import edge_tts
            try:
                await edge_tts.Communicate(tts.prepare(DEMO_TEXT), voice, rate="+5%").save(str(out))
                ok = out
            except Exception as e:
                raise HTTPException(502, f"Голоса Microsoft недоступны: {e}")
        if not ok:
            raise HTTPException(500, tts.LAST_ERROR or "не удалось озвучить")
    return FileResponse(out, media_type="audio/wav" if out.suffix == ".wav" else "audio/mpeg")


@app.post("/api/voice/pick")
async def voice_pick(body: VoicePick):
    """Выбрать голос: применяется сразу и пишется в config.yaml."""
    from ..config import write_settings
    from ..voice import tts
    if not any(v["engine"] == body.engine and v["id"] == body.voice for v in VOICES):
        raise HTTPException(400, "unknown voice")
    tts.ENGINE = body.engine
    changes = {"voice.tts.engine": body.engine}
    if body.engine == "silero":
        tts.SPEAKER = body.voice
        changes["voice.tts.speaker"] = body.voice
    else:
        tts.EDGE_VOICE = body.voice
        changes["voice.tts.edge_voice"] = body.voice
    write_settings(changes)
    return {"ok": True, "engine": tts.ENGINE, "speaker": tts.SPEAKER, "edge_voice": tts.EDGE_VOICE}


@app.post("/api/game")
async def game_mode(body: GameBody):
    from ..brain import llm
    return {"text": await llm.set_game_mode(body.on), "game_mode": llm.GAME_MODE}


@app.post("/api/status/small")
async def small_check():
    """«Проверить» у карточки малой модели: есть ли, отвечает ли, за сколько."""
    from ..brain import llm
    return await llm.small_check()


@app.post("/api/status/gemini")
async def gemini_check():
    from ..brain import llm
    llm.reload_cloud_settings()   # «проверить» = перечитать настройки + сбросить кэш + живой запрос
    return await llm.cloud_check()


# ---------------- Google Календарь (push-only) ----------------
def _gcal_reload():
    """Настройки Google меняются с сайта без перезапуска: перечитываем config."""
    from .. import config as _cfg
    from ..services import gcal
    _cfg.cfg = _cfg._load()
    gcal.cfg = _cfg.cfg
    return gcal


@app.get("/api/google/status")
def google_status():
    return _gcal_reload().status()


@app.get("/api/google/connect")
def google_connect():
    """Кнопка «подключить» на сайте: отдаём ссылку на согласие Google (открывать на этом же ПК — редирект на localhost)."""
    gcal = _gcal_reload()
    if not gcal.client_id() or not gcal.client_secret():
        raise HTTPException(400, "Сначала вставьте Client ID и Client secret в настройках (раздел «Google Календарь»)")
    return {"url": gcal.auth_url()}


@app.get("/api/google/callback", response_class=HTMLResponse)
async def google_callback(code: Optional[str] = None, state: Optional[str] = None, error: Optional[str] = None):
    gcal = _gcal_reload()
    page = "<html><head><meta charset='utf-8'><title>Джарвис · Google</title></head><body style='font-family:-apple-system,Segoe UI,sans-serif;background:#f4f3f1;color:#1d1d1f;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'><div style='text-align:center;max-width:520px;padding:32px'>{}</div></body></html>"
    if error or not code:
        return page.format(f"<h1 style='font-weight:500'>Не вышло</h1><p>{error or 'Google не вернул код'}.</p><p><a href='/settings'>← назад в настройки</a></p>")
    try:
        res = await gcal.finish_auth(code, state)
    except Exception as e:
        return page.format(f"<h1 style='font-weight:500'>Не вышло</h1><p>{e}</p><p><a href='/settings'>← назад в настройки</a></p>")
    # включаем флаг, если забыли
    from ..config import write_settings
    write_settings({"google.enabled": True})
    _gcal_reload()
    _asyncio.get_running_loop().create_task(gcal.sync_all())
    broadcast("google", {"connected": True})
    return page.format(f"<h1 style='font-weight:500'>Готово, сэр</h1><p>Google Календарь подключён{(' · ' + res.get('email')) if res.get('email') else ''}. Выгружаю события — это займёт минуту.</p><p><a href='/settings'>← назад в настройки</a></p><script>setTimeout(()=>location.href='/settings',2500)</script>")


@app.post("/api/google/sync")
async def google_sync():
    gcal = _gcal_reload()
    if not gcal.connected():
        raise HTTPException(400, "Google Календарь не подключён")
    return await gcal.sync_all(days_back=30)


@app.post("/api/google/disconnect")
def google_disconnect():
    gcal = _gcal_reload()
    gcal.disconnect()
    from ..config import write_settings
    write_settings({"google.enabled": False})
    return {"ok": True}


@app.post("/api/backup")
def backup_now():
    """Ручной снимок — даже если ночной бэкап выключен (force)."""
    from ..services.scheduler import backup_db
    dst = backup_db(force=True)
    return {"ok": dst is not None, "file": str(dst) if dst else None, "name": dst.name if dst else None}


@app.get("/api/backups")
def backups_list():
    from ..services.scheduler import list_backups
    return list_backups()


@app.post("/api/backups/restore")
def backups_restore(body: BackupRestoreIn):
    """Восстановить data/jarvis.db из выбранного backup-*.db. После — перезапуск start.bat."""
    from ..services.scheduler import restore_backup
    try:
        return restore_backup(body.name)
    except LookupError:
        raise HTTPException(404, "Такого бэкапа нет")
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/manifest.json", include_in_schema=False)
def manifest():
    return {
        "name": persona.display_name(), "short_name": persona.display_name(), "start_url": "/", "display": "standalone",
        "background_color": "#f4f3f0", "theme_color": "#f4f3f0", "lang": "ru",
        "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}],
        # Ярлыки PWA (долгое нажатие на иконку на телефоне): быстрая запись без блужданий по меню
        "shortcuts": [
            {"name": "Трата", "short_name": "Трата", "url": "/?quick=exp", "icons": [{"src": "/icon-192.png", "sizes": "192x192"}]},
            {"name": "Доход", "short_name": "Доход", "url": "/?quick=inc", "icons": [{"src": "/icon-192.png", "sizes": "192x192"}]},
            {"name": "Задача", "short_name": "Задача", "url": "/?quick=task", "icons": [{"src": "/icon-192.png", "sizes": "192x192"}]},
            {"name": "Мысль", "short_name": "Мысль", "url": "/?quick=note", "icons": [{"src": "/icon-192.png", "sizes": "192x192"}]},
        ],
    }


# ---------------- роутеры по доменам (ФАЗА 7) ----------------
# ИНВАРИАНТ: этот вызов стоит ПОСЛЕ app.include_router(crm) и ДО регистрации статики
# и catch-all-роута SPA в конце файла. Если подключить роутеры после catch-all,
# SPA перехватит /api/* и сайт перестанет открываться.
# Шаг 7.4: подключены routers/finance.py (42), routers/orders.py (22),
# routers/boards.py (17), routers/people.py (15) и routers/tasks.py (15).
# Шаг 7.5a: подключён routers/mind.py (32 роута: notes/links/facts/lessons/
# memory/graph/search/cards/chat/undo) — после tasks, до статики.
# ⚠️ /api/events/stream (SSE) и /api/chat/stream (POST-SSE) намеренно остаются
# в app.py: это живые каналы, по §3 reviews/P7_refactor.md они уезжают в
# routers/system.py на шаге 7.6. Здесь они регистрируются раньше любых
# параметрических /api/*-роутов. Не переставлять. См. reviews/P7_5a_mind.md.
from .routers import register as _register_routers  # noqa: E402

_register_routers(app)


# ---------------- сайт (Этап 2): раздаём собранную статику, если есть ----------------
web_dist = ROOT / "web" / "site"
if not web_dist.exists():
    web_dist = ROOT / "web" / "dist"
if (web_dist / "index.html").exists():
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        # До завершения мастера не отдаём приложение наружу: auth middleware
        # закроет /setup для проксированных клиентов, а локальный ПК увидит мастер.
        from ..config import setup_done
        if path == "setup":
            return HTMLResponse((ROOT / "core" / "api" / "setup.html").read_text(encoding="utf-8"))
        if not setup_done() and not path.startswith(("api", "media", "assets")):
            return RedirectResponse("/setup")
        # любой не-API маршрут (/finance, /calendar…) → index.html, роутинг делает React
        f = web_dist / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(web_dist / "index.html")
else:
    _preview = (ROOT / "core" / "api" / "preview.html").read_text(encoding="utf-8")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def preview_page():
        return _preview
