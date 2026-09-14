"""Граф связей «второго мозга» — как в Obsidian, только связи выводятся сами, ничего вручную.

Узлы: люди, заказы, заметки, ссылки, теги, долги, цели. Рёбра:
• заказ → человек (client_id), оплата → заказ (order_id), долг → человек (по имени)
• заметка/ссылка/задача/событие → человек (упоминание имени, people.mentions)
• заметка/ссылка → тег (#тег из полей tags)
• заметка ↔ заметка (похожие по смыслу, если есть эмбеддинги — semantic.related_pairs)
• заметка → заметка/ссылка по [[двойным скобкам]] в тексте (как в Obsidian): «см. [[идея про кофе]]»

Возвращаем компактный JSON для отрисовки на сайте (force-layout считаем в браузере, без библиотек).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlmodel import select

from ..db import Client, Debt, Event, Goal, Link, Note, Order, Task, Transaction, session
from . import people as ppl
from .match import score

WIKI_RX = re.compile(r"\[\[([^\]|#]{2,80})(?:\|[^\]]*)?\]\]")
TAG_RX = re.compile(r"(?<!\w)#([\wа-яё][\wа-яё\-]{1,30})", re.I)


def _tags(raw: str | None, text: str | None = None) -> list[str]:
    out = [t.strip().lower().lstrip("#") for t in (raw or "").split(",") if t.strip()]
    if text:
        out += [m.lower() for m in TAG_RX.findall(text)]
    return list(dict.fromkeys(t for t in out if t))


def build(days: int = 365, max_notes: int = 400, focus: str | None = None) -> dict:
    """Узлы и рёбра. focus — id узла («person:3», «note:12») — вернуть только его окрестность (2 шага)."""
    since = datetime.now() - timedelta(days=days)
    with session() as s:
        clients = list(s.exec(select(Client)))
        orders = list(s.exec(select(Order).where(Order.created_at >= since)))
        notes = list(s.exec(select(Note).where(Note.created_at >= since).order_by(Note.created_at.desc()).limit(max_notes)))
        links = list(s.exec(select(Link).where(Link.created_at >= since).order_by(Link.created_at.desc()).limit(max_notes)))
        debts = list(s.exec(select(Debt).where(Debt.closed == False)))  # noqa: E712
        goals = list(s.exec(select(Goal).where(Goal.closed == False)))  # noqa: E712
        tasks = list(s.exec(select(Task).where(Task.done == False)))  # noqa: E712
        events = list(s.exec(select(Event).where(Event.start >= datetime.now() - timedelta(days=60)).limit(600)))
        paid: dict[int, float] = {}
        for t in s.exec(select(Transaction).where(Transaction.order_id != None, Transaction.kind == "income")):  # noqa: E711
            paid[t.order_id] = paid.get(t.order_id, 0.0) + t.amount

    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(nid: str, label: str, kind: str, **extra):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": (label or "")[:60], "kind": kind, **extra}
        return nid

    def edge(a: str, b: str, rel: str, w: float = 1.0):
        if a != b:
            edges.append({"source": a, "target": b, "rel": rel, "w": w})

    for c in clients:
        node(f"person:{c.id}", c.name, "person", sub=c.kind, ref_id=c.id)
    for o in orders:
        nid = node(f"order:{o.id}", o.title, "order", status=o.status, ref_id=o.id, price=o.price, paid=round(paid.get(o.id, 0.0)))
        if o.client_id:
            edge(nid, f"person:{o.client_id}", "client", 2.0)
    for d in debts:
        nid = node(f"debt:{d.id}", d.title, "debt", ref_id=d.id, remaining=d.remaining)
        for c in clients:
            if ppl.mentions(d.title, c) or ppl.mentions(d.creditor, c):
                edge(nid, f"person:{c.id}", "debt", 1.5)
    for g in goals:
        node(f"goal:{g.id}", g.title, "goal", ref_id=g.id, saved=g.saved, target=g.target)

    # заметки и ссылки: люди, теги, [[wiki-ссылки]]
    titled: list[tuple[str, str]] = []   # (node_id, title) — для разрешения [[…]]
    for n in notes:
        nid = node(f"note:{n.id}", n.title or n.text[:50], "note", ref_id=n.id, image=bool(n.image), at=n.created_at.isoformat())
        titled.append((nid, n.title or n.text[:60]))
        for t in _tags(n.tags, n.text):
            edge(nid, node(f"tag:{t}", "#" + t, "tag"), "tag", 0.7)
        for c in clients:
            if ppl.mentions(n.text, c) or ppl.mentions(n.title, c):
                edge(nid, f"person:{c.id}", "mention", 1.2)
    for l in links:
        nid = node(f"link:{l.id}", l.title or l.domain or l.url, "link", ref_id=l.id, url=l.url, at=l.created_at.isoformat())
        titled.append((nid, l.title or l.domain or ""))
        for t in _tags(l.tags, l.comment):
            edge(nid, node(f"tag:{t}", "#" + t, "tag"), "tag", 0.7)
        for c in clients:
            if ppl.mentions(l.title, c) or ppl.mentions(l.comment, c):
                edge(nid, f"person:{c.id}", "mention", 1.2)
    # [[двойные скобки]] в тексте заметок → лучшая по совпадению названия заметка/ссылка
    for n in notes:
        for m in WIKI_RX.findall(n.text or ""):
            best = max(((score(title, m), tid) for tid, title in titled if tid != f"note:{n.id}"), default=(0, None))
            if best[0] >= 0.66 and best[1]:
                edge(f"note:{n.id}", best[1], "wiki", 1.5)

    # задачи и события — только те, что связаны с людьми (иначе граф зарастает)
    for t in tasks:
        for c in clients:
            if ppl.mentions(t.title, c):
                edge(node(f"task:{t.id}", t.title, "task", ref_id=t.id), f"person:{c.id}", "mention", 1.0)
    for e in events:
        for c in clients:
            if ppl.mentions(e.title, c) or ppl.mentions(e.notes, c):
                edge(node(f"event:{e.id}", e.title, "event", ref_id=e.id, at=e.start.isoformat()), f"person:{c.id}", "mention", 1.0)

    # похожие по смыслу заметки — если эмбеддинги уже посчитаны (без модели просто нет таких рёбер)
    try:
        from . import semantic
        for a, b, sc in semantic.related_pairs(min_score=0.62, limit=200):
            if a in nodes and b in nodes:
                edge(a, b, "similar", round(sc, 2))
    except Exception:
        pass

    # степень узла → размер; одинокие теги не показываем
    deg: dict[str, int] = {}
    for e in edges:
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    for nid, nd in nodes.items():
        nd["deg"] = deg.get(nid, 0)
    keep = {nid for nid, nd in nodes.items() if not (nd["kind"] == "tag" and nd["deg"] < 2)}
    edges = [e for e in edges if e["source"] in keep and e["target"] in keep]

    if focus and focus in nodes:
        near = {focus}
        for _ in range(2):
            for e in edges:
                if e["source"] in near or e["target"] in near:
                    near.add(e["source"]); near.add(e["target"])
        keep &= near
        edges = [e for e in edges if e["source"] in keep and e["target"] in keep]

    out_nodes = [nodes[n] for n in keep]
    return {"nodes": out_nodes, "edges": edges,
            "stats": {"people": sum(1 for n in out_nodes if n["kind"] == "person"), "notes": sum(1 for n in out_nodes if n["kind"] == "note"),
                      "links": sum(1 for n in out_nodes if n["kind"] == "link"), "tags": sum(1 for n in out_nodes if n["kind"] == "tag"),
                      "edges": len(edges), "lonely": sum(1 for n in out_nodes if n["deg"] == 0 and n["kind"] in ("note", "link"))}}


def backlinks(kind: str, ref_id: int) -> list[dict]:
    """Что ссылается на этот объект (для карточки заметки/человека): узлы-соседи с типом связи."""
    g = build(focus=f"{kind}:{ref_id}")
    me = f"{kind}:{ref_id}"
    by_id = {n["id"]: n for n in g["nodes"]}
    out = []
    for e in g["edges"]:
        other = e["target"] if e["source"] == me else e["source"] if e["target"] == me else None
        if other and other in by_id:
            out.append({**by_id[other], "rel": e["rel"]})
    seen, uniq = set(), []
    for o in out:
        if o["id"] not in seen:
            seen.add(o["id"]); uniq.append(o)
    return uniq
