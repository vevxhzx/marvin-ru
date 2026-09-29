"""Журнал решений — «решил: беру заказ у Лены, но с предоплатой 50%, потому что в прошлый раз ждал месяц».

Это не новая таблица: решение = Note с тегом «решение» (и, если сказано, «почему» в тексте после «потому что/так как»).
Зачем отдельно: через месяц спросить «почему я так решил про Лену» — и получить свои же слова, а не догадки.
"""
from __future__ import annotations

import re
from datetime import datetime

from sqlmodel import select

from ..db import Note, session
from .match import score, tokens

TAG = "решение"

DECIDE_RX = re.compile(r"^\s*(?:я\s+)?(?:решил\w*|принял\w*\s+решение|решение)\s*[:—-]?\s*(.+)$", re.I | re.S)
WHY_RX = re.compile(r"^\s*(?:почему|зачем)\s+(?:я\s+)?(?:так\s+)?(?:решил\w*|выбрал\w*|сделал\w*)\s*(?:про|по|с|насчёт|насчет|о|об)?\s*(.*?)\s*\??\s*$", re.I)
LIST_RX = re.compile(r"^\s*(?:мои\s+решения|журнал\s+решений|что\s+я\s+решил\w*(?:\s+за\s+(?:неделю|месяц))?)\s*\??\s*$", re.I)
_REASON_SPLIT = re.compile(r"\s+(?:потому\s+что|так\s+как|поскольку|причина\s*[:—-]|—\s*причина)\s+", re.I)


def add(text: str, source: str = "tg") -> Note:
    from .brain_notes import add_note
    text = text.strip().rstrip(".")
    return add_note(text, tags=[TAG], source=source, polish=False)


def split(text: str) -> tuple[str, str]:
    """«беру заказ, потому что нужны деньги» → («беру заказ», «нужны деньги»)."""
    parts = _REASON_SPLIT.split(text, maxsplit=1)
    return (parts[0].strip(" ,.;—-"), parts[1].strip(" ,.;—-")) if len(parts) == 2 else (text.strip(" ,.;—-"), "")


def all_(limit: int = 50) -> list[Note]:
    with session() as s:
        rows = s.exec(select(Note).where(Note.tags.contains(TAG)).order_by(Note.created_at.desc()).limit(limit)).all()
    return [n for n in rows if TAG in (n.tags or "").split(",")]


def find(query: str, limit: int = 3) -> list[Note]:
    q = query.strip()
    if not q:
        return all_(limit)
    scored = [(score(n.text, q), n) for n in all_(200)]
    scored = [x for x in scored if x[0] >= 0.3]
    scored.sort(key=lambda x: (-x[0], x[1].created_at))
    return [n for _, n in scored[:limit]]


def text_list(limit: int = 8) -> str:
    rows = all_(limit)
    if not rows:
        return "Решений пока не записано. Скажи «решил: …, потому что …» — запишу."
    out = ["Решения:"]
    for n in rows:
        what, why = split(n.text)
        out.append(f"· {n.created_at:%d.%m} — {what}" + (f" (потому что {why})" if why else ""))
    return "\n".join(out)


def text_why(query: str) -> str:
    rows = find(query)
    if not rows:
        return f"Про «{query}» решений не записано." if query else "Решений не записано."
    n = rows[0]
    what, why = split(n.text)
    line = f"{n.created_at:%d.%m.%Y}: {what}"
    if why:
        line += f" — потому что {why}."
    else:
        line += ". Причину ты тогда не назвал."
    if len(rows) > 1:
        line += "\nЕщё рядом: " + "; ".join(split(x.text)[0][:60] for x in rows[1:])
    return line


def chat_rule(text_in: str, source: str = "tg") -> str | None:
    t = text_in or ""
    m = DECIDE_RX.match(t)
    if m and len(m.group(1).strip()) >= 4:
        n = add(m.group(1), source)
        what, why = split(n.text)
        return f"Записал решение: {what}" + (f" — потому что {why}" if why else ". Если есть причина — скажи, допишу.")
    m = WHY_RX.match(t)
    if m:
        return text_why(m.group(1))
    if LIST_RX.match(t):
        return text_list()
    return None
