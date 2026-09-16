"""Судья и уроки: спорную фразу перед записью решает нейронка, а исправления хозяина запоминаются.

Зачем: шаблоны в agent.rules() хороши на явных командах («потратил 700 на такси»), но на фразах без глагола-маркера
(«сайт 15000», «отдал Ване 2000», «мама в субботу») гадают — и получается «записал одно, а имелось в виду другое».

Три части:
- lessons: «это заказ» после неверной записи → Lesson(text, kind). Похожая фраза (эмбеддинги ≥ LESSON_MIN, локально;
  без модели — по словам) в следующий раз идёт нужным типом, минуя и шаблон, и судью.
- judge(): один короткий JSON-запрос {kind, confidence}. Маршрут brain.judge.where (local по умолчанию — малая модель,
  если задана brain.ollama.small_model). Уверен ≥ SURE → пишем; иначе — уточняющий вопрос.
- mute: «не надо про это» под инициативным сообщением → тема больше не всплывает (используется в proactive).
"""
from __future__ import annotations

import json
import logging
import re

from sqlmodel import select

from ..brain import llm
from ..config import cfg
from ..db import Lesson, session

log = logging.getLogger("assistant.judge")

KINDS = ("expense", "income", "debt", "order", "task", "event", "note")
KIND_RU = {"expense": "трата", "income": "доход", "debt": "долг", "order": "заказ", "task": "задача", "event": "событие в календарь", "note": "заметка"}
SURE = 0.8
LESSON_MIN = 0.82

PROMPT = """Ты — сортировщик фраз личного ассистента. Дана короткая фраза хозяина (русский, разговорный). Реши, что он хотел записать:
expense — потратил деньги; income — получил деньги (зарплата, оплата от клиента); debt — кто-то кому-то должен;
order — новый заказ/проект в работу (фриланс: название + цена/клиент); task — дело, которое надо сделать;
event — встреча/событие со временем в календарь; note — просто мысль или факт на память.
Ответ строго JSON: {"kind": "<один из: expense, income, debt, order, task, event, note>", "confidence": <0..1>}.
Если фраза двусмысленная — confidence ниже 0.6."""


def enabled() -> bool:
    j = getattr(cfg.brain, "judge", None)
    return bool(getattr(j, "enabled", True)) if j is not None else True


def where() -> str:
    j = getattr(cfg.brain, "judge", None)
    w = str(getattr(j, "where", "local") or "local").lower() if j is not None else "local"
    return w if w in ("cloud", "auto", "local") else "local"


# ---------------------------------------------------------------- уроки
def _norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "").strip(" .!,;:—-"))


def _words(t: str) -> set[str]:
    return {w[:-1] if len(w) > 4 else w for w in re.findall(r"[а-яёa-z]{3,}", t.lower())}


def _vec(raw: str) -> list[float]:
    try:
        return json.loads(raw) if raw else []
    except ValueError:
        return []


