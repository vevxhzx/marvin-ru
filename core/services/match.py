"""Нечёткий поиск по названиям без словаря: «встречу с ваней» находит «Встреча с Ваней»,
«тренировки» — «Тренировка», «долг ване» — «Долг Ване».

Идея: режем окончания (грубый стемминг), выкидываем предлоги, и требуем, чтобы все значимые
слова запроса нашлись в названии. Работает для русского/английского без внешних библиотек.
"""
from __future__ import annotations

import re
from typing import Callable, Iterable, TypeVar

T = TypeVar("T")

STOP = {"с", "со", "на", "в", "во", "к", "ко", "о", "об", "обо", "у", "и", "а", "по", "за", "для", "от", "до", "из",
        "про", "это", "эту", "этот", "эта", "мой", "моя", "мою", "моё", "мое", "мои", "меня", "мне", "я", "же", "ли",
        "the", "a", "an", "of", "to", "at", "in", "on"}
# слова-обёртки, которые обычно стоят перед названием: «задачу про полку», «событие встреча»
WRAP = {"задачу", "задача", "задачи", "событие", "события", "встречу", "напоминание", "заметку", "заметка", "мысль",
        "долг", "долга", "подписку", "подписка", "платёж", "платеж", "регулярный", "регулярку"}


_VOWELS = "аеиоуыэюяйь"


def stem(word: str) -> str:
    """Грубая основа: срезаем до двух гласных окончаний. еда/еду → ед, встреча/встречу → встреч, ваней/ваня → ван."""
    w = word.lower().replace("ё", "е")
    for _ in range(2):
        if len(w) > 2 and w[-1] in _VOWELS:
            w = w[:-1]
    return w


def same(a: str, b: str) -> bool:
    """Одно ли это слово в разных формах: еда/еду, такси/такси, продукты/продуктов."""
    sa, sb = stem(a), stem(b)
    if sa == sb:
        return True
    if len(sa) >= 4 and len(sb) >= 4 and (sa.startswith(sb) or sb.startswith(sa)):
        return True
    return False


def tokens(text: str, drop_wrap: bool = False) -> list[str]:
    out = []
    for w in re.findall(r"[а-яёa-z0-9]+", (text or "").lower()):
        if w in STOP or len(w) < 2:
            continue
        if drop_wrap and w in WRAP:
            continue
        out.append(stem(w))
    return out


def score(title: str, query: str) -> float:
    """Доля слов запроса, найденных в названии (0..1)."""
    tt = (title or "").lower().replace("ё", "е")
    toks = tokens(query, drop_wrap=True) or tokens(query)
    if not toks:
        return 0.0
    hit = sum(1 for q in toks if q in tt)
    return hit / len(toks)


def best(items: Iterable[T], query: str, key: Callable[[T], str] = lambda x: getattr(x, "title", ""),
         min_score: float = 1.0) -> T | None:
    """Лучший кандидат: сначала полное совпадение всех слов, иначе — не меньше min_score (для длинных запросов 2/3)."""
    items = list(items)
    if not items:
        return None
    q = (query or "").strip()
    if not q:
        return None
    scored = sorted(((score(key(i), q), i) for i in items), key=lambda p: -p[0])
    top, item = scored[0]
    if top >= 1.0:
        return item
    ntok = len(tokens(q, drop_wrap=True) or tokens(q))
    floor = min(min_score, 0.66) if ntok >= 3 else min_score
    return item if top >= floor and top > 0 else None
