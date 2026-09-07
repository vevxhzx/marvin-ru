"""HTTP API ядра. Его используют: сайт (Этап 2) и голосовой клиент на ПК (Этап 3)."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from fastapi.responses import JSONResponse, RedirectResponse, HTMLResponse
import asyncio
import os
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..brain import agent
from ..config import ROOT
from ..db import session, Event, Task, Note, Link, Transaction, Debt, Recurring
from .. import identity
from ..services import brain_notes, calendar, finance, insights, pc, tasks
from ..services.scheduler import morning_digest_text

app = FastAPI(title="Assistant Core", version="0.1")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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


@app.get("/api/events/stream")
async def stream():
    q: _asyncio.Queue = _asyncio.Queue()
    _subscribers.add(q)

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


@app.get("/api/pc/state")
def pc_state():
    from ..services import pc
    return {"alive": pc.alive(), **pc.STATE}


class PcResult(BaseModel):
    text: str
    channel: str = "voice"
    kind: str = "result"          # result / find / screen / clipboard / status


@app.post("/api/pc/result")
def pc_result(r: PcResult):
    """Результат команды с ПК (список найденных файлов, статус железа) — в общий чат, чтобы было видно на сайте/в TG."""
    from ..services import pc
    pc.seen()
    agent._log_chat("assistant", r.text, r.channel)
    broadcast("chat", {"channel": r.channel, "actions": [f"pc_{r.kind}"]})
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
    return {
        "today": [e.model_dump() for e in calendar.events_today()],
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
    return d


@app.get("/api/events")
def events(start: Optional[datetime] = None, end: Optional[datetime] = None):
    return [_ev_out(e) for e in calendar.list_events(start, end, limit=1000)]


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


@app.get("/api/tasks")
def get_tasks(all: bool = False):
    return tasks.list_tasks(include_done=all, limit=500)


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


class CategoryPatch(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    keywords: Optional[str] = None
    budget: Optional[float] = None


@app.post("/api/finance/categories")
def fin_cat_add(c: CategoryIn):
    return finance.add_category(c.name, c.kind, c.icon, c.keywords, c.budget)


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


@app.delete("/api/notes/{nid}")
def note_del(nid: int):
    with session() as s:
        n = s.get(Note, nid)
        if not n:
            raise HTTPException(404)
        s.delete(n); s.commit()
    return {"ok": True}


@app.get("/api/links")
def links(q: Optional[str] = None):
    return brain_notes.list_links(200, q)


@app.post("/api/links")
async def link_add(l: LinkIn):
    return await brain_notes.add_link(l.url, l.comment, l.tags, "web")


@app.delete("/api/links/{lid}")
def link_del(lid: int):
    with session() as s:
        l = s.get(Link, lid)
        if not l:
            raise HTTPException(404)
        s.delete(l); s.commit()
    return {"ok": True}


@app.get("/api/memory")
def memory(days: int = 30, kind: Optional[str] = None, q: Optional[str] = None):
    if q:
        return brain_notes.search_memory(q, 100)
    return brain_notes.memory_feed(days, 300, kind)


# ---------------- настройки, статус, экспорт, поиск ----------------
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
    if any(k.startswith(("brain.cloud.", "brain.gemini.", "brain.mode", "brain.vision.")) for k in changed):
        from ..brain import llm
        llm.reload_cloud_settings()
    if any(k.startswith("google.") for k in changed):
        _gcal_reload()
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
                   "embed": await llm.embed_available(), "embed_model": llm.EMBED_MODEL},
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
    items = []
    if ts:
        items.append({"kind": "tailscale", "title": "Tailscale — из любой сети", "url": f"http://{ts}:{port}",
                      "alt": f"http://{host}:{port}", "qr": qr(f"http://{ts}:{port}")})
    if lan:
        items.append({"kind": "lan", "title": "Домашний Wi-Fi — телефон в той же сети", "url": f"http://{lan}:{port}", "qr": qr(f"http://{lan}:{port}")})
    # с какого адреса открыт сайт сейчас: если не localhost — телефон уже может так же
    opened_from = request.headers.get("host", "")
    return {"tailscale": bool(ts), "host": host, "port": port, "items": items, "opened_from": opened_from,
            "is_windows": __import__("os").name == "nt"}


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
