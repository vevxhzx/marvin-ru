"""Привычки по времени: когда человек реально пишет/отвечает — для «умного» откладывания напоминаний.

Считается локально по записям (Memory). Ничего не меняет; наружу отдаёт только догадку —
её подтверждает человек кнопкой «⏰ По привычке». Если данных мало, честно молчим.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta

from sqlmodel import select

from ..db import Memory, session

log = logging.getLogger("jarvis.habits")

DAYS = 90
MIN_SAMPLES = 8


def active_hours(days: int = DAYS) -> list[tuple[int, int]]:
    """Сколько записей в каждый час суток (24 → счёт), по свежим записям."""
    since = datetime.now() - timedelta(days=days)
    with session() as s:
        rows = s.exec(select(Memory).where(Memory.created_at >= since, Memory.channel != "system")).all()
    c = Counter(m.created_at.hour for m in rows)
    return sorted(c.items(), key=lambda kv: -kv[1])


def best_hour(default: int = 20) -> int:
    """Самый «живой» час суток (0–23). Мало данных — default."""
    hours = active_hours()
    if sum(n for _, n in hours) < MIN_SAMPLES:
        return default
    # сглаживаем соседей, чтобы не поймать случайный выброс одного часа
    score: Counter = Counter()
    for h, n in hours:
        score[h] += n
        score[(h - 1) % 24] += n // 2
        score[(h + 1) % 24] += n // 2
    return score.most_common(1)[0][0]


def next_habit(now: datetime | None = None) -> datetime:
    """Ближайшее привычное время: сегодня в best_hour, если оно ещё не близко, иначе завтра."""
    now = now or datetime.now()
    cand = now.replace(hour=best_hour(), minute=0, second=0, microsecond=0)
    if cand <= now + timedelta(minutes=30):
        cand += timedelta(days=1)
    return cand


def hint() -> str | None:
    """Подсказка для напоминания. None — если по данным ещё нечего советовать."""
    if sum(n for _, n in active_hours()) < MIN_SAMPLES:
        return None
    return f"Обычно вы отвечаете около {best_hour():02d}:00 — можно отложить на это время."
