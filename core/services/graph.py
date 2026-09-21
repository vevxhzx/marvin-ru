"""Граф связей «второго мозга» — как в Obsidian, только связи выводятся сами, ничего вручную.

Узлы: люди, заказы, заметки, ссылки, теги, долги, цели, деньги (категории с оборотом), проекты (из задач). Рёбра:
• заказ → человек (client_id), долг → человек (по имени)
• заметка/ссылка/задача/событие → человек (упоминание имени, people.mentions)
• заметка/ссылка/задача/событие → заказ / долг / цель (упоминание характерных слов названия: «Headway», «сбер»;
  общие слова — «кредит», «заказ», «проект» — не считаются, иначе всё слипнется)
• заметка/ссылка/заказ/человек → тег (#тег из полей tags и текста); заказы и клиенты — к #работа автоматически
• задача → проект (поле project); если проект — это заказ, то прямо к заказу
• деньги (категория) ↔ заказ / долг / цель (по оплатам: order_id / debt_id / goal_id), ↔ тег с тем же именем, ↔ человек (имя в комментарии)
• заметка ↔ заметка (смысловые связи из relations: эмбеддинги отобрали, нейронка решила, крестик убрал)
• заметка → заметка/ссылка по [[двойным скобкам]] в тексте (как в Obsidian): «см. [[идея про кофе]]»

Возвращаем компактный JSON для отрисовки на сайте (force-layout считаем в браузере, без библиотек).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlmodel import select

from ..db import Board, Client, Debt, Event, Goal, Link, Note, Order, Task, Transaction, session
from . import people as ppl
from .match import same, score, stem, tokens

WIKI_RX = re.compile(r"\[\[([^\]|#]{2,80})(?:\|[^\]]*)?\]\]")
TAG_RX = re.compile(r"(?<!\w)#([\wа-яё][\wа-яё\-]{1,30})", re.I)
WORK_TAG = "работа"
# слова, по которым нельзя связывать заказ/долг/цель с записью — они есть в половине названий
_GENERIC = {stem(w) for w in (
    "заказ", "проект", "работа", "задача", "клиент", "кредит", "кредитка", "кредитная", "карта", "долг", "платеж", "платёж",
    "ипотека", "рассрочка", "банк", "счет", "счёт", "цель", "накопление", "деньги", "оплата", "аванс", "остаток", "новый", "новая",
    "первый", "второй", "версия", "правки", "срочно", "сделать", "купить", "нужно", "надо", "для", "под",
)}


def keywords(title: str | None) -> list[str]:
    """Характерные основы слов названия — то, по чему запись можно узнать в чужом тексте. «Сбер кредит» → [сбер],
    «Headway v1» → [headway], «Кредит» → [] (нечего искать)."""
    out = []
    for t in tokens(title or ""):
        if t in _GENERIC or len(t) < 3 or t.isdigit() or re.fullmatch(r"v?\d+", t):
            continue
        out.append(t)
    return list(dict.fromkeys(out))


def mentions_title(text: str | None, kws: list[str]) -> bool:
    """Упоминается ли объект в тексте: короткое название (1–2 слова) — все слова; длиннее — не меньше двух третей."""
    if not text or not kws:
        return False
    tt = set(tokens(text))
    hit = sum(1 for k in kws if k in tt or any(same(k, w) for w in tt if len(w) >= 4))
    return hit >= (len(kws) if len(kws) <= 2 else max(2, -(-len(kws) * 2 // 3)))


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
            # деньги: оборот по категориям за период + привязки платежей к заказам/долгам/целям
        paid: dict[int, float] = {}
        money_total: dict[str, float] = {}
        money_kind: dict[str, str] = {}
        money_links: set[tuple[str, str]] = set()       # (категория, "order:3" | "debt:1" | "goal:2")
        money_person_text: dict[str, list[str]] = {}    # категория → комментарии платежей (для имён)
        for t in s.exec(select(Transaction).where(Transaction.date >= since)):
            if t.order_id and t.kind == "income":
                paid[t.order_id] = paid.get(t.order_id, 0.0) + t.amount
            cat = (t.category or "").strip()
            if not cat or t.kind == "transfer" and not t.goal_id:
                continue
            money_total[cat] = money_total.get(cat, 0.0) + t.amount
            money_kind.setdefault(cat, t.kind)
            if t.order_id:
                money_links.add((cat, f"order:{t.order_id}"))
            if t.debt_id:
                money_links.add((cat, f"debt:{t.debt_id}"))
            if t.goal_id:
                money_links.add((cat, f"goal:{t.goal_id}"))
            if t.note:
                money_person_text.setdefault(cat, []).append(t.note)

    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seen_pairs: set[tuple[str, str]] = set()

    def node(nid: str, label: str, kind: str, **extra):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": (label or "")[:60], "kind": kind, **extra}
        return nid

    def edge(a: str, b: str, rel: str, w: float = 1.0):
        # одна линия на пару: первая (самая «сильная») связь остаётся, остальные не дублируем
        key = (a, b) if a < b else (b, a)
        if a != b and key not in seen_pairs:
            seen_pairs.add(key)
            edges.append({"source": a, "target": b, "rel": rel, "w": w})

    def tag_node(t: str) -> str:
        return node(f"tag:{t}", "#" + t, "tag")

    # --- доски: узел «доска», связан с заказом/целью, иначе с #работа (сториборд) или сам по себе
    with session() as s:
        for b in s.exec(select(Board).where(Board.archived == False)).all():  # noqa: E712
            bid = node(f"board:{b.id}", b.title, "board", ref_id=b.id, sub=b.kind)
            if b.order_id:
                edge(bid, f"order:{b.order_id}", "board", 0.9)
            elif b.aim_id:
                edge(bid, f"aim:{b.aim_id}", "board", 0.9)
            elif b.kind == "storyboard":
                edge(bid, tag_node(WORK_TAG), "work", 0.5)
    # --- люди: тип «клиент» → #работа; свои теги
    for c in clients:
        nid = node(f"person:{c.id}", c.name, "person", sub=c.kind, ref_id=c.id)
        if c.kind == "client":
            edge(nid, tag_node(WORK_TAG), "work", 0.6)
        for t in _tags(c.tags):
            edge(nid, tag_node(t), "tag", 0.7)
    # --- заказы: клиент, #работа, теги из ТЗ; характерные слова — чтобы находить упоминания
    order_kws: list[tuple[str, list[str]]] = []
    for o in orders:
        nid = node(f"order:{o.id}", o.title, "order", status=o.status, ref_id=o.id, price=o.price, paid=round(paid.get(o.id, 0.0)))
        if o.client_id:
            edge(nid, f"person:{o.client_id}", "client", 2.0)
        edge(nid, tag_node(WORK_TAG), "work", 0.6)
        for t in _tags(None, o.notes):
            edge(nid, tag_node(t), "tag", 0.7)
        order_kws.append((nid, keywords(o.title)))
    # --- долги и цели
    debt_kws: list[tuple[str, list[str]]] = []
    for d in debts:
        nid = node(f"debt:{d.id}", d.title, "debt", ref_id=d.id, remaining=d.remaining)
        for c in clients:
            if ppl.mentions(d.title, c) or ppl.mentions(d.creditor, c):
                edge(nid, f"person:{c.id}", "debt", 1.5)
        debt_kws.append((nid, keywords(d.title) or keywords(d.creditor)))
    goal_kws: list[tuple[str, list[str]]] = []
    for g in goals:
        nid = node(f"goal:{g.id}", g.title, "goal", ref_id=g.id, saved=g.saved, target=g.target)
        goal_kws.append((nid, keywords(g.title)))
    named = order_kws + debt_kws + goal_kws   # всё, что можно «упомянуть» по названию

    def mention_edges(nid: str, *texts: str | None) -> None:
        blob = " ".join(t for t in texts if t)
        if not blob:
            return
        for c in clients:
            if ppl.mentions(blob, c):
                edge(nid, f"person:{c.id}", "mention", 1.2)
        for other, kws in named:
            if other != nid and mentions_title(blob, kws):
                edge(nid, other, "mention", 1.2)

    # --- заметки и ссылки: люди, заказы/долги/цели по словам, теги, [[wiki-ссылки]]
    titled: list[tuple[str, str]] = []   # (node_id, title) — для разрешения [[…]]
    for n in notes:
        nid = node(f"note:{n.id}", n.title or n.text[:50], "note", ref_id=n.id, image=bool(n.image), at=n.created_at.isoformat())
        titled.append((nid, n.title or n.text[:60]))
        for t in _tags(n.tags, n.text):
            edge(nid, tag_node(t), "tag", 0.7)
        mention_edges(nid, n.title, n.text)
    for l in links:
        nid = node(f"link:{l.id}", l.title or l.domain or l.url, "link", ref_id=l.id, url=l.url, at=l.created_at.isoformat())
        titled.append((nid, l.title or l.domain or ""))
        for t in _tags(l.tags, l.comment):
            edge(nid, tag_node(t), "tag", 0.7)
        mention_edges(nid, l.title, l.comment)
    # [[двойные скобки]] в тексте заметок → лучшая по совпадению названия заметка/ссылка
    for n in notes:
        for m in WIKI_RX.findall(n.text or ""):
            best = max(((score(title, m), tid) for tid, title in titled if tid != f"note:{n.id}"), default=(0, None))
            if best[0] >= 0.66 and best[1]:
                edge(f"note:{n.id}", best[1], "wiki", 1.5)

    # --- задачи: проект (или заказ, если проект — это он), упоминания людей/заказов/долгов
    order_titles = [(f"order:{o.id}", o.title) for o in orders]
    for t in tasks:
        tid = node(f"task:{t.id}", t.title, "task", ref_id=t.id)
        before = len(edges)
        if t.project:
            best = max(((score(title, t.project), nid) for nid, title in order_titles), default=(0, None))
            if best[0] >= 0.66 and best[1]:
                edge(tid, best[1], "project", 1.5)
            else:
                edge(tid, node(f"project:{t.project.strip().lower()}", t.project.strip(), "project"), "project", 1.0)
        mention_edges(tid, t.title, t.project)
        if len(edges) == before:
            nodes.pop(tid, None)   # задача без связей граф не засоряет
    for e in events:
        eid = f"event:{e.id}"
        node(eid, e.title, "event", ref_id=e.id, at=e.start.isoformat())
        before = len(edges)
        mention_edges(eid, e.title, e.notes)
        if len(edges) == before:
            nodes.pop(eid, None)

    # --- деньги: категории как узлы; связи по реальным платежам, по одноимённому тегу и по именам в комментариях
    for cat, total in money_total.items():
        mid = node(f"money:{cat.lower()}", cat, "money", total=round(total), sub=money_kind.get(cat, "expense"))
        for c2, dst in money_links:
            if c2 == cat and dst in nodes:
                edge(mid, dst, "pay", 1.5)
        for tid_ in [k for k in nodes if k.startswith("tag:")]:
            if same(tid_[4:], cat.lower()):
                edge(mid, tid_, "same", 1.0)
        blob = " ".join(money_person_text.get(cat, []))
        if blob:
            for c in clients:
                if ppl.mentions(blob, c):
                    edge(mid, f"person:{c.id}", "pay", 1.0)

    # связанные по смыслу записи — только принятые нейронкой/человеком (relations), а не голая близость эмбеддингов
    from . import relations
    for a, b, sc, st in relations.pairs(limit=300):
        if a in nodes and b in nodes:
            edge(a, b, "similar", round(max(sc, 0.5) + (0.3 if st == "yes" else 0), 2))

    # степень узла → размер; одинокие теги не показываем
    deg: dict[str, int] = {}
    for e in edges:
        deg[e["source"]] = deg.get(e["source"], 0) + 1
        deg[e["target"]] = deg.get(e["target"], 0) + 1
    for nid, nd in nodes.items():
        nd["deg"] = deg.get(nid, 0)
    # одинокие теги/категории/проекты не показываем; #работа держится, пока к нему что-то прицеплено
    # одинокие теги и проекты (меньше двух связей) не показываем; категория денег остаётся, если ведёт хоть куда-то;
    # #работа держится, пока к нему что-то прицеплено
    def _lonely(nid: str, nd: dict) -> bool:
        if nd["kind"] == "money":
            return nd["deg"] < 1
        if nd["kind"] in ("tag", "project"):
            return nd["deg"] < (1 if nid == f"tag:{WORK_TAG}" else 2)
        return False
    keep = {nid for nid, nd in nodes.items() if not _lonely(nid, nd)}
    edges = [e for e in edges if e["source"] in keep and e["target"] in keep]
    # задача/встреча, у которой единственной связью был выброшенный проект/тег — тоже уходит
    left = {e["source"] for e in edges} | {e["target"] for e in edges}
    keep = {nid for nid in keep if nid in left or nodes[nid]["kind"] not in ("task", "event")}
    for nid in keep:
        nodes[nid]["deg"] = sum(1 for e in edges if nid in (e["source"], e["target"]))

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
