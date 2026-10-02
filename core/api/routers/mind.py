"""Мозг (ФАЗА 7, шаг 7.5a). Перенос механический из core/api/app.py, логика не менялась.

Заметки, ссылки, факты, уроки, память, граф, поиск, карточки и чат/undo.
SSE-потоки НЕ здесь: `/api/chat/stream` (POST-SSE) и `/api/events/stream` остаются
в `core/api/app.py` до шага 7.6 (см. `reviews/P7_5a_mind.md`).
"""
from __future__ import annotations

import asyncio
import asyncio as _asyncio
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field, field_validator

from ...brain import agent
from ...db import Link, Note, session
from ...services import brain_notes, relations
from .._shared import broadcast
from ..schemas import (ChatIn, FactIn, FactPatch, LinkEdit, LinkIn, NoteEdit, NoteIn, StyleIn)

router = APIRouter()
# Новые маршруты правки заметок — отдельным роутером: frozen-таблица MIND_ROUTES в
# tests/test_review_a_contract.py описывает роуты, перенесённые из app.py на шаге 7.5a,
# её не трогаем (иначе контракт-тест упадёт на «лишних» маршрутах).
polish_router = APIRouter()


def register(app) -> None:
    app.include_router(router)
    app.include_router(polish_router)


@router.get("/api/cards/{name}")
def card_file(name: str):
    """PNG карточки из кэша. Принимаем только имя файла — защита от обхода каталога."""
    import re
    from pathlib import Path
    from fastapi.responses import FileResponse
    from ...config import DATA_DIR
    if not re.fullmatch(r"[A-Za-z0-9_\-]+\.png", name or ""):
        raise HTTPException(status_code=404, detail="нет такой карточки")
    p = Path(DATA_DIR) / "card_cache" / name
    if not p.exists():
        raise HTTPException(status_code=404, detail="нет такой карточки")
    return FileResponse(str(p), media_type="image/png", headers={"Cache-Control": "public, max-age=31536000"})


@router.post("/api/chat")
async def chat(inp: ChatIn):
    from ..app import _card_for  # хелпер остаётся в app.py до шага 7.6
    r = await agent.handle(inp.text, inp.channel)
    card = await _asyncio.to_thread(_card_for, r)
    return {"text": r.text, "actions": r.actions, "via": r.via, "card": card}


@router.post("/api/undo")
def undo_last():
    from ...services import undo
    msg = undo.undo_last("web")
    broadcast("chat", {"channel": "web", "actions": ["undo"]})
    return {"ok": bool(msg), "text": msg or "Отменять нечего, сэр."}


@router.get("/api/chat/history")
def chat_history(limit: int = 40):
    """Общая история чата — одна и та же в Telegram и на сайте."""
    from ...db import ChatMessage
    from sqlmodel import select
    with session() as s:
        rows = s.exec(select(ChatMessage).order_by(ChatMessage.id.desc()).limit(limit)).all()
    return [{"id": m.id, "role": m.role, "text": m.text, "channel": m.channel, "at": m.created_at.isoformat()} for m in reversed(rows)]


@router.get("/api/notes/{nid}/related")
async def note_related(nid: int):
    from ...services import insights
    return await insights.related_notes(nid)


@router.get("/api/links/{lid}/related")
async def link_related(lid: int):
    key = f"link:{lid}"
    if relations.enabled() and key in relations.pending(10_000):
        await relations.compute(key)
    return relations.related(key)


@router.get("/api/graph")
def graph_get(days: int = 365, focus: Optional[str] = None):
    from ...services import graph
    return graph.build(days=days, focus=focus)


@router.get("/api/graph/backlinks/{kind}/{ref_id}")
def graph_backlinks(kind: str, ref_id: int):
    from ...services import graph
    if kind not in ("note", "link", "person", "order", "tag", "debt", "goal"):
        raise HTTPException(400)
    return graph.backlinks(kind, ref_id)


# ---------------- второй мозг ----------------
@router.get("/api/notes")
def notes(q: Optional[str] = None):
    return brain_notes.list_notes(200, q)


@router.post("/api/notes")
def note_add(n: NoteIn):
    return brain_notes.add_note(n.text, n.tags, "web")


