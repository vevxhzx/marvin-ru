# -*- coding: utf-8 -*-
"""Правила памяти: запомни / забудь / восстанови / что ты знаешь.

Вынесено из core/brain/agent.py 1:1. Общие хелперы (Reply, regexes,
_looks_like_question) остаются в agent и импортируются здесь.
Сигнатура каждого правила: (text, low, channel) -> Reply | None.
"""
from __future__ import annotations

from ..agent import (
    MEM_ABOUT_RX,
    MEM_FORGET_RX,
    MEM_REMEMBER_RX,
    MEM_RESTORE_RX,
    Reply,
    _ME_RX,
    _looks_like_question,
)


def memory_rule(text: str, low: str, channel: str) -> Reply | None:
    from core.services import memory

    t = text
    if not memory.enabled():
        return None
    if MEM_ABOUT_RX.match(t):
        return Reply(memory.about_me_text(), ["about_me"])
    m = MEM_FORGET_RX.match(t)
    if m and len(t.split()) <= 20:
        what = m.group(1).strip(" .!")
        f = memory.find_fact(what)
        if f:
            memory.forget(f.id)
            return Reply(f"Забыл: «{f.text}». Лежит в архиве памяти — если что, верну («восстанови …»).", ["forget_fact"])
        arch = memory.find_fact(what, include_archived=True)
        if arch is not None:
            return Reply(f"«{arch.text}» — так я уже и не помню: оно в архиве памяти. Скажите «восстанови …», если нужно вернуть.", [])
        return Reply(f"Такого я и не помнил, сэр: «{what}». Проверьте страницу «память».", [])
    m = MEM_RESTORE_RX.match(t)
    if m and len(t.split()) <= 20:
        # восстановление затухшего/забытого факта: ищем и в архиве (recall/find_fact с include_archived=True)
        f = memory.find_fact(m.group(1).strip(" .!"), include_archived=True)
        if f is not None and f.layer == "archive":
            memory.restore(f.id)
            return Reply(f"Вернул: «{f.text}» — снова в памяти, и больше он не затухнет.", ["restore_fact"])
    m = MEM_REMEMBER_RX.match(t)
    if m and _ME_RX.search(m.group(1)) and len(t.split()) <= 40 and not _looks_like_question(t):
        body = m.group(1).strip(" .!")
        f = memory.add_fact_sync(body, layer="long", confidence=0.95)   # вектор досчитает планировщик
        if f:
            return Reply(f"Запомнил: «{f.text}». Это теперь часть того, что я о вас знаю.", ["add_fact"])
    return None


RULES = [memory_rule]
