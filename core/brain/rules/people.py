# -*- coding: utf-8 -*-
"""Правила людей: «что по Ване», «кто такой Иванов», «человек: Лена, сестра».

Вынесено из core/brain/agent.py 1:1. Regexes и Reply остаются в agent.
"""
from __future__ import annotations

from ..agent import PERSON_ADD_RX, PERSON_Q_RX, Reply


def people_rule(text: str, low: str, channel: str) -> Reply | None:
    """«что по Ване», «кто такой Иванов», «человек: Лена, сестра» — без модели."""
    from core.services import people

    t = text
    m = PERSON_Q_RX.match(t)
    if m:
        q = m.group(1).strip()
        cands = people.find_candidates(q)
        if len(cands) >= 2:
            # тёзки: молча никого не выбираем — спрашиваем одним словом (батч 4)
            shown = " или ".join(f"«{c.name}»" for c in cands[:3])
            return Reply(f"Какой {q}: {shown}? Уточните, сэр.", ["clarify"],
                         buttons=[(c.name[:32], c.name) for c in cands[:3]])
        if cands:
            return Reply(people.card_text(people.card(cands[0])), ["person_card"])
        return None   # неизвестное имя — пусть решает модель/память
    m = PERSON_ADD_RX.match(t)
    if m:
        body = m.group(1).strip()
        head = t.lower().lstrip()
        kind = ("client" if head.startswith("клиент") else "company" if head.startswith(("компани", "фирм"))
                else "family" if head.startswith(("семья", "родн", "родствен")) else "friend" if head.startswith(("друг", "подруг", "прият"))
                else None)   # None — угадать по подписи
        name, _, rest = body.partition(",")
        name = name.strip(" «»\"'")
        if not name or len(name) > 60:
            return None
        c = people.add_person(name, kind, notes=rest.strip() or None)
        return Reply(f"{ {'client': 'Клиент', 'company': 'Компания', 'family': 'Семья', 'friend': 'Друг'}.get(c.kind, 'Карточка')} «{c.name}» — есть. Всё, где всплывёт это имя, теперь собирается в одном месте — спросите «что по …» или «кто такой …».", ["add_person"])
    return None


RULES = [people_rule]
