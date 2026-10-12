"""Память: портрет хозяина и профиль стиля."""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from sqlmodel import select

from ...brain import llm
from ...db import get_setting, session, set_setting

from .extract import _cloud_sees_stored
from .store import (
    PORTRAIT_AT_KEY, PORTRAIT_KEY, PORTRAIT_PROMPT, STYLE_AT_KEY, STYLE_KEY,
    STYLE_LINE_MAX, STYLE_PROMPT, enabled, list_facts, log, where,
)



# ---------------------------------------------------------------- портрет и уборка
async def rebuild_portrait(force: bool = False) -> str | None:
    """Раз в неделю (или по кнопке): long-факты → 5–8 строк «кто мой хозяин»."""
    if not enabled():
        return None
    if not force:
        at = get_setting(PORTRAIT_AT_KEY, "")
        try:
            if at and datetime.fromisoformat(at) > datetime.now() - timedelta(days=7):
                return get_setting(PORTRAIT_KEY, "")
        except ValueError:
            pass
    facts = [f for f in list_facts("long")][:80]
    if len(facts) < 3:
        return get_setting(PORTRAIT_KEY, "")
    if await _cloud_sees_stored():
        facts = [f for f in facts if not f.is_private]   # замок: приватное в облако не уходит
        if len(facts) < 3:
            return get_setting(PORTRAIT_KEY, "")
    user = "\n".join(f"— {f.text}" for f in facts)
    w = where()
    cloud_ok, local_ok = llm.cloud_enabled(), await llm.local_available()
    text = None
    order = []
    if w == "cloud":
        order = (["cloud"] if cloud_ok else []) + (["local"] if local_ok else [])
    elif w == "auto":
        order = (["local"] if local_ok else []) + (["cloud"] if cloud_ok else [])
    else:
        order = ["local"] if local_ok else []
    for how in order:
        try:
            if how == "cloud":
                text = await llm.cloud_chat(PORTRAIT_PROMPT, user)
            else:
                out = await llm.ollama_chat([{"role": "system", "content": PORTRAIT_PROMPT}, {"role": "user", "content": user}], temperature=0.2)
                text = llm.strip_think(out.get("content") or "")
        except Exception as e:
            log.warning("portrait via %s: %s", how, e)
            text = None
        if text and text.strip():
            break
    if not text or not text.strip():
        return get_setting(PORTRAIT_KEY, "")
    text = "\n".join(l.strip() for l in text.strip().splitlines() if l.strip())[:1200]
    set_setting(PORTRAIT_KEY, text)
    set_setting(PORTRAIT_AT_KEY, datetime.now().isoformat())
    return text


async def rebuild_style(force: bool = False) -> str | None:
    """Раз в неделю (или по кнопке): последние ~200 реплик хозяина → 3–5 строк «как он пишет». Идёт в системный промпт рядом
    с портретом. В облако — через анонимайзер cloud_chat; секреты скрыты заранее."""
    if not enabled():
        return None
    if not force:
        at = get_setting(STYLE_AT_KEY, "")
        try:
            if at and datetime.fromisoformat(at) > datetime.now() - timedelta(days=7):
                return get_setting(STYLE_KEY, "")
        except ValueError:
            pass
    from ...db import ChatMessage
    with session() as s:
        rows = s.exec(select(ChatMessage).where(ChatMessage.role == "user").order_by(ChatMessage.id.desc()).limit(200)).all()
    lines = [llm._hide_secrets(r.text.strip())[:200] for r in reversed(rows) if r.text and len(r.text.strip()) >= 3]
    if len(lines) < 20:
        return get_setting(STYLE_KEY, "")
    user = "\n".join(lines)
    w = where()
    cloud_ok, local_ok = llm.cloud_enabled(), await llm.local_available()
    order = ((["cloud"] if cloud_ok else []) + (["local"] if local_ok else [])) if w == "cloud" else \
            ((["local"] if local_ok else []) + (["cloud"] if cloud_ok else [])) if w == "auto" else (["local"] if local_ok else [])
    text = None
    for how in order:
        try:
            if how == "cloud":
                text = await llm.cloud_chat(STYLE_PROMPT, user)
            else:
                out = await llm.ollama_chat([{"role": "system", "content": STYLE_PROMPT}, {"role": "user", "content": user}], temperature=0.2)
                text = llm.strip_think(out.get("content") or "")
        except Exception as e:
            log.warning("style via %s: %s", how, e)
            text = None
        if text and text.strip():
            break
    if not text or not text.strip():
        return get_setting(STYLE_KEY, "")
    text = "\n".join(l.strip() for l in text.strip().splitlines() if l.strip())[:800]
    set_setting(STYLE_KEY, text)
    set_setting(STYLE_AT_KEY, datetime.now().isoformat())
    return text


def style_line() -> str:
    """Профиль стиля хозяина ОДНОЙ строкой — идёт в system prompt (см. agent._system).
    Одна строка, не зависящая от реплики: не портит кэш промпта и не дублирует многострочный блок в каждом сообщении."""
    raw = get_setting(STYLE_KEY, "") or ""
    if not raw.strip():
        return ""
    out, used = [], 0
    for l in raw.splitlines():
        line = re.sub(r"^[\s—•\-–]+", "", l).strip()
        if not line:
            continue
        if used + len(line) > STYLE_LINE_MAX:
            break
        out.append(line)
        used += len(line) + 3
    return " · ".join(out)
