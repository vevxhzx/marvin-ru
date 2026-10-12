"""Память: извлечение фактов из реплик (маршрут cloud/auto/local)."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

from sqlmodel import select

from ...brain import llm
from ...db import session

from .recall import recall
from .store import (
    COMMAND_RX, CORE_MAX, EXTRACT_PROMPT, SECRET_RX, _dismissed, _norm,
    add_fact, enabled, list_facts, log, update_fact, where,
)



# ---------------------------------------------------------------- модель
def _parse(raw: str) -> dict | None:
    raw = llm.strip_think(raw or "").strip()
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return d if isinstance(d, dict) else None


async def _ask(system: str, user: str) -> tuple[dict | None, str]:
    """Маршрут cloud / auto / local (как у сортировщика и связей). Текст в облако проходит анонимайзер в cloud_chat."""
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    w = where()
    cloud_ok, local_ok = llm.cloud_enabled(), await llm.local_available()

    async def cloud():
        return _parse(await llm.cloud_chat(system + "\nТолько JSON, без markdown.", user) or ""), "cloud"

    async def local():
        out = await llm.ollama_chat(msgs, temperature=0.1, json_mode=True)
        return _parse(out.get("content") or ""), "ollama"

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
            log.warning("memory via %s failed: %s", fn.__name__, e)
            continue
        if res is not None:
            return res, via
    return None, "none"


async def _cloud_sees_stored() -> bool:
    """Уйдут ли хранимые факты в облако на этом проходе: where() == cloud,
    или auto без доступной локалки (фолбэк на облако). Замок (is_private):
    всё, что может увидеть облако, фильтруется вызывающим."""
    w = where()
    return w == "cloud" or (w == "auto" and not await llm.local_available())


# ---------------------------------------------------------------- извлечение из реплики
def worth_extracting(text: str, actions: list[str] | None = None) -> bool:
    """Стоит ли вообще звать нейронку: не команда-шаблон, не вопрос, не короткая реплика, не секрет."""
    t = (text or "").strip()
    if len(t.split()) < 4 or len(t) > 1500:
        return False
    if SECRET_RX.search(t):
        return False
    if t.endswith("?") or COMMAND_RX.match(t):
        return False
    # правило уже что-то записало (трата/событие/задача) — там факта о человеке нет; заметка и разговор — есть
    if actions and any(a in actions for a in ("add_expense", "add_income", "add_event", "add_task", "pay_debt", "transfer", "complete_task", "undo", "clarify")):
        return False
    return True


async def extract(text: str, msg_id: int | None = None) -> dict:
    """Нейронка решает, что запомнить из реплики. Возвращает {'added': [...], 'updated': [...], 'via': ...}."""
    if not enabled() or not worth_extracting(text):
        return {"added": [], "updated": [], "via": "skip"}
    known = await recall(text, limit=10)
    core = [f for f in list_facts() if f.core and f.layer != "archive"][:CORE_MAX]
    seen, ctx = set(), []
    for f in core + known:
        if f.id not in seen:
            seen.add(f.id); ctx.append(f)
    if await _cloud_sees_stored():
        ctx = [f for f in ctx if not f.is_private]   # замок: приватное в облако не уходит
    user = "РЕПЛИКА:\n" + llm._hide_secrets(text) + "\n\nИЗВЕСТНО:\n" + ("\n".join(f"[{f.id}] {f.text}" for f in ctx) or "(пока ничего)")
    d, via = await _ask(EXTRACT_PROMPT, user)
    if d is None:
        return {"added": [], "updated": [], "via": via}
    added, updated = [], []
    dismissed = _dismissed()   # «нет» в тосте: такую фразу хозяин просил не запоминать — молча не сохраняем
    ids_ok = {f.id for f in ctx}
    for u in (d.get("update") or [])[:5]:
        if not isinstance(u, dict):
            continue
        try:
            fid = int(str(u.get("id", "")).strip("[] "))
        except ValueError:
            continue
        if fid in ids_ok and _norm(str(u.get("text") or "")):
            f = await update_fact(fid, text=str(u["text"]), reason="уточнено из разговора")
            if f:
                updated.append(f)
    for a in (d.get("add") or [])[:5]:
        if not isinstance(a, dict) or not _norm(str(a.get("text") or "")):
            continue
        if _norm(str(a["text"])).lower() in dismissed:
            continue
        f = await add_fact(str(a["text"]), layer=str(a.get("layer") or "short"), category=str(a.get("category") or "быт"),
                           source_msg=msg_id, confidence=0.6)
        if f and f.created_at >= datetime.now() - timedelta(seconds=5):
            added.append(f)
    remind = None
    rm = d.get("remind")
    if isinstance(rm, dict) and _norm(str(rm.get("title") or "")):
        remind = _suggest_task(str(rm["title"]), rm.get("when"))
    if added or updated or remind:
        log.info("память: +%d / ~%d фактов%s via %s", len(added), len(updated), " + напоминание" if remind else "", via)
    return {"added": added, "updated": updated, "remind": remind, "via": via}


def _suggest_task(title: str, when) -> dict | None:
    """Напоминание, которое ассистент предложил сам: задача с источником proactive (ActionLog → «отмени» работает)."""
    from .. import tasks
    title = _norm(title)[:120]
    title = title[0].upper() + title[1:]
    due = None
    if when:
        try:
            due = datetime.fromisoformat(str(when).replace(" ", "T"))
        except ValueError:
            due = None
        if due and due < datetime.now():
            due = None
    with session() as s:
        from ...db import Task
        for t in s.exec(select(Task).where(Task.done == False)):  # noqa: E712
            if t.title.strip().lower() == title.lower():
                return None   # такая уже есть — не дублируем и не сообщаем
    t = tasks.add_task(title, due, source="proactive")
    return {"id": t.id, "title": t.title, "due": t.due}
