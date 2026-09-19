"""Лента дня: что делал человек и что делал Марвин — одной хронологией.

Сшивает четыре источника, которые раньше жили порознь:
• Memory — действия (записал трату, закрыл задачу, поставил цель) и события (сел/ушёл/рендер/фон);
• ScreenSlot — сессии за ПК и смены занятия (только куски ≥ min_block минут, иначе лента — шум);
• ChatMessage — факт разговора (сколько сообщений за час), НЕ текст;
• Run — только упавшие ходы («не понял»), чтобы «почему он тупил в 15:40» тоже было видно.

Отвечает на «что я сегодня делал», «что было вчера», «что происходило с <проект/цель> вчера» (фильтр по словам).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlmodel import select

from ..db import ChatMessage, Memory, Run, ScreenSlot, session
from .match import tokens

MIN_BLOCK_MIN = 15


def _bounds(day: datetime | None) -> tuple[datetime, datetime]:
    d = (day or datetime.now()).replace(hour=0, minute=0, second=0, microsecond=0)
    return d, d + timedelta(days=1)


def build(day: datetime | None = None, query: str | None = None, min_block: int = MIN_BLOCK_MIN) -> list[dict]:
    """[{at, kind, text, who}] отсортировано. who: «я» (человек) / «марвин» / «пк». query — фильтр по словам."""
    d0, d1 = _bounds(day)
    items: list[dict] = []
    with session() as s:
        for m in s.exec(select(Memory).where(Memory.created_at >= d0, Memory.created_at < d1).order_by(Memory.created_at)).all():
            if m.kind == "chat":
                continue
            who = "марвин" if m.channel == "system" or m.kind == "presence" else "я"
            if m.kind == "presence":
                who = "пк" if m.text.startswith(("сел", "отошёл", "вернулся", "давно нет", "без перерыва", "запущена", "тяжёлая", "переключился")) else "марвин"
            items.append({"at": m.created_at, "kind": m.kind, "text": m.text, "who": who})
        # экран: сессии и длинные блоки
        rows = s.exec(select(ScreenSlot).where(ScreenSlot.end >= d0, ScreenSlot.start < d1).order_by(ScreenSlot.start)).all()
        cur: dict | None = None
        for r in rows:
            if r.idle:
                if cur:
                    items.append(cur); cur = None
                continue
            a, b = max(r.start, d0), min(r.end, d1)
            label = r.app if r.category != "браузер" else (r.title or r.app)
            if cur and cur["_label"] == label and (a - cur["_end"]).total_seconds() <= 120:
                cur["_end"] = b
                continue
            if cur:
                items.append(cur)
            cur = {"at": a, "kind": "screen", "text": label, "who": "пк", "_label": label, "_end": b, "cat": r.category}
        if cur:
            items.append(cur)
        # разговор: по часам
        chats = s.exec(select(ChatMessage).where(ChatMessage.created_at >= d0, ChatMessage.created_at < d1, ChatMessage.role == "user")).all()
        by_hour: dict[int, int] = {}
        for c in chats:
            by_hour[c.created_at.hour] = by_hour.get(c.created_at.hour, 0) + 1
        for h, n in by_hour.items():
            items.append({"at": d0.replace(hour=h), "kind": "chat", "text": f"разговор с Марвином ({n} сообщ.)", "who": "я"})
        # упавшие ходы
        for r in s.exec(select(Run).where(Run.created_at >= d0, Run.created_at < d1, Run.ok == False)).all():  # noqa: E712
            items.append({"at": r.created_at, "kind": "fail", "text": f"не справился: «{(r.text or '')[:50]}»", "who": "марвин"})
    # блоки экрана короче min_block — убираем; оформляем длительность
    out = []
    for it in items:
        if it["kind"] == "screen":
            mins = (it["_end"] - it["at"]).total_seconds() / 60
            if mins < min_block:
                continue
            it["text"] = f"{it['_label']} — {int(mins)} мин"
            it["end"] = it.pop("_end"); it.pop("_label", None)
        out.append(it)
    out.sort(key=lambda x: x["at"])
    if query:
        q = set(tokens(query))
        if q:
            out = [i for i in out if q & set(tokens(i["text"]))]
    return out


def text(day: datetime | None = None, query: str | None = None, limit: int = 40) -> str:
    items = build(day, query)
    label = "сегодня" if not day or day.date() == datetime.now().date() else ("вчера" if day.date() == (datetime.now() - timedelta(days=1)).date() else f"{day:%d.%m}")
    if not items:
        return f"За {label} в ленте пусто" + (f" по «{query}»" if query else "") + "."
    lines = [f"Лента за {label}" + (f" · «{query}»" if query else "") + ":"]
    for it in items[-limit:]:
        mark = {"я": "", "марвин": "🤖 ", "пк": "🖥 "}[it["who"]]
        lines.append(f"{it['at']:%H:%M} — {mark}{it['text']}")
    return "\n".join(lines)


import re
TIMELINE_RX = re.compile(r"^\s*(?:что\s+(?:я\s+)?(?:сегодня|вчера)\s+(?:делал\w*|происходило)|что\s+(?:происходило|было|делал\w*)\s+(?:сегодня|вчера)"
                         r"|лента(?:\s+(?:дня|за сегодня|за вчера))?|хронология(?:\s+(?:сегодня|вчера))?"
                         r"|что\s+(?:происходило|было|делал\w*)\s+(?:с|по)\s+(.+?)\s+(сегодня|вчера))\s*\??\s*$", re.I)


def chat_rule(text_in: str) -> str | None:
    m = TIMELINE_RX.match(text_in or "")
    if not m:
        return None
    low = text_in.lower()
    day = datetime.now() - timedelta(days=1) if "вчера" in low else None
    return text(day, m.group(1))
