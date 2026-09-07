"""Смысловой поиск по «Мозгу» (заметки + ссылки) на локальных эмбеддингах Ollama.

Векторы храним в таблице Embedding как JSON. Если модели эмбеддингов нет — поиск падает обратно на обычный по подстроке.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math

from sqlmodel import select

from ..brain import llm
from ..db import Embedding, Link, Note, session

log = logging.getLogger("assistant.semantic")


def _text_of(row) -> str:
    if isinstance(row, Note):
        return " ".join(filter(None, [row.title, row.text, row.tags]))
    return " ".join(filter(None, [row.title, row.description, row.comment, row.tags, row.domain]))


def _h(t: str) -> str:
    return hashlib.sha1(t.encode()).hexdigest()[:16]


async def index_pending(limit: int = 50) -> int:
    """Считает эмбеддинги для новых/изменённых заметок и ссылок. Возвращает, сколько проиндексировали."""
    if not await llm.embed_available():
        return 0
    todo: list[tuple[str, int, str]] = []
    with session() as s:
        have = {(e.ref_table, e.ref_id): e for e in s.exec(select(Embedding).where(Embedding.model == llm.EMBED_MODEL))}
        for table, model in (("note", Note), ("link", Link)):
            for row in s.exec(select(model)):
                txt = _text_of(row).strip()
                if not txt:
                    continue
                e = have.get((table, row.id))
                if e is None or e.text_hash != _h(txt):
                    todo.append((table, row.id, txt))
        # чистим эмбеддинги удалённых записей
        ids = {("note", n.id) for n in s.exec(select(Note))} | {("link", l.id) for l in s.exec(select(Link))}
        for key, e in have.items():
            if key not in ids:
                s.delete(e)
        s.commit()
    todo = todo[:limit]
    if not todo:
        return 0
    vecs = await llm.embed([t for _, _, t in todo])
    if not vecs:
        return 0
    with session() as s:
        for (table, rid, txt), v in zip(todo, vecs):
            e = s.exec(select(Embedding).where(Embedding.ref_table == table, Embedding.ref_id == rid, Embedding.model == llm.EMBED_MODEL)).first()
            if e is None:
                e = Embedding(ref_table=table, ref_id=rid, model=llm.EMBED_MODEL, vector="", text_hash="")
            e.vector = json.dumps([round(x, 6) for x in v])
            e.text_hash = _h(txt)
            s.add(e)
        s.commit()
    log.info("indexed %d items", len(todo))
    return len(todo)


def _vec(raw) -> list[float]:
    """Вектор из базы: строка JSON (или bytes от старой версии)."""
    if isinstance(raw, (bytes, memoryview)):
        raw = bytes(raw).decode("utf-8", "ignore")
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []


def _cos(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


async def search(query: str, limit: int = 10) -> dict:
    """{'mode': 'semantic'|'text', 'items': [{'kind','id','score', ...}]}"""
    q = (query or "").strip()
    if not q:
        return {"mode": "text", "items": []}
    vec = None
    if await llm.embed_available():
        vs = await llm.embed([q])
        vec = vs[0] if vs else None
    if vec is None:
        from . import brain_notes
        items = [{**n.model_dump(), "kind": "note", "score": 1.0} for n in brain_notes.list_notes(limit, q)]
        items += [{**l.model_dump(), "kind": "link", "score": 1.0} for l in brain_notes.list_links(limit, q)]
        return {"mode": "text", "items": items[:limit]}
    with session() as s:
        embs = list(s.exec(select(Embedding).where(Embedding.model == llm.EMBED_MODEL)))
        scored = sorted(((_cos(vec, _vec(e.vector)), e) for e in embs), key=lambda x: -x[0])[:limit]
        items = []
        for score, e in scored:
            if score < 0.35:
                continue
            if e.ref_table == "note":
                n = s.get(Note, e.ref_id)
                if n:
                    items.append({**n.model_dump(), "kind": "note", "score": round(score, 3)})
            else:
                l = s.get(Link, e.ref_id)
                if l:
                    items.append({**l.model_dump(), "kind": "link", "score": round(score, 3)})
    return {"mode": "semantic", "items": items}
