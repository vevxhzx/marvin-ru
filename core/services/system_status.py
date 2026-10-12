# -*- coding: utf-8 -*-
"""Хелперы для GET /api/status (system.py): вынести прямые select из роутера.

Подготовлено в audit-wave4, роутер system.py НЕ тронут (вне разрешённого
списка файлов) — подключение этих хелперов следующей волной, поведение
ответа должно остаться 1:1. Функции повторяют те же запросы, что сейчас
лежат в system.py:244-261.
"""
from __future__ import annotations

from sqlmodel import select
from sqlalchemy import func as _f

from ..db import (
    ActionLog as _AL,
    ChatMessage,
    Event,
    Link,
    Memory as _Mem,
    Note,
    Task,
    Transaction,
    get_setting,
    session,
)


def last_tg_message() -> ChatMessage | None:
    """Последнее сообщение из Telegram (каналы tg/tg-voice) — или None."""
    with session() as s:
        return s.exec(
            select(ChatMessage)
            .where(ChatMessage.channel.in_(["tg", "tg-voice"]))
            .order_by(ChatMessage.id.desc())
        ).first()


def table_counts() -> dict:
    """Размеры предметных таблиц для блока "db" в /api/status."""
    with session() as s:
        return {
            "events": len(s.exec(select(Event)).all()),
            "tasks": len(s.exec(select(Task)).all()),
            "notes": len(s.exec(select(Note)).all()),
            "links": len(s.exec(select(Link)).all()),
            "transactions": len(s.exec(select(Transaction)).all()),
        }


def retention_counts() -> dict:
    """Размеры retention-таблиц + метка последней чистки (только чтение)."""
    with session() as s:
        return {
            "chatmessage": int(s.exec(select(_f.count()).select_from(ChatMessage)).one() or 0),
            "memory": int(s.exec(select(_f.count()).select_from(_Mem)).one() or 0),
            "actionlog": int(s.exec(select(_f.count()).select_from(_AL)).one() or 0),
            "last": get_setting("retention:last"),
        }
