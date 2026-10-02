# -*- coding: utf-8 -*-
"""Релевантные уроки хозяина в промпте: лимит 6–8, свежесть/применённые в приоритете,
не повторять подряд, mute-формулировки, колонки applied/last_applied_at (миграция v6)."""
from __future__ import annotations

import asyncio
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path

os.environ["ASSISTANT_TEST"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import db  # noqa: E402
from core.brain import agent  # noqa: E402
from core.services import judge  # noqa: E402


def _offline(monkeypatch):
    """Ни Ollama, ни облака — уроки отбираются по пересечению слов, без эмбеддингов."""
    from core.brain import llm
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)

    async def no_ollama(force=False):
        return False
    monkeypatch.setattr(llm, "ollama_available", no_ollama)

    async def emb_avail():
        return False
    monkeypatch.setattr(llm, "embed_available", emb_avail)


def _shown(blk: str) -> list[str]:
    """Тексты уроков из блока (строки начинаются на «— «...»)."""
    return re.findall(r"— «(.+?)»", blk)


def _backdate(lid: int, days: int) -> None:
    from sqlalchemy import text as _t
    with db.session() as s:
        s.exec(_t("UPDATE lesson SET created_at = :t WHERE id = :i"),
               params={"t": datetime.now() - timedelta(days=days), "i": int(lid)})
        s.commit()


def test_lessons_block_cap_relevance_and_mute(fresh_db, monkeypatch):
    """Из 10 релевантных — максимум LESSON_MAX; нерелевантные мимо; mute — своей формулировкой."""
    _offline(monkeypatch)
    assert 6 <= agent.LESSON_MAX <= 8
    assert asyncio.run(agent._lessons_block("оформи заказ через сайт")) == ""   # уроков ещё нет

    for i in range(9):
        assert judge.add_lesson(f"заказ через сайт — вариант {i}", "order")
    assert judge.add_lesson("купить молоко и хлеб завтра", "task")              # нерелевантный
    mute = judge.add_lesson("заказ через сайт", "mute")                         # релевантный, но mute
    assert mute is not None

    blk = asyncio.run(agent._lessons_block("оформи заказ через сайт для клиента"))
    assert blk.startswith("\nУРОКИ ХОЗЯИНА")
    lines = [l for l in blk.splitlines() if l.startswith("— «")]
    assert len(lines) == agent.LESSON_MAX                       # 10 релевантных → обрезка до лимита
    texts = _shown(blk)
    assert len(texts) == len(set(texts)), texts                 # уроки не дублируются в блоке
    assert not any("молоко" in t for t in texts)                # нерелевантный не протёк
    assert any("НЕ предлагать" in l for l in lines)             # mute — явной формулировкой
    assert sum("→ это заказ" in l for l in lines) == len(lines) - 1   # остальные — с типом «заказ»

    # показанные уроки помечены applied + last_applied_at (колонки v6)
    meta = agent._lesson_meta()
    by_text = {l.text: l.id for l in judge.list_lessons()}
    for t in texts:
        m = meta[by_text[t]]
        assert m["applied"] and m["last_applied"] is not None, t
    assert db.get_setting(agent.LESSON_SHOWN_KEY) == str(by_text[texts[0]])


def test_lessons_fresh_outranks_older(fresh_db, monkeypatch):
    """Свежий урок идёт выше старого, даже если id у старого больше (тёк-брейк в его пользу)."""
    _offline(monkeypatch)
    fresh = judge.add_lesson("заказ через сайт вариант а", "order")
    old = judge.add_lesson("заказ через сайт вариант б", "order")
    assert fresh.id < old.id
    _backdate(old.id, 60)

    texts = _shown(asyncio.run(agent._lessons_block("оформи заказ через сайт")))
    i_fresh = next(i for i, t in enumerate(texts) if "вариант а" in t)
    i_old = next(i for i, t in enumerate(texts) if "вариант б" in t)
    assert i_fresh < i_old, "свежий урок должен идти выше старого"


def test_lessons_not_repeated_back_to_back(fresh_db, monkeypatch):
    """Урок, показанный в прошлый ход, подряд не повторяется; после сброса флага — снова доступен."""
    _offline(monkeypatch)
    assert judge.add_lesson("заказ через сайт вариант а", "order")
    assert judge.add_lesson("заказ через сайт вариант б", "order")
    q = "оформи заказ через сайт"
    t1 = _shown(asyncio.run(agent._lessons_block(q)))
    t2 = _shown(asyncio.run(agent._lessons_block(q)))
    assert len(t1) == 2 and len(t2) == 1
    assert t1[0] not in t2                                       # показанный ход подряд не идёт
    db.set_setting(agent.LESSON_SHOWN_KEY, "")
    t3 = _shown(asyncio.run(agent._lessons_block(q)))
    assert len(t3) == 2                                          # после сброса снова оба


def test_lessons_single_skips_repeat(fresh_db, monkeypatch):
    """Единственный урок подряд не показываем дважды — и пропускаем ход, не теряя урок насовсем."""
    _offline(monkeypatch)
    assert judge.add_lesson("заказ через сайт", "order")
    assert "заказ" in asyncio.run(agent._lessons_block("оформи заказ через сайт"))
    assert asyncio.run(agent._lessons_block("оформи заказ через сайт")) == ""    # он единственный — пауза
    assert "заказ" in asyncio.run(agent._lessons_block("оформи заказ через сайт"))  # следующий ход — снова можно
    assert asyncio.run(agent._lessons_block("   ")) == ""                        # пустой запрос — пусто