@router.post("/api/notes/photo")
async def note_add_photo(file: UploadFile = File(...), text: str = Form("")):
    """Мысль с картинкой с сайта: файл + подпись. Описание картинки делает зрение (если доступно) — для поиска."""
    import base64
    from ...brain import llm
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


@router.post("/api/notes/{nid}/polish")
async def note_polish(nid: int):
    from ...services import polish
    ok = await polish.polish_note(nid)
    with session() as s:
        n = s.get(Note, nid)
    return {"ok": ok, "note": n}


# ---------------- правка заметок нейронкой: было/стало + история версий ----------------
# Схемы держим здесь же: core/api/schemas.py не наш файл. Ответы ошибок — те же, что у соседей:
# LLM недоступна → 503 с русским текстом (фронт покажет тост), нет заметки/версии → 404/400.
class PolishIn(BaseModel):
    mode: str = "rewrite"        # rewrite — привести к одному смыслу, expand — расширить тему


class ApplyIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=20000)

    @field_validator("text")
    @classmethod
    def _t(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("пустой текст")
        return v


class RevertIn(BaseModel):
    revision_id: Optional[int] = None


def _note_or_404(nid: int) -> Note:
    with session() as s:
        n = s.get(Note, nid)
    if not n:
        raise HTTPException(404, "Заметка не найдена")
    return n


@polish_router.post("/api/mind/notes/{nid}/polish")
async def note_refine(nid: int, body: Optional[PolishIn] = None):
    """Предложить новый текст заметки. Ничего не сохраняет — применение отдельным /apply."""
    from ...services import polish
    _note_or_404(nid)
    mode = (body.mode if body else "rewrite") or "rewrite"
    if mode not in ("rewrite", "expand"):
        raise HTTPException(400, "mode должен быть rewrite или expand")
    try:
        r = await polish.refine_note(nid, mode)
    except polish.RevisionError as e:
        raise HTTPException(400, str(e))
    except polish.PolishError as e:
        raise HTTPException(503, str(e))   # текст пойдёт в тост на сайте как есть
    return {"original": r["original"], "polished": r["polished"], "mode": r["mode"], "revision_id": r["revision_id"]}


@polish_router.post("/api/mind/notes/{nid}/apply")
def note_apply(nid: int, e: ApplyIn):
    """Применить новый текст: текущий уходит в историю версий, оригинал остаётся в raw."""
    from ...services import brain_notes
    _note_or_404(nid)
    n = brain_notes.update_note(nid, text=e.text)
    if not n:
        raise HTTPException(404, "Заметка не найдена")
    broadcast("note", {"id": nid, "action": "edit"})
    return {"ok": True, "text": n.text, "note": n}


@polish_router.post("/api/mind/notes/{nid}/revert")
def note_revert(nid: int, body: Optional[RevertIn] = None):
    """Откат на предыдущую версию (или конкретную, revision_id). Актуальный текст — в ответе."""
    from ...services import polish
    _note_or_404(nid)
    try:
        n = polish.revert_note(nid, body.revision_id if body else None)
    except polish.RevisionError as e:
        raise HTTPException(400, str(e))
    if not n:
        raise HTTPException(404, "Заметка не найдена")
    broadcast("note", {"id": nid, "action": "edit"})
    return {"ok": True, "text": n.text, "note": n}


@polish_router.get("/api/mind/notes/{nid}/revisions")
def note_revisions(nid: int):
    """История версий заметки: только текст + дата, без LLM."""
    from ...services import polish
    _note_or_404(nid)
    return polish.list_revisions(nid)


@router.put("/api/notes/{nid}")
def note_edit(nid: int, e: NoteEdit):
    n = brain_notes.update_note(nid, e.text, e.title, e.tags, e.append)
    if not n:
        raise HTTPException(404)
    broadcast("note", {"id": nid, "action": "edit"})
    return n


@router.delete("/api/notes/{nid}")
def note_del(nid: int):
    with session() as s:
        n = s.get(Note, nid)
        if not n:
            raise HTTPException(404)
        s.delete(n); s.commit()
    relations.forget("note", nid)
    from ...services import polish
    polish.forget_revisions(nid)   # история версий ушла вместе с заметкой (id в SQLite может достаться новой)
    return {"ok": True}


@router.get("/api/links")
def links(q: Optional[str] = None):
    return brain_notes.list_links(200, q)


@router.post("/api/links")
async def link_add(l: LinkIn):
    return await brain_notes.add_link(l.url, l.comment, l.tags, "web")


@router.put("/api/links/{lid}")
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


@router.delete("/api/links/{lid}")
def link_del(lid: int):
    with session() as s:
        l = s.get(Link, lid)
        if not l:
            raise HTTPException(404)
        s.delete(l); s.commit()
    relations.forget("link", lid)
    return {"ok": True}


# ---------------- память о хозяине (факты, слои, портрет) ----------------
@router.get("/api/facts")
def facts_list(layer: Optional[str] = None):
    from ...services import memory as mem
    rows = [f.model_dump(exclude={"vector"}) for f in mem.list_facts(layer)]
    return {"items": rows, "stats": mem.stats(), "enabled": mem.enabled(), "categories": list(mem.CATEGORIES)}


@router.post("/api/facts")
async def facts_add(p: FactIn):
    from ...services import memory as mem
    f = await mem.add_fact(p.text, p.layer, p.category, p.core, confidence=1.0)
    if not f:
        raise HTTPException(400, "Пусто или похоже на пароль/код — такое не запоминаю")
    return f.model_dump(exclude={"vector"})


# Литеральный путь ПЕРЕД /api/facts/{fid}: Starlette сверяет роуты по порядку
# регистрации, иначе «style» уходит в fid как int → 422 на PUT /api/facts/style
# (находка P1 ревью A; сайт: api.setStyle → страница «Память»).
@router.put("/api/facts/style")
def facts_style_set(p: StyleIn):
    """Поправить описание стиля руками (или стереть — пустая строка)."""
    from ...db import set_setting
    from ...services import memory as mem
    set_setting(mem.STYLE_KEY, p.text.strip()[:800] or None)
    return {"style": p.text.strip()[:800], "stats": mem.stats()}


@router.put("/api/facts/{fid}")
async def facts_patch(fid: int, p: FactPatch):
    from ...services import memory as mem
    f = await mem.update_fact(fid, p.text, p.layer, p.category, p.core, reason="поправлено вручную")
    if not f:
        raise HTTPException(404)
    return f.model_dump(exclude={"vector"})


@router.post("/api/facts/{fid}/forget")
def facts_forget(fid: int):
    from ...services import memory as mem
    f = mem.forget(fid)
    if not f:
        raise HTTPException(404)
    return f.model_dump(exclude={"vector"})


@router.post("/api/facts/{fid}/restore")
def facts_restore(fid: int):
    from ...services import memory as mem
    f = mem.restore(fid)
    if not f:
        raise HTTPException(404)
    return f.model_dump(exclude={"vector"})


@router.post("/api/facts/portrait")
async def facts_portrait():
    from ...services import memory as mem
    text = await mem.rebuild_portrait(force=True)
    return {"portrait": text or "", "stats": mem.stats()}


@router.post("/api/facts/style")
async def facts_style():
    from ...services import memory as mem
    text = await mem.rebuild_style(force=True)
    return {"style": text or "", "stats": mem.stats()}


@router.get("/api/lessons")
def lessons_list():
    from ...services import judge
    return [l.model_dump(exclude={"vector"}) for l in judge.list_lessons()]


@router.delete("/api/lessons/{lid}")
def lessons_del(lid: int):
    from ...services import judge
    if not judge.forget_lesson(lid):
        raise HTTPException(404)
    return {"ok": True}


@router.post("/api/facts/nightly")
async def facts_nightly():
    """Кнопка «убраться сейчас» — то же, что ночная уборка."""
    from ...services import memory as mem
    return await mem.nightly()


@router.get("/api/memory")
def memory(days: int = 30, kind: Optional[str] = None, q: Optional[str] = None):
    if q:
        return brain_notes.search_memory(q, 100)
    return brain_notes.memory_feed(days, 300, kind)


@router.get("/api/search/semantic")
async def semantic_search(q: str, limit: int = 12):
    from ...services import semantic
    return await semantic.search(q, limit)


@router.post("/api/search/reindex")
async def semantic_reindex():
    from ...services import semantic
    return {"indexed": await semantic.index_pending(500)}