def _cos(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def add_lesson(text: str, kind: str, wrong: str = "") -> Lesson | None:
    text = _norm(text)
    if not text or kind not in KINDS + ("mute",):
        return None
    with session() as s:
        for l in s.exec(select(Lesson).where(Lesson.kind == kind)):
            if l.text.lower() == text.lower():
                return l
        l = Lesson(text=text, kind=kind, wrong=wrong)
        s.add(l); s.commit(); s.refresh(l)
        return l


def list_lessons(kind: str | None = None) -> list[Lesson]:
    with session() as s:
        q = select(Lesson).order_by(Lesson.id.desc())
        if kind:
            q = q.where(Lesson.kind == kind)
        return list(s.exec(q))


def forget_lesson(lid: int) -> bool:
    with session() as s:
        l = s.get(Lesson, lid)
        if not l:
            return False
        s.delete(l); s.commit()
        return True


async def index_pending(limit: int = 50) -> int:
    """Досчитать эмбеддинги урокам (локально). Зовётся из планировщика вместе с индексом памяти."""
    if not await llm.embed_available():
        return 0
    with session() as s:
        rows = list(s.exec(select(Lesson).where(Lesson.vector == "").limit(limit)))
    if not rows:
        return 0
    vecs = await llm.embed([r.text for r in rows])
    if not vecs:
        return 0
    with session() as s:
        for r, v in zip(rows, vecs):
            row = s.get(Lesson, r.id)
            if row:
                row.vector = json.dumps([round(x, 6) for x in v]); s.add(row)
        s.commit()
    return len(rows)


def _lesson_by_words(text: str, kinds: tuple[str, ...]) -> Lesson | None:
    w = _words(text)
    if not w:
        return None
    best, best_sc = None, 0.0
    for l in list_lessons():
        if l.kind not in kinds:
            continue
        lw = _words(l.text)
        if not lw:
            continue
        sc = len(w & lw) / len(w | lw)
        if sc > best_sc:
            best, best_sc = l, sc
    return best if best_sc >= 0.6 else None


async def lesson_for(text: str, kinds: tuple[str, ...] = KINDS) -> Lesson | None:
    """Есть ли урок для похожей фразы. Эмбеддинги — если доступны и посчитаны, иначе по словам."""
    text = _norm(text)
    if not text:
        return None
    lessons = [l for l in list_lessons() if l.kind in kinds]
    if not lessons:
        return None
    hit = None
    if any(l.vector for l in lessons):
        try:
            vecs = await llm.embed([text]) if await llm.embed_available() else None
        except Exception as e:  # pragma: no cover
            log.warning("lesson embed: %s", e); vecs = None
        if vecs:
            scored = sorted(((_cos(vecs[0], _vec(l.vector)), l) for l in lessons if l.vector), key=lambda x: -x[0])
            if scored and scored[0][0] >= LESSON_MIN:
                hit = scored[0][1]
    if hit is None:
        hit = _lesson_by_words(text, kinds)
    if hit:
        with session() as s:
            row = s.get(Lesson, hit.id)
            if row:
                row.uses += 1; s.add(row); s.commit()
    return hit


# ---------------------------------------------------------------- судья
def _parse(raw: str) -> tuple[str, float] | None:
    raw = llm.strip_think(raw or "").strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    kind = str(d.get("kind") or "").strip().lower()
    if kind not in KINDS:
        return None
    try:
        conf = float(d.get("confidence", 0))
    except (TypeError, ValueError):
        conf = 0.0
    return kind, max(0.0, min(1.0, conf))


async def judge(text: str, allowed: tuple[str, ...] = KINDS) -> tuple[str, float, str] | None:
    """(kind, confidence, via) или None, если решать некому. allowed сужает варианты (например, только expense/order/income)."""
    if not enabled():
        return None
    text = _norm(text)
    user = f"Фраза: «{llm._hide_secrets(text)}»" + (f"\nВыбирай только из: {', '.join(allowed)}." if allowed != KINDS else "")
    w = where()
    cloud_ok, local_ok = llm.cloud_enabled(), await llm.ollama_available()

    async def local():
        return _parse(await llm.small_chat(PROMPT, user, json_mode=True, num_predict=60)), ("small" if llm.small_model_active() else "ollama")

    async def cloud():
        return _parse(await llm.cloud_chat(PROMPT + "\nТолько JSON.", user) or ""), "cloud"

    if w == "cloud":
        order = ([cloud] if cloud_ok else []) + ([local] if local_ok else [])
    elif w == "auto":
        order = ([local] if local_ok else []) + ([cloud] if cloud_ok else [])
    else:
        order = [local] if local_ok else []
    for fn in order:
        try:
            res, via = await fn()
        except Exception as e:
            log.warning("judge via %s failed: %s", fn.__name__, e)
            continue
        if res is not None:
            kind, conf = res
            if kind not in allowed:
                conf = min(conf, 0.5)
            return kind, conf, via
    return None


async def decide(text: str, allowed: tuple[str, ...] = KINDS) -> tuple[str | None, str]:
    """Что делать с фразой: сначала урок, потом судья. Возвращает (kind | None, источник: lesson/small/ollama/cloud/none).
    None — уверенности нет, пусть спросит."""
    l = await lesson_for(text, allowed)
    if l:
        return l.kind, "lesson"
    r = await judge(text, allowed)
    if r is None:
        return None, "none"
    kind, conf, via = r
    return (kind if conf >= SURE else None), via
