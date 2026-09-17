"""HTTP API ядра. Его используют: сайт (Этап 2) и голосовой клиент на ПК (Этап 3)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi.responses import JSONResponse, RedirectResponse
import asyncio
import logging
import os
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlmodel import select

from ..brain import agent
from ..config import ROOT
from ..db import session, Event, Task, Note, Link, Transaction, Debt, Recurring, get_setting, set_setting
from .. import identity
from ..services import brain_notes, calendar, finance, goals, insights, orders, pc, people, pulse, relations, tasks
from ..services.scheduler import morning_digest_text

log = logging.getLogger("assistant.api")

app = FastAPI(title="Assistant Core", version="0.1")
# CORS: сайт живёт на том же origin, что и API, — чужим сайтам доступ не нужен. Разрешаем только dev-сервер Vite.
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
# доступ с других устройств — только с токеном (см. core/api/auth.py); с самого ПК — свободно
from .auth import AuthMiddleware  # noqa: E402
app.add_middleware(AuthMiddleware)


# ---------------- живые обновления (сайт узнаёт о действиях из Telegram/голоса мгновенно) ----------------
import asyncio as _asyncio
import json as _json
from fastapi.responses import StreamingResponse

_subscribers: set[_asyncio.Queue] = set()


def broadcast(kind: str, payload: dict | None = None) -> None:
    """Сообщить всем открытым вкладкам сайта, что данные изменились."""
    msg = _json.dumps({"kind": kind, **(payload or {})}, ensure_ascii=False)
    for q in list(_subscribers):
        try:
            q.put_nowait(msg)
        except Exception:
            _subscribers.discard(q)


agent.on_change = broadcast


_pc_streams: set[int] = set()


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
class ChatIn(BaseModel):
    text: str
    channel: str = "web"


@app.post("/api/chat")
async def chat(inp: ChatIn):
    r = await agent.handle(inp.text, inp.channel)
    return {"text": r.text, "actions": r.actions, "via": r.via}


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
            await q.put(("done", {"text": r.text, "actions": r.actions, "via": r.via}))
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


@app.post("/api/undo")
def undo_last():
    from ..services import undo
    msg = undo.undo_last("web")
    broadcast("chat", {"channel": "web", "actions": ["undo"]})
    return {"ok": bool(msg), "text": msg or "Отменять нечего, сэр."}


@app.get("/api/chat/history")
def chat_history(limit: int = 40):
    """Общая история чата — одна и та же в Telegram и на сайте."""
    from ..db import ChatMessage
    from sqlmodel import select
    with session() as s:
        rows = s.exec(select(ChatMessage).order_by(ChatMessage.id.desc()).limit(limit)).all()
    return [{"id": m.id, "role": m.role, "text": m.text, "channel": m.channel, "at": m.created_at.isoformat()} for m in reversed(rows)]


# ---------------- ПК-клиент (voice.bat): пульс, состояние, результаты команд, зрение ----------------
class PcPing(BaseModel):
    mode: str = "idle"
    text: str = ""
    pending_results: bool = False


@app.post("/api/pc/ping")
def pc_ping(p: PcPing):
    """Голосовой клиент раз в 20 с сообщает, что жив и что делает (idle/listening/thinking/speaking/off)."""
    from ..services import pc
    was = pc.STATE.get("mode")
    pc.seen({"mode": p.mode, "text": p.text})
    if was != p.mode:
        broadcast("pc_state", {"mode": p.mode, "text": p.text})
    return {"ok": True}


class PcAck(BaseModel):
    action: str = ""


@app.post("/api/pc/ack")
def pc_ack(a: PcAck):
    """ПК подтверждает: команду из SSE получил и выполняет (чтобы «Смотрю, что лежит…» не оставалось без продолжения)."""
    from ..services import pc
    pc.seen(); pc.ack(a.action)
    return {"ok": True}


@app.get("/api/pc/state")
def pc_state():
    from ..services import pc
    return {"alive": pc.alive(), **pc.STATE}


class PcResult(BaseModel):
    text: str
    channel: str = "voice"
    kind: str = "result"          # result / find / screen / clipboard / status / tidy_plan / tidy_done / tidy_undo
    extra: dict = {}


@app.post("/api/pc/result")
async def pc_result(r: PcResult):
    """Результат команды с ПК (список найденных файлов, статус железа, план уборки) — в общий чат, чтобы было видно
    на сайте/в TG. План уборки ждёт «да» тем же механизмом подтверждения, что крупные суммы и выключение ПК."""
    from ..services import pc
    pc.seen()
    if r.kind == "tidy_plan" and r.extra.get("plan_id") and r.extra.get("total"):
        agent._pending_set(r.channel, "confirm|" + _json.dumps({"tidy": r.extra["plan_id"]}))
    agent._log_chat("assistant", r.text, r.channel)
    broadcast("chat", {"channel": r.channel, "actions": [f"pc_{r.kind}"]})
    if (r.channel.startswith("tg") or r.channel == "system") and agent.notify:   # system — ночная уборка: отчёт утром в Telegram
        try:
            await agent.notify(r.text)
        except Exception as e:  # pragma: no cover
            log.warning("pc_result → telegram: %s", e)
    return {"ok": True}


class PcClip(BaseModel):
    text: str
    channel: str = "voice"


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


class VisionIn(BaseModel):
    image_b64: str
    question: str = "Что на картинке?"
    private: bool = False
    channel: str = "voice"


@app.post("/api/vision/ask")
async def vision_ask(v: VisionIn):
    """Скриншот экрана с ПК → описание/перевод. Приватные (чеки, документы) — только локальная модель."""
    from ..brain import llm
    ans = await llm.describe_image(v.image_b64, v.question, private=v.private)
    if not ans:
        st = llm.vision_status()
        ans = ("Зрение сейчас недоступно, сэр. " + ("Поставьте локальную vision-модель: ollama pull qwen2.5vl:3b и vision_model в настройках мозга."
                                                    if st == "выключено" else f"({st}) — не ответило, смотрите лог."))
    agent._log_chat("user", f"[скриншот] {v.question}", v.channel)
    agent._log_chat("assistant", ans, v.channel)
    broadcast("chat", {"channel": v.channel, "actions": ["vision"]})
    return {"text": ans}


@app.post("/api/finance/import")
async def finance_import(request: Request):
    """Импорт выписки (CSV/PDF/XLSX Т-Банка). multipart: file=..., account=... (необязательно)."""
    from ..services import bank_import
    form = await request.form()
    up = form.get("file")
    if up is None:
        raise HTTPException(400, "Нет файла")
    data = await up.read()
    res = bank_import.import_file(up.filename or "", data, (form.get("account") or None))
    if res.added:
        broadcast("chat", {"channel": "web", "actions": ["import"]})
    agent._log_chat("assistant", res.text(), "web")
    return {"ok": bool(res.rows), "text": res.text(), "added": res.added, "dup": res.skipped_dup, "rows": res.rows}


# ---------------- аналитика ----------------
@app.get("/api/insights/forecast")
def insights_forecast(days: int = 30):
    from ..services import insights
    return {**insights.cash_forecast(days), "text": insights.cash_forecast_text()}


@app.get("/api/insights/subscriptions")
def insights_subs():
    from ..services import insights
    return insights.detect_subscriptions()


@app.get("/api/insights/streak")
def insights_streak():
    from ..services import insights
    return {**insights.streak(), "heatmap": insights.activity_heatmap(26)}


@app.get("/api/insights/birthdays")
def insights_bdays(days: int = 14):
    from ..services import insights
    return insights.upcoming_birthdays(days)


@app.get("/api/notes/{nid}/related")
async def note_related(nid: int):
    from ..services import insights
    return await insights.related_notes(nid)


@app.get("/api/links/{lid}/related")
async def link_related(lid: int):
    key = f"link:{lid}"
    if relations.enabled() and key in relations.pending(10_000):
        await relations.compute(key)
    return relations.related(key)


class RelationIn(BaseModel):
    status: str      # yes — подтвердить / no — убрать (крестик) / auto — вернуть


@app.put("/api/relations/{rid}")
def relation_set(rid: int, p: RelationIn):
    """Крестик на связи: status=no — пара больше никогда не предлагается. Переход по связи — status=yes."""
    r = relations.set_status(rid, p.status)
    if not r:
        raise HTTPException(404)
    return r


@app.get("/api/insights/weekly")
async def insights_weekly():
    from ..services import insights
    return {"text": await insights.weekly_digest() or "За неделю заметок не было — обозревать нечего, сэр."}


@app.get("/api/health")
async def health():
    from ..brain import llm
    from .. import VERSION
    return {"ok": True, "ollama": await llm.ollama_available(), "mode": llm.MODE, "time": datetime.now().isoformat(), "version": VERSION,
            "name": identity.title(), "name_latin": identity.NAME_LATIN}


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
        "digest": morning_digest_text(),
        "streak": {**insights.streak(), "heatmap": insights.activity_heatmap(26)},
        "birthdays": insights.upcoming_birthdays(14),
        "forecast": insights.cash_forecast(30),
        "pc": {"alive": pc.alive(), **pc.STATE},
        "timer": orders.timer_state(),
        "orders": {"open": [o for o in orders.list_orders() if o["status"] in ("new", "work", "review")][:5],
                   "unpaid": sum(o["left"] for o in orders.list_orders() if o["status"] not in ("new", "paid", "cancelled")),
                   "expected": orders.expected_income(30),
                   "late": pulse.late_payments()[:3] if fl["enabled"] and fl["late_nudge"] else []},
        "freelance": fl["enabled"],
        "goals": goals.list_goals()[:4],
        "runway": goals.runway(),
        "payments": goals.payment_check(7),
    }


# ---------------- календарь ----------------
class EventIn(BaseModel):
    title: str
    start: datetime
    duration_min: int = 60
    location: Optional[str] = None
    notes: Optional[str] = None
    remind_minutes: int = 30
    repeat: str = ""                       # "" / daily / weekly / monthly / yearly
    repeat_days: list[int] = []            # для weekly: 0=пн … 6=вс
    repeat_until: Optional[datetime] = None


def _ev_out(e: Event) -> dict:
    d = e.model_dump()
    d["repeat_label"] = calendar.fmt_repeat(e)
    d["repeat_anchor"] = getattr(e, "_anchor", e.start)
    d["done"] = calendar.is_done(e) if e.repeat else bool(e.done)
    return d


def _task_as_event(t: Task) -> dict:
    """Задача с дедлайном в календаре: тот же формат, что событие, + kind='task'. Записи в БД не дублируются —
    отметил в календаре → закрылась задача, перенёс задачу → сдвинулась в календаре."""
    all_day = t.due.hour == 23 and t.due.minute == 59
    # задача с конкретным временем занимает в календаре полчаса — видно, куда её подвинуть; «до конца дня» — без длительности
    end = t.due if all_day else t.due + timedelta(minutes=30)
    return {"id": -t.id, "task_id": t.id, "kind": "task", "title": t.title, "start": t.due, "end": end, "duration_min": 0 if all_day else 30,
            "location": None, "notes": None, "repeat": "", "repeat_label": "", "repeat_anchor": t.due, "done": t.done,
            "priority": t.priority, "all_day": all_day}


@app.get("/api/events")
def events(start: Optional[datetime] = None, end: Optional[datetime] = None, tasks_too: bool = False):
    out = [dict(_ev_out(e), kind="event") for e in calendar.list_events(start, end, limit=1000)]
    if tasks_too:
        with session() as s:
            q = select(Task).where(Task.due != None)  # noqa: E711
            if start:
                q = q.where(Task.due >= start)
            if end:
                q = q.where(Task.due <= end)
            for t in s.exec(q.limit(1000)).all():
                if not t.done or (t.done_at and start and t.done_at >= start):
                    out.append(_task_as_event(t))
        # дедлайны заказов — тоже в календаре (kind='order'), закрытые не показываем
        for o in orders.list_orders():
            if o["deadline"] and o["status"] in ("new", "work", "review") and (not start or o["deadline"] >= start) and (not end or o["deadline"] <= end):
                out.append({"id": -100000 - o["id"], "order_id": o["id"], "kind": "order", "status": o["status"], "title": f"Сдать: {o['title']}" + (f" · {o['client']}" if o["client"] else ""),
                            "start": o["deadline"], "end": o["deadline"], "duration_min": 0, "location": None, "notes": None, "repeat": "", "repeat_label": "",
                            "repeat_anchor": o["deadline"], "done": False, "priority": 2 if (o["days_left"] or 0) <= 2 else 1,
                            "all_day": o["deadline"].hour == 23 and o["deadline"].minute == 59})
    return out


@app.post("/api/events")
def create_event(e: EventIn):
    return _ev_out(calendar.add_event(e.title, e.start, e.duration_min, e.location, e.notes, e.remind_minutes, "web",
                                      repeat=e.repeat, repeat_days=e.repeat_days, repeat_until=e.repeat_until))


@app.put("/api/events/{event_id}")
def update_event(event_id: int, e: EventIn):
    ev = calendar.update_event(event_id, title=e.title, start=e.start, duration_min=e.duration_min, location=e.location, notes=e.notes,
                               remind_minutes=e.remind_minutes, repeat=e.repeat, repeat_days=e.repeat_days, repeat_until=e.repeat_until)
    if not ev:
        raise HTTPException(404)
    return _ev_out(ev)


class SkipIn(BaseModel):
    date: datetime


class EventDoneIn(BaseModel):
    done: bool = True
    date: Optional[datetime] = None     # для повторов: какой именно раз


@app.post("/api/events/{event_id}/done")
def done_event(event_id: int, p: EventDoneIn):
    """Галочка на событии — как на задаче. Одна запись: видна и в календаре, и в «Делах», и в Google (✓ в названии)."""
    ev = calendar.set_done(event_id, p.done, p.date)
    if not ev:
        raise HTTPException(404)
    d = _ev_out(ev)
    if ev.repeat and p.date:
        d["done"] = calendar.is_done(ev, p.date)
    return d


@app.post("/api/events/{event_id}/skip")
def skip_event(event_id: int, p: SkipIn):
    """Пропустить один повтор («в эту среду тренировки не будет»)."""
    ev = calendar.skip_occurrence(event_id, p.date)
    if not ev:
        raise HTTPException(404)
    return _ev_out(ev)


@app.delete("/api/events/{event_id}")
def remove_event(event_id: int):
    if not calendar.delete_event(event_id):
        raise HTTPException(404)
    return {"ok": True}


# ---------------- задачи ----------------
class TaskIn(BaseModel):
    title: str
    due: Optional[datetime] = None
    priority: int = 2
    project: Optional[str] = None


def _event_as_task(e: Event) -> dict:
    """Событие календаря в списке дел: тот же формат, что задача, + kind='event'. Отметил в делах → сделано и в календаре."""
    return {"id": -e.id, "event_id": e.id, "kind": "event", "title": e.title, "done": calendar.is_done(e), "priority": 2, "due": e.start,
            "end": e.end, "project": None, "source": e.source, "created_at": e.created_at, "done_at": e.done_at if not e.repeat else None,
            "repeat": e.repeat, "location": e.location}


@app.get("/api/tasks")
def get_tasks(all: bool = False, events_too: bool = False):
    out = [t.model_dump() for t in tasks.list_tasks(include_done=all, limit=500)]
    if events_too:
        # «сегодня по календарю»: события сегодняшнего дня (и вчерашние несделанные — чтобы не потерялись)
        d0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        for e in calendar.list_events(d0 - timedelta(days=1), d0 + timedelta(days=1), limit=200):
            if e.start < d0 and calendar.is_done(e):
                continue
            out.append(_event_as_task(e))
    return out


@app.get("/api/tasks/{task_id}")
def get_task(task_id: int):
    with session() as s:
        t = s.get(Task, task_id)
    if not t:
        raise HTTPException(404)
    return t


@app.post("/api/tasks")
def create_task(t: TaskIn):
    return tasks.add_task(t.title, t.due, t.priority, t.project, "web")


class TaskPatch(BaseModel):
    title: Optional[str] = None
    due: Optional[datetime] = None
    clear_due: bool = False
    priority: Optional[int] = None
    project: Optional[str] = None


@app.put("/api/tasks/{task_id}")
def patch_task(task_id: int, p: TaskPatch):
    fields = p.model_dump(exclude_none=True)
    fields.pop("clear_due", None)
    if p.clear_due:
        fields["due"] = None
    t = tasks.update_task(task_id, **fields)
    if not t:
        raise HTTPException(404)
    return t


@app.post("/api/tasks/{task_id}/undone")
def undone_task(task_id: int):
    with session() as s:
        t = s.get(Task, task_id)
        if not t:
            raise HTTPException(404)
        t.done, t.done_at = False, None
        s.add(t); s.commit(); s.refresh(t)
        return t


@app.post("/api/tasks/{task_id}/done")
def done_task(task_id: int):
    t = tasks.complete_task(task_id)
    if not t:
        raise HTTPException(404)
    return t


@app.delete("/api/tasks/{task_id}")
def remove_task(task_id: int):
    if not tasks.delete_task(task_id):
        raise HTTPException(404)
    return {"ok": True}


# ---------------- финансы ----------------
@app.exception_handler(finance.FinanceError)
async def _fin_err(_, exc: finance.FinanceError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


class TxIn(BaseModel):
    amount: float
    kind: str = "expense"
    category: Optional[str] = None
    note: Optional[str] = None
    account: Optional[str] = None
    to_account: Optional[str] = None
    date: Optional[datetime] = None


class TxPatch(BaseModel):
    amount: Optional[float] = None
    kind: Optional[str] = None
    category: Optional[str] = None
    note: Optional[str] = None
    account: Optional[str] = None
    to_account: Optional[str] = None
    date: Optional[datetime] = None


@app.get("/api/finance/summary")
def fin_summary(days: int = 30):
    return finance.summary(days)


@app.get("/api/finance/daily")
def fin_daily(days: int = 30):
    return finance.daily_series(days)


@app.get("/api/finance/transactions")
def fin_tx(days: int = 30):
    return finance.list_transactions(days, 1000)


@app.post("/api/finance/transactions")
def fin_add(t: TxIn):
    return finance.add_transaction(t.amount, t.kind, t.category, t.note, t.account, t.to_account, t.date, "web")


@app.put("/api/finance/transactions/{tx_id}")
def fin_tx_update(tx_id: int, p: TxPatch):
    return finance.update_transaction(tx_id, **p.model_dump(exclude_unset=True))


@app.delete("/api/finance/transactions/{tx_id}")
def fin_del(tx_id: int):
    if not finance.delete_transaction(tx_id):
        raise HTTPException(404)
    return {"ok": True}


class CategoryIn(BaseModel):
    name: str
    kind: str = "expense"
    icon: str = "•"
    keywords: str = ""
    budget: float = 0
    bucket: str = ""


class CategoryPatch(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    keywords: Optional[str] = None
    budget: Optional[float] = None
    bucket: Optional[str] = None


@app.post("/api/finance/categories")
def fin_cat_add(c: CategoryIn):
    return finance.add_category(c.name, c.kind, c.icon, c.keywords, c.budget, c.bucket)


@app.put("/api/finance/categories/{cid}")
def fin_cat_update(cid: int, p: CategoryPatch):
    return finance.update_category(cid, **p.model_dump(exclude_none=True))


@app.delete("/api/finance/categories/{cid}")
def fin_cat_del(cid: int):
    if not finance.delete_category(cid):
        raise HTTPException(404)
    return {"ok": True}


@app.get("/api/finance/budgets")
def fin_budgets():
    return {"budgets": finance.budgets(), "safe": finance.safe_to_spend()}


@app.get("/api/finance/categories")
def fin_cats():
    return finance.list_categories()


@app.get("/api/finance/accounts")
def fin_accounts():
    return finance.list_accounts()


class BalanceIn(BaseModel):
    name: str
    balance: float


@app.post("/api/finance/accounts/balance")
def fin_balance(b: BalanceIn):
    return finance.set_balance(b.name, b.balance)


class AccountIn(BaseModel):
    name: str
    kind: str = "bank"
    balance: float = 0


class AccountPatch(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    balance: Optional[float] = None
    is_main: Optional[bool] = None


@app.post("/api/finance/accounts")
def fin_account_add(a: AccountIn):
    return finance.add_account(a.name, a.kind, a.balance)


@app.put("/api/finance/accounts/{aid}")
def fin_account_update(aid: int, p: AccountPatch):
    return finance.update_account(aid, **p.model_dump(exclude_unset=True))


@app.delete("/api/finance/accounts/{aid}")
def fin_account_del(aid: int):
    if not finance.delete_account(aid):
        raise HTTPException(404)
    return {"ok": True}


class DebtIn(BaseModel):
    title: str
    total: float
    remaining: Optional[float] = None
    payment: float = 0
    rate: float = 0
    pay_day: int = 1
    creditor: Optional[str] = None


@app.get("/api/finance/debts")
def fin_debts():
    return [{**d.model_dump(), **finance.debt_forecast(d)} for d in finance.list_debts(include_closed=True)]


@app.post("/api/finance/debts")
def fin_debt_add(d: DebtIn):
    x = finance.add_debt(d.title, d.total, d.payment, d.rate, d.pay_day, d.creditor, d.remaining)
    return {**x.model_dump(), **finance.debt_forecast(x)}


class PayIn(BaseModel):
    amount: float
    account: Optional[str] = None
    date: Optional[datetime] = None


class DebtPatch(BaseModel):
    title: Optional[str] = None
    creditor: Optional[str] = None
    total: Optional[float] = None
    remaining: Optional[float] = None
    payment: Optional[float] = None
    rate: Optional[float] = None
    pay_day: Optional[int] = None
    closed: Optional[bool] = None


@app.post("/api/finance/debts/{debt_id}/pay")
def fin_debt_pay(debt_id: int, p: PayIn):
    d = finance.pay_debt(debt_id, p.amount, account=p.account, source="web", date=p.date)
    if not d:
        raise HTTPException(404)
    return {**d.model_dump(), **finance.debt_forecast(d)}


@app.get("/api/finance/debts/{debt_id}/payments")
def fin_debt_payments(debt_id: int):
    return finance.debt_payments(debt_id)


@app.put("/api/finance/debts/{debt_id}")
def fin_debt_update(debt_id: int, p: DebtPatch):
    d = finance.update_debt(debt_id, **p.model_dump(exclude_unset=True))
    return {**d.model_dump(), **finance.debt_forecast(d)}


@app.delete("/api/finance/debts/{debt_id}")
def fin_debt_del(debt_id: int):
    if not finance.delete_debt(debt_id):
        raise HTTPException(404)
    return {"ok": True}


class RecurringIn(BaseModel):
    title: str
    amount: float
    day: int = 1
    kind: str = "expense"
    category: Optional[str] = None
    period: str = "monthly"


@app.get("/api/finance/recurring")
def fin_recurring():
    return finance.list_recurring()


@app.post("/api/finance/recurring")
def fin_recurring_add(r: RecurringIn):
    return finance.add_recurring(r.title, r.amount, r.day, r.kind, r.category, r.period)


class RecurringPatch(BaseModel):
    title: Optional[str] = None
    amount: Optional[float] = None
    day: Optional[int] = None
    kind: Optional[str] = None
    category: Optional[str] = None
    period: Optional[str] = None
    account: Optional[str] = None
    active: Optional[bool] = None


@app.put("/api/finance/recurring/{rid}")
def fin_recurring_update(rid: int, p: RecurringPatch):
    return finance.update_recurring(rid, **p.model_dump(exclude_unset=True))


@app.delete("/api/finance/recurring/{rid}")
def fin_recurring_del(rid: int):
    with session() as s:
        r = s.get(Recurring, rid)
        if not r:
            raise HTTPException(404)
        r.active = False
        s.add(r); s.commit()
    return {"ok": True}


# ---------------- заказы / фриланс ----------------
class ClientIn(BaseModel):
    name: str
    contact: Optional[str] = None
    notes: Optional[str] = None


class OrderIn(BaseModel):
    title: str
    price: float = 0
    client: Optional[str] = None
    deadline: Optional[datetime] = None
    notes: Optional[str] = None
    estimate_h: float = 0
    status: str = "work"


class OrderPatch(BaseModel):
    title: Optional[str] = None
    price: Optional[float] = None
    client: Optional[str] = None
    deadline: Optional[datetime] = None
    notes: Optional[str] = None
    estimate_h: Optional[float] = None
    status: Optional[str] = None


class PaymentIn(BaseModel):
    amount: float
    note: Optional[str] = None
    account: Optional[str] = None
    date: Optional[datetime] = None   # когда пришли деньги (старые заказы задним числом)


class TimerIn(BaseModel):
    order_id: Optional[int] = None
    minutes: Optional[int] = None      # пусто — из настроек помодоро
    kind: str = "focus"


def _order_or_404(oid: int):
    o = orders.get_order(oid)
    if not o:
        raise HTTPException(404, "Заказ не найден")
    return o


@app.get("/api/orders/clients")
def clients_list():
    return [c.model_dump() for c in orders.list_clients()]


@app.post("/api/orders/clients")
def clients_add(c: ClientIn):
    r = orders.get_or_create_client(c.name)
    if not r:
        raise HTTPException(400, "Нужно имя клиента")
    if c.contact or c.notes:
        r = orders.update_client(r.id, contact=c.contact, notes=c.notes)
    return r.model_dump()


@app.put("/api/orders/clients/{cid}")
def clients_update(cid: int, c: ClientIn):
    r = orders.update_client(cid, name=c.name, contact=c.contact, notes=c.notes)
    if not r:
        raise HTTPException(404)
    return r.model_dump()


@app.delete("/api/orders/clients/{cid}")
def clients_del(cid: int):
    if not orders.delete_client(cid):
        raise HTTPException(404)
    return {"ok": True}


# ---------------- люди и граф ----------------
class PersonIn(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    contact: Optional[str] = None
    notes: Optional[str] = None
    aliases: Optional[str] = None
    birthday: Optional[str] = None
    tags: Optional[str] = None
    pay_mode: Optional[str] = None     # each / batch / monthly — как клиент платит
    pay_every: Optional[int] = None
    pay_days: Optional[str] = None


@app.get("/api/people/batch-hints")
def people_batch_hints():
    """Клиенты, у которых 2+ заказа оплачены одним днём, а режим ещё «за каждый» — предложить «пачкой»."""
    from ..services import pulse
    return pulse.guess_batch_clients()


@app.get("/api/people/kinds")
def people_kinds():
    """Типы «кто это»: встроенные + свои (people.kinds)."""
    return people.all_kinds()


@app.delete("/api/people/kinds/{kind}")
def people_kind_delete(kind: str):
    n = people.remove_custom_kind(kind)
    broadcast("people")
    return {"ok": True, "reassigned": n}


@app.get("/api/people")
def people_list():
    from ..services import people
    return people.list_people()


@app.post("/api/people")
def people_add(p: PersonIn):
    from ..services import people
    if not (p.name or "").strip():
        raise HTTPException(400, "Нужно имя")
    c = people.add_person(p.name, p.kind or None, p.contact, p.notes, p.aliases, p.birthday, p.tags)
    broadcast("chat", {"channel": "web", "actions": ["add_person"]})
    return people.card(c)


@app.get("/api/people/today")
def people_today():
    from ..services import people
    return people.people_today()


@app.get("/api/people/{cid}")
def people_card(cid: int):
    from ..services import people
    from ..db import Client
    with session() as s:
        c = s.get(Client, cid)
    if not c:
        raise HTTPException(404)
    return people.card(c, limit=20)


@app.put("/api/people/{cid}")
def people_update(cid: int, p: PersonIn):
    from ..services import people
    c = people.update_person(cid, **p.model_dump(exclude_none=True))
    if not c:
        raise HTTPException(404)
    broadcast("chat", {"channel": "web", "actions": ["update_person"]})
    return people.card(c, limit=20)


@app.get("/api/graph")
def graph_get(days: int = 365, focus: Optional[str] = None):
    from ..services import graph
    return graph.build(days=days, focus=focus)


@app.get("/api/graph/backlinks/{kind}/{ref_id}")
def graph_backlinks(kind: str, ref_id: int):
    from ..services import graph
    if kind not in ("note", "link", "person", "order", "tag"):
        raise HTTPException(400)
    return graph.backlinks(kind, ref_id)


@app.get("/api/orders")
def orders_list(status: Optional[str] = None, all: bool = False):
    return orders.list_orders(status, include_closed=all)


@app.get("/api/orders/stats")
def orders_stats(months: int = 6):
    return orders.stats(months)


@app.get("/api/orders/timer")
def orders_timer():
    return orders.timer_state()


class PomoSettingsIn(BaseModel):
    focus: Optional[int] = None
    short: Optional[int] = None
    long: Optional[int] = None
    long_every: Optional[int] = None
    auto_break: Optional[bool] = None
    sound: Optional[str] = None
    voice: Optional[bool] = None
    volume: Optional[float] = None


@app.get("/api/orders/pomodoro")
def pomo_get():
    return orders.pomo_settings()


class FreelanceIn(BaseModel):
    enabled: Optional[bool] = None
    late_days: Optional[int] = None
    late_nudge: Optional[bool] = None
    rate_check: Optional[bool] = None
    rate_tolerance: Optional[int] = None
    tax_percent: Optional[int] = None
    weekly: Optional[bool] = None


@app.get("/api/orders/freelance")
def freelance_get():
    pulse.auto_enable_if_used()
    return pulse.freelance_settings()


@app.put("/api/orders/freelance")
def freelance_put(p: FreelanceIn):
    r = pulse.save_freelance_settings(p.model_dump(exclude_none=True))
    broadcast("freelance_settings", r)
    return r


@app.get("/api/orders/pulse")
def pulse_get():
    """Пульс: задержки оплат + налог за месяц. Пусто, если режим фрилансера выключен."""
    st = pulse.freelance_settings()
    if not st["enabled"]:
        return {"enabled": False, "late": [], "tax": None}
    return {"enabled": True, "late": pulse.late_payments() if st["late_nudge"] else [], "tax": pulse.tax_month() if st["tax_percent"] else None, "settings": st}


@app.put("/api/orders/pomodoro")
def pomo_put(p: PomoSettingsIn):
    r = orders.save_pomo_settings(p.model_dump(exclude_none=True))
    broadcast("pomo_settings", r)
    return r


@app.post("/api/orders/timer")
def orders_timer_start(t: TimerIn):
    if t.order_id:
        _order_or_404(t.order_id)
    orders.start_session(t.order_id, t.minutes or None, t.kind, source="web")
    broadcast("timer", {"action": "start"})
    return orders.timer_state()


@app.delete("/api/orders/timer")
def orders_timer_stop():
    orders.stop_session()
    broadcast("timer", {"action": "stop"})
    return orders.timer_state()


@app.post("/api/orders")
def orders_add(o: OrderIn):
    try:
        r = orders.add_order(o.title, o.price, o.client, o.deadline, o.notes, o.estimate_h, o.status, source="web")
    except orders.OrderError as e:
        raise HTTPException(400, str(e))
    broadcast("order", {"id": r.id, "action": "add"})
    return orders.order_view(r)


@app.get("/api/orders/{oid}")
def orders_get(oid: int):
    o = _order_or_404(oid)
    return {**orders.order_view(o), "payments": [t.model_dump() for t in orders.payments_for(oid)],
            "sessions": [w.model_dump() for w in orders.sessions_for(oid)]}


@app.put("/api/orders/{oid}")
def orders_update(oid: int, p: OrderPatch):
    _order_or_404(oid)
    try:
        r = orders.update_order(oid, **p.model_dump(exclude_unset=True))
    except orders.OrderError as e:
        raise HTTPException(400, str(e))
    broadcast("order", {"id": oid, "action": "edit"})
    return orders.order_view(r)


@app.delete("/api/orders/{oid}")
def orders_del(oid: int):
    if not orders.delete_order(oid):
        raise HTTPException(404)
    broadcast("order", {"id": oid, "action": "delete"})
    return {"ok": True}


@app.post("/api/orders/{oid}/payments")
def orders_pay(oid: int, p: PaymentIn):
    _order_or_404(oid)
    try:
        t = orders.add_payment(oid, p.amount, p.note, p.account, source="web", date=p.date)
    except (orders.OrderError, finance.FinanceError) as e:
        raise HTTPException(400, str(e))
    broadcast("order", {"id": oid, "action": "pay"})
    return {"tx": t.model_dump(), "order": orders.order_view(orders.get_order(oid))}


# ---------------- цели / конверты / техники ----------------
class GoalIn(BaseModel):
    title: str
    target: float
    due: Optional[datetime] = None
    saved: float = 0
    icon: str = "🎯"


class GoalPatch(BaseModel):
    title: Optional[str] = None
    target: Optional[float] = None
    due: Optional[datetime] = None
    saved: Optional[float] = None
    icon: Optional[str] = None
    closed: Optional[bool] = None


class GoalPut(BaseModel):
    amount: float
    account: Optional[str] = None
    record_tx: bool = True


@app.get("/api/finance/goals")
def goals_list(all: bool = False):
    return goals.list_goals(include_closed=all)


@app.post("/api/finance/goals")
def goals_add(g: GoalIn):
    try:
        r = goals.add_goal(g.title, g.target, g.due, g.saved, g.icon, source="web")
    except finance.FinanceError as e:
        raise HTTPException(400, str(e))
    return goals.goal_view(r)


@app.put("/api/finance/goals/{gid}")
def goals_update(gid: int, p: GoalPatch):
    r = goals.update_goal(gid, **p.model_dump(exclude_unset=True))
    if not r:
        raise HTTPException(404)
    return goals.goal_view(r)


@app.delete("/api/finance/goals/{gid}")
def goals_del(gid: int):
    if not goals.delete_goal(gid):
        raise HTTPException(404)
    return {"ok": True}


@app.post("/api/finance/goals/{gid}/put")
def goals_put(gid: int, p: GoalPut):
    try:
        r = goals.put_to_goal(gid, p.amount, p.account, source="web", record_tx=p.record_tx)
    except finance.FinanceError as e:
        raise HTTPException(400, str(e))
    broadcast("chat", {"channel": "web", "actions": ["save_to_goal"]})
    return r


@app.get("/api/finance/techniques")
def finance_techniques():
    """Все «умные» финансы одним запросом: 50/30/20, месяц к месяцу, годовой резерв, хватит ли на платежи, подушка."""
    return {"buckets": goals.buckets_report(), "compare": goals.month_compare(), "annual": goals.annual_reserve(),
            "payments": goals.payment_check(7), "runway": goals.runway()}


# ---------------- второй мозг ----------------
class NoteIn(BaseModel):
    text: str
    tags: list[str] = []


class LinkIn(BaseModel):
    url: str
    comment: Optional[str] = None
    tags: list[str] = []


@app.get("/api/notes")
def notes(q: Optional[str] = None):
    return brain_notes.list_notes(200, q)


@app.post("/api/notes")
def note_add(n: NoteIn):
    return brain_notes.add_note(n.text, n.tags, "web")


@app.post("/api/notes/photo")
async def note_add_photo(file: UploadFile = File(...), text: str = Form("")):
    """Мысль с картинкой с сайта: файл + подпись. Описание картинки делает зрение (если доступно) — для поиска."""
    import base64
    from ..brain import llm
    raw = await file.read()
    if len(raw) > 20 * 1024 * 1024:
        raise HTTPException(413, "Картинка больше 20 МБ")
    about = ""
    try:
        about = await asyncio.wait_for(llm.describe_image(base64.b64encode(raw).decode(),
                                       "Опиши, что на фото, одной-двумя фразами: главное содержимое, текст на картинке если есть. Без вступлений.",
                                       private=False, short=True), timeout=90) or ""
    except Exception:
        about = ""
    body = text.strip()
    if about:
        body = (body + "\n\n" if body else "") + "📷 " + about.strip()
    n = brain_notes.add_note(body or "Фото", [], "web", image=brain_notes.save_image(raw), polish=bool(text.strip()))
    return n


@app.get("/media/{path:path}", include_in_schema=False)
def media(path: str):
    from fastapi.responses import FileResponse
    f = (brain_notes.MEDIA_DIR / path).resolve()
    if not str(f).startswith(str(brain_notes.MEDIA_DIR.resolve())) or not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, headers={"Cache-Control": "public, max-age=31536000, immutable"})


@app.post("/api/notes/{nid}/polish")
async def note_polish(nid: int):
    from ..services import polish
    ok = await polish.polish_note(nid)
    with session() as s:
        n = s.get(Note, nid)
    return {"ok": ok, "note": n}


class NoteEdit(BaseModel):
    text: Optional[str] = None
    title: Optional[str] = None
    tags: Optional[list[str]] = None
    append: Optional[str] = None


@app.put("/api/notes/{nid}")
def note_edit(nid: int, e: NoteEdit):
    n = brain_notes.update_note(nid, e.text, e.title, e.tags, e.append)
    if not n:
        raise HTTPException(404)
    broadcast("note", {"id": nid, "action": "edit"})
    return n


@app.delete("/api/notes/{nid}")
def note_del(nid: int):
    with session() as s:
        n = s.get(Note, nid)
        if not n:
            raise HTTPException(404)
        s.delete(n); s.commit()
    relations.forget("note", nid)
    return {"ok": True}


@app.get("/api/links")
def links(q: Optional[str] = None):
    return brain_notes.list_links(200, q)


@app.post("/api/links")
async def link_add(l: LinkIn):
    return await brain_notes.add_link(l.url, l.comment, l.tags, "web")


class LinkEdit(BaseModel):
    title: Optional[str] = None
    comment: Optional[str] = None
    tags: Optional[list[str]] = None


@app.put("/api/links/{lid}")
def link_edit(lid: int, e: LinkEdit):
    """Правка ссылки руками: заголовок, комментарий, теги. Адрес и превью не трогаем."""
    with session() as s:
        l = s.get(Link, lid)
        if not l:
            raise HTTPException(404)
        if e.title is not None:
            l.title = e.title.strip() or l.title
        if e.comment is not None:
            l.comment = e.comment.strip() or None
        if e.tags is not None:
            l.tags = ",".join(t.strip().lstrip("#") for t in e.tags if t.strip())
        s.add(l); s.commit(); s.refresh(l)
    broadcast("note", {"id": lid, "action": "edit_link"})
    return l


@app.delete("/api/links/{lid}")
def link_del(lid: int):
    with session() as s:
        l = s.get(Link, lid)
        if not l:
            raise HTTPException(404)
        s.delete(l); s.commit()
    relations.forget("link", lid)
    return {"ok": True}


# ---------------- память о хозяине (факты, слои, портрет) ----------------
class FactIn(BaseModel):
    text: str
    layer: str = "long"
    category: str = "быт"
    core: bool = False


class FactPatch(BaseModel):
    text: Optional[str] = None
    layer: Optional[str] = None
    category: Optional[str] = None
    core: Optional[bool] = None


@app.get("/api/facts")
def facts_list(layer: Optional[str] = None):
    from ..services import memory as mem
    rows = [f.model_dump(exclude={"vector"}) for f in mem.list_facts(layer)]
    return {"items": rows, "stats": mem.stats(), "enabled": mem.enabled(), "categories": list(mem.CATEGORIES)}


@app.post("/api/facts")
async def facts_add(p: FactIn):
    from ..services import memory as mem
    f = await mem.add_fact(p.text, p.layer, p.category, p.core, confidence=1.0)
    if not f:
        raise HTTPException(400, "Пусто или похоже на пароль/код — такое не запоминаю")
    return f.model_dump(exclude={"vector"})


@app.put("/api/facts/{fid}")
async def facts_patch(fid: int, p: FactPatch):
    from ..services import memory as mem
    f = await mem.update_fact(fid, p.text, p.layer, p.category, p.core, reason="поправлено вручную")
    if not f:
        raise HTTPException(404)
    return f.model_dump(exclude={"vector"})


@app.post("/api/facts/{fid}/forget")
def facts_forget(fid: int):
    from ..services import memory as mem
    f = mem.forget(fid)
    if not f:
        raise HTTPException(404)
    return f.model_dump(exclude={"vector"})


@app.post("/api/facts/{fid}/restore")
def facts_restore(fid: int):
    from ..services import memory as mem
    f = mem.restore(fid)
    if not f:
        raise HTTPException(404)
    return f.model_dump(exclude={"vector"})


@app.post("/api/facts/portrait")
async def facts_portrait():
    from ..services import memory as mem
    text = await mem.rebuild_portrait(force=True)
    return {"portrait": text or "", "stats": mem.stats()}


@app.post("/api/facts/style")
async def facts_style():
    from ..services import memory as mem
    text = await mem.rebuild_style(force=True)
    return {"style": text or "", "stats": mem.stats()}


class StyleIn(BaseModel):
    text: str


@app.put("/api/facts/style")
def facts_style_set(p: StyleIn):
    """Поправить описание стиля руками (или стереть — пустая строка)."""
    from ..db import set_setting
    from ..services import memory as mem
    set_setting(mem.STYLE_KEY, p.text.strip()[:800] or None)
    return {"style": p.text.strip()[:800], "stats": mem.stats()}


@app.get("/api/lessons")
def lessons_list():
    from ..services import judge
    return [l.model_dump(exclude={"vector"}) for l in judge.list_lessons()]


@app.delete("/api/lessons/{lid}")
def lessons_del(lid: int):
    from ..services import judge
    if not judge.forget_lesson(lid):
        raise HTTPException(404)
    return {"ok": True}


@app.post("/api/facts/nightly")
async def facts_nightly():
    """Кнопка «убраться сейчас» — то же, что ночная уборка."""
    from ..services import memory as mem
    return await mem.nightly()


@app.get("/api/memory")
def memory(days: int = 30, kind: Optional[str] = None, q: Optional[str] = None):
    if q:
        return brain_notes.search_memory(q, 100)
    return brain_notes.memory_feed(days, 300, kind)


# ---------------- настройки, статус, экспорт, поиск ----------------
# ---------------- оформление сайта: одно на все устройства ----------------
class UiPrefsIn(BaseModel):
    prefs: dict


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


@app.get("/api/settings")
def settings_get():
    from ..config import read_settings
    return read_settings()


class SettingsIn(BaseModel):
    changes: dict


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
    needs_restart = any(k.startswith(("telegram.", "brain.ollama", "backup.")) for k in changed)
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
        "pc": {"alive": pc.alive(), **pc.STATE},
        "vision": llm.vision_status(),
        "ollama": {"ok": ollama, "model": llm.OLLAMA_MODEL, "url": llm.OLLAMA_URL, "diag": diag, "gpu": llm.GPU_NOTE,
                   "embed": await llm.embed_available(), "embed_model": llm.EMBED_MODEL,
                   "small_model": llm.SMALL_MODEL, "small_ok": llm.small_model_active()},
        "gemini": {"enabled": llm.cloud_enabled(), "provider": llm.CLOUD_PROVIDER or "gemini", "title": llm.cloud_title(),
                   "model": (llm._cloud_model() if llm.CLOUD_PROVIDER not in ("", "gemini") else (llm._RESOLVED_MODEL or llm.GEMINI_MODEL)),
                   "auto": llm.GEMINI_AUTO, "mode": llm.MODE,
                   "proxy": (llm.CLOUD_PROXY if llm.CLOUD_PROVIDER not in ("", "gemini") else (llm.GEMINI_PROXY or ((getattr(cfg.telegram, "proxy", "") or "").strip() or None))),
                   "last_error": llm.LAST_CLOUD_ERROR or (llm.LAST_GEMINI_ERROR if llm.CLOUD_PROVIDER in ("", "gemini") else None),
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


class TgLogin(BaseModel):
    init_data: str


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
    resp.delete_cookie("assistant_tg", path="/")
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


class VoicePick(BaseModel):
    engine: str
    voice: str


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


class GameBody(BaseModel):
    on: bool = True


@app.post("/api/game")
async def game_mode(body: GameBody):
    from ..brain import llm
    return {"text": await llm.set_game_mode(body.on), "game_mode": llm.GAME_MODE}


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
    page = "<html><head><meta charset='utf-8'><title>Google Календарь</title></head><body style='font-family:-apple-system,Segoe UI,sans-serif;background:#f4f3f1;color:#1d1d1f;display:flex;align-items:center;justify-content:center;height:100vh;margin:0'><div style='text-align:center;max-width:520px;padding:32px'>{}</div></body></html>"
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
    from ..services.scheduler import backup_db
    dst = backup_db()
    return {"ok": dst is not None, "file": str(dst) if dst else None}


@app.get("/api/export/{what}.{fmt}")
def export(what: str, fmt: str):
    """Экспорт данных: /api/export/transactions.csv, /api/export/all.json …"""
    import csv
    import io
    from fastapi.responses import Response
    from sqlmodel import select
    tables = {"transactions": Transaction, "events": Event, "tasks": Task, "notes": Note, "links": Link, "debts": Debt, "recurring": Recurring}
    if what != "all" and what not in tables:
        raise HTTPException(404)
    with session() as s:
        def _row(r):
            d = r.model_dump()
            first = [k for k in ("id", "date", "start", "created_at", "title", "amount", "kind", "category") if k in d]
            return {k: d[k] for k in first} | {k: v for k, v in d.items() if k not in first}
        data = {name: [_row(r) for r in s.exec(select(model)).all()] for name, model in tables.items() if what in ("all", name)}
    stamp = datetime.now().strftime("%Y%m%d")
    if fmt == "json":
        body = _json.dumps(data if what == "all" else data[what], ensure_ascii=False, default=str, indent=1)
        return Response(body, media_type="application/json", headers={"Content-Disposition": f'attachment; filename="export-{what}-{stamp}.json"'})
    if fmt == "csv":
        buf = io.StringIO()
        buf.write("\ufeff")  # BOM — чтобы Excel открыл кириллицу
        for name, rows in data.items():
            if what == "all":
                buf.write(f"# {name}\n")
            if rows:
                w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()), delimiter=";")
                w.writeheader()
                for r in rows:
                    w.writerow({k: (str(v).replace("T", " ")[:19] if isinstance(v, datetime) else v) for k, v in r.items()})
            buf.write("\n")
        return Response(buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="export-{what}-{stamp}.csv"'})
    raise HTTPException(400, "fmt: csv или json")


@app.get("/api/search/semantic")
async def semantic_search(q: str, limit: int = 12):
    from ..services import semantic
    return await semantic.search(q, limit)


@app.post("/api/search/reindex")
async def semantic_reindex():
    from ..services import semantic
    return {"indexed": await semantic.index_pending(500)}


@app.get("/manifest.json", include_in_schema=False)
def manifest():
    return {
        "name": identity.title(), "short_name": identity.title(), "start_url": "/", "display": "standalone",
        "background_color": "#f4f3f0", "theme_color": "#f4f3f0", "lang": "ru",
        "icons": [{"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                  {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}],
    }


# ---------------- сайт (Этап 2): раздаём собранную статику, если есть ----------------

# ---------------- мастер первого запуска ----------------
from .. import setup_wizard as _sw  # noqa: E402


class _CloudCheckIn(BaseModel):
    provider: str
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    proxy: str = ""


class _TgCheckIn(BaseModel):
    token: str
    proxy: str = ""


class _PullIn(BaseModel):
    model: str


class _SetupSaveIn(BaseModel):
    changes: dict


@app.get("/api/setup/state")
async def setup_state():
    from ..config import setup_done, read_settings
    from .. import identity
    return {"done": setup_done(), "name": identity.title(), "settings": read_settings()}


@app.get("/api/setup/hardware")
async def setup_hardware():
    from ..config import cfg
    hw = await _sw.detect_hardware(str(cfg.brain.ollama.url))
    return {"hardware": _sw.hardware_dict(hw), "recommend": _sw.recommend(hw)}


@app.post("/api/setup/check/telegram")
async def setup_check_tg(p: _TgCheckIn):
    return await _sw.check_telegram(p.token, p.proxy)


@app.post("/api/setup/telegram/owner")
async def setup_tg_owner(p: _TgCheckIn):
    """Ждём сообщение владельца боту и возвращаем его ID (до 90 с)."""
    return await _sw.wait_owner_id(p.token, p.proxy)


@app.post("/api/setup/check/cloud")
async def setup_check_cloud(p: _CloudCheckIn):
    return await _sw.check_cloud(p.provider, p.api_key, p.model, p.base_url, p.proxy)


@app.get("/api/setup/providers")
def setup_providers():
    from ..brain import llm
    out = []
    for k, v in llm.PROVIDERS.items():
        out.append({"id": k, **{kk: vv for kk, vv in v.items() if kk != "base_url"}})
    out.append({"id": "gemini", "title": "Google Gemini", "free": True, "ru_ok": False, "key_url": "https://aistudio.google.com/apikey"})
    return out


@app.get("/api/setup/ollama")
async def setup_ollama():
    from ..config import cfg
    st = await _sw.ollama_status(str(cfg.brain.ollama.url))
    if not st["running"] and st["installed"]:
        if _sw.start_ollama_if_installed():
            await asyncio.sleep(2.5)
            st = await _sw.ollama_status(str(cfg.brain.ollama.url))
    return st


@app.post("/api/setup/ollama/pull")
async def setup_ollama_pull(p: _PullIn):
    from ..config import cfg
    if _sw.pull_progress(p.model)["status"] in ("starting", "pulling manifest") or (_sw.pull_progress(p.model)["total"] and _sw.pull_progress(p.model)["status"] not in ("success", "error")):
        return _sw.pull_progress(p.model)
    asyncio.get_event_loop().create_task(_sw.ollama_pull(str(cfg.brain.ollama.url), p.model))
    await asyncio.sleep(0.5)
    return _sw.pull_progress(p.model)


@app.get("/api/setup/ollama/pull/{model:path}")
def setup_ollama_pull_progress(model: str):
    return _sw.pull_progress(model)


@app.post("/api/setup/save")
async def setup_save(p: _SetupSaveIn):
    """Записать настройки мастера. Имя ассистента и токен требуют перезапуска — мастер сам об этом скажет."""
    from ..config import write_settings
    changed = write_settings(p.changes)
    from ..brain import llm
    llm.reload_cloud_settings()
    return {"changed": changed}


@app.post("/api/setup/restart")
async def setup_restart():
    """Завершить процесс; start.bat / docker перезапустят его с новым config.yaml."""
    async def _die():
        await asyncio.sleep(0.8)
        os._exit(0)
    asyncio.get_event_loop().create_task(_die())
    return {"ok": True}


def _setup_html() -> str:
    return (ROOT / "core" / "api" / "setup.html").read_text(encoding="utf-8")


web_dist = ROOT / "web" / "site"
if not web_dist.exists():
    web_dist = ROOT / "web" / "dist"
if (web_dist / "index.html").exists():
    from fastapi.responses import FileResponse

    app.mount("/assets", StaticFiles(directory=web_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        # любой не-API маршрут (/finance, /calendar…) → index.html, роутинг делает React
        if path == "setup":
            return HTMLResponse(_setup_html())
        f = web_dist / path
        if path and f.is_file():
            return FileResponse(f)
        from ..config import setup_done
        if not setup_done() and not path.startswith(("api", "media", "assets")):
            return RedirectResponse("/setup")
        return FileResponse(web_dist / "index.html")
else:
    _preview = (ROOT / "core" / "api" / "preview.html").read_text(encoding="utf-8")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def preview_page():
        from ..config import setup_done
        if not setup_done():
            return RedirectResponse("/setup")
        return _preview

    @app.get("/setup", response_class=HTMLResponse, include_in_schema=False)
    def setup_page_noweb():
        return HTMLResponse(_setup_html())
