"""Смысловые связи между записями Мозга (заметки и ссылки).

Раньше «связано:» под заметкой и линии в графе были голой косинусной близостью эмбеддингов с порогом 0.55–0.62.
Для коротких бытовых фраз маленькая модель эмбеддингов даёт 0.6–0.7 почти для чего угодно — так «помощь маме
с сайтом» связывалась с «апельсиновым соком», и убрать это было негде.

Теперь в два шага:
  1. эмбеддинги (только ПК) отбирают кандидатов — топ-N с мягким порогом;
  2. нейронка (облако → ПК или ПК → облако, по настройке brain.relations.where) одним запросом говорит, какие из
     кандидатов действительно о том же (общая тема / человек / проект / дело), и почему — одной строкой.
Результат хранится в таблице Relation: auto (предложено) / yes (человек перешёл по связи) / no (крестик — больше не
предлагать). Без единой модели — только эмбеддинги с жёстким порогом и пометкой «похоже по словам».
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from sqlmodel import select

from ..brain import llm
from ..db import Embedding, Link, Note, Relation, session
from . import semantic

log = logging.getLogger("assistant.relations")

CANDIDATES = 8          # сколько похожих по эмбеддингам показываем нейронке
SOFT_MIN = 0.50         # порог отбора кандидатов
HARD_MIN = 0.72         # без модели: только очень похожее, с пометкой
MAX_SHOW = 4            # сколько связей показываем в карточке

PROMPT = """Ты помогаешь связывать записи личного дневника/заметок человека. Дана ЗАПИСЬ и список КАНДИДАТОВ, похожих на неё по словам.
Отметь связанными ТОЛЬКО те, что действительно о том же: один и тот же проект, дело, человек, событие, конкретная тема,
или одна запись — продолжение/уточнение другой. Общая категория («оба про еду», «оба про покупки», «оба про работу»,
«и там и там упоминается мама») — НЕ связь. Сомневаешься — не связывай.
Ответь строго JSON: {"related": [{"id": <id кандидата>, "why": "<почему, до 8 слов>"}]}. Если связей нет — {"related": []}."""


def enabled() -> bool:
    from .. import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "relations", None)
    return bool(getattr(node, "enabled", True)) if node is not None else True


def where() -> str:
    from .. import config as _c
    node = getattr(getattr(_c.cfg, "brain", None), "relations", None)
    w = str(getattr(node, "where", "cloud") or "cloud").lower()
    return w if w in ("cloud", "local", "auto") else "cloud"


def _key(kind: str, rid: int) -> str:
    return f"{kind}:{int(rid)}"


def _pair(x: str, y: str) -> tuple[str, str]:
    return (x, y) if x < y else (y, x)


def _split(key: str) -> tuple[str, int]:
    k, _, i = key.partition(":")
    return k, int(i)


def _text(kind: str, rid: int) -> str | None:
    with session() as s:
        row = s.get(Note if kind == "note" else Link, rid)
    if not row:
        return None
    if kind == "note":
        return " ".join(filter(None, [row.title, row.text]))[:600]
    return " ".join(filter(None, [row.title, row.comment, row.description]))[:600]


def _row_dict(kind: str, rid: int) -> dict | None:
    with session() as s:
        row = s.get(Note if kind == "note" else Link, rid)
    return {**row.model_dump(), "kind": kind} if row else None


# ---------------------------------------------------------------- шаг 1: кандидаты по эмбеддингам
def candidates(key: str, limit: int = CANDIDATES, min_score: float = SOFT_MIN) -> list[tuple[str, float]]:
    """Похожие по эмбеддингам записи (без обращения к модели — по уже посчитанным векторам)."""
    kind, rid = _split(key)
    with session() as s:
        embs = list(s.exec(select(Embedding).where(Embedding.model == llm.EMBED_MODEL)))
    me = next((e for e in embs if e.ref_table == kind and e.ref_id == rid), None)
    if not me:
        return []
    mv = semantic._vec(me.vector)
    if not mv:
        return []
    out = []
    for e in embs:
        if e is me:
            continue
        v = semantic._vec(e.vector)
        if not v:
            continue
        sc = semantic._cos(mv, v)
        if sc >= min_score:
            out.append((_key(e.ref_table, e.ref_id), sc))
    out.sort(key=lambda x: -x[1])
    return out[:limit]


# ---------------------------------------------------------------- шаг 2: решение нейронки
def _parse(raw: str) -> list[dict] | None:
    raw = llm.strip_think(raw or "").strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    rel = d.get("related") if isinstance(d, dict) else None
    return rel if isinstance(rel, list) else None


async def _ask(text: str, cands: list[tuple[str, str]]) -> tuple[list[dict] | None, str]:
    """cands — [(id-строка для модели, текст)]. Возвращает (список {id, why}, via)."""
    user = "ЗАПИСЬ:\n" + text + "\n\nКАНДИДАТЫ:\n" + "\n".join(f"[{i}] {t}" for i, t in cands)
    msgs = [{"role": "system", "content": PROMPT}, {"role": "user", "content": user}]
    w = where()
    cloud_ok, local_ok = llm.cloud_enabled(), await llm.ollama_available()

    async def cloud():
        raw = await llm.cloud_chat(PROMPT + "\nТолько JSON, без markdown.", user) or ""
        return _parse(raw), "cloud"

    async def local():
        out = await llm.ollama_chat(msgs, temperature=0.1, json_mode=True)
        return _parse(out.get("content") or ""), "ollama"

    order = []
    if w == "cloud":
        order = [cloud] if cloud_ok else []
        order += [local] if local_ok else []
    elif w == "auto":
        order = ([local] if local_ok else []) + ([cloud] if cloud_ok else [])
    else:
        order = [local] if local_ok else []
    for fn in order:
        try:
            res, via = await fn()
        except Exception as e:  # модель ответила ерундой/упала — пробуем следующую
            log.warning("relations via %s failed: %s", fn.__name__, e)
            continue
        if res is not None:
            return res, via
    return None, "none"


def _mark_seen(key: str) -> None:
    """Служебная строка a == b == key: «для этой версии текста связи считали». В why — хэш текста эмбеддинга,
    чтобы после правки заметки пересчитать заново. В чтении такие строки отфильтрованы (a != b)."""
    with session() as s:
        kind, rid = _split(key)
        e = s.exec(select(Embedding).where(Embedding.ref_table == kind, Embedding.ref_id == rid, Embedding.model == llm.EMBED_MODEL)).first()
        row = s.exec(select(Relation).where(Relation.a == key, Relation.b == key)).first() or Relation(a=key, b=key, status="seen")
        row.why = e.text_hash if e else ""
        row.status = "seen"
        s.add(row); s.commit()


async def compute(key: str, force: bool = False) -> list[Relation]:
    """Посчитать связи для одной записи и сохранить. Уже решённые пары (любой статус) не переспрашиваем, кроме force."""
    if not enabled():
        return []
    text = _text(*_split(key))
    if not text:
        return []
    cands = candidates(key)
    _mark_seen(key)
    if not cands:
        return []
    with session() as s:
        known = {}
        for r in s.exec(select(Relation).where((Relation.a == key) | (Relation.b == key), Relation.a != Relation.b)):
            other = r.b if r.a == key else r.a
            known[other] = r
    fresh = [(k, sc) for k, sc in cands if force or k not in known]
    if not fresh:
        return []
    texts = []
    for i, (k, _) in enumerate(fresh, 1):
        t = _text(*_split(k))
        if t:
            texts.append((str(i), t))
    if not texts:
        return []
    decided, via = await _ask(text, texts)
    saved: list[Relation] = []
    with session() as s:
        if decided is None:
            # ни одна модель не ответила: только очень похожее, с честной пометкой
            for k, sc in fresh:
                if sc >= HARD_MIN:
                    a, b = _pair(key, k)
                    r = Relation(a=a, b=b, score=round(sc, 3), status="auto", why="похоже по словам", via="embed")
                    s.add(r); saved.append(r)
        else:
            yes = {}
            for d in decided:
                if not isinstance(d, dict):
                    continue
                idx = str(d.get("id", "")).strip("[] ")
                if idx.isdigit() and 1 <= int(idx) <= len(fresh):
                    yes[int(idx)] = str(d.get("why") or "")[:80]
            for i, (k, sc) in enumerate(fresh, 1):
                a, b = _pair(key, k)
                if i in yes:
                    r = Relation(a=a, b=b, score=round(sc, 3), status="auto", why=yes[i], via=via)
                else:
                    # отказ нейронки тоже запоминаем, чтобы не спрашивать снова про ту же пару
                    r = Relation(a=a, b=b, score=round(sc, 3), status="no", why="", via=via)
                s.add(r); saved.append(r)
        s.commit()
        for r in saved:
            s.refresh(r)
    log.info("relations for %s: %d yes / %d no via %s", key, sum(r.status == "auto" for r in saved), sum(r.status == "no" for r in saved), via)
    return [r for r in saved if r.status != "no"]


# ---------------------------------------------------------------- чтение / правка
def related(key: str, limit: int = MAX_SHOW) -> list[dict]:
    """Связи записи для карточки: auto и yes, отклонённые не показываем."""
    if not enabled():
        return []
    with session() as s:
        rows = list(s.exec(select(Relation).where(((Relation.a == key) | (Relation.b == key)), Relation.a != Relation.b, Relation.status.in_(("auto", "yes")))))  # type: ignore[attr-defined]
    rows.sort(key=lambda r: (r.status != "yes", -r.score))
    out = []
    for r in rows:
        other = r.b if r.a == key else r.a
        d = _row_dict(*_split(other))
        if not d:
            continue
        out.append({**d, "relation_id": r.id, "why": r.why, "status": r.status, "score": r.score, "via": r.via})
        if len(out) >= limit:
            break
    return out


def set_status(relation_id: int, status: str) -> Relation | None:
    if status not in ("auto", "yes", "no"):
        return None
    with session() as s:
        r = s.get(Relation, relation_id)
        if not r or r.a == r.b:
            return None
        r.status = status
        s.add(r); s.commit(); s.refresh(r)
        return r


def pairs(limit: int = 300) -> list[tuple[str, str, float, str]]:
    """Рёбра для графа: только принятые/подтверждённые связи."""
    if not enabled():
        return []
    with session() as s:
        rows = list(s.exec(select(Relation).where(Relation.status.in_(("auto", "yes")), Relation.a != Relation.b).order_by(Relation.score.desc()).limit(limit)))  # type: ignore[attr-defined]
    return [(r.a, r.b, r.score, r.status) for r in rows]


def forget(kind: str, rid: int) -> None:
    """Запись удалили — связи с ней больше не нужны."""
    key = _key(kind, rid)
    with session() as s:
        for r in s.exec(select(Relation).where((Relation.a == key) | (Relation.b == key))):
            s.delete(r)
        s.commit()


# ---------------------------------------------------------------- фон
def pending(limit: int = 3) -> list[str]:
    """Записи с эмбеддингом, для которых связи ещё не считали (или текст с тех пор изменился), свежие первыми.
    Пересчёт старого после обновления идёт так же — по несколько записей за проход планировщика, чтобы не упереться
    в лимиты облака."""
    with session() as s:
        embs = list(s.exec(select(Embedding).where(Embedding.model == llm.EMBED_MODEL).order_by(Embedding.ref_id.desc())))
        seen = {r.a: r.why for r in s.exec(select(Relation).where(Relation.a == Relation.b))}
    out = []
    for e in embs:
        k = _key(e.ref_table, e.ref_id)
        if seen.get(k) != e.text_hash:
            out.append(k)
    return out[:limit]


async def job(limit: int = 3) -> int:
    """Планировщик: посчитать связи для нескольких новых записей. Сначала должен отработать semantic.index_pending."""
    if not enabled():
        return 0
    n = 0
    for key in pending(limit):
        try:
            await compute(key)
            n += 1
        except Exception as e:  # pragma: no cover
            log.warning("relations job %s: %s", key, e)
    return n
