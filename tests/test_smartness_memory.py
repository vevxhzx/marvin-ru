# -*- coding: utf-8 -*-
"""Умная память: затухание фактов (decay), мета-колонки v5/v6, ночная архивация,
подтверждение/отклонение факта, сводки без устаревшего и дублей, восстановление из архива."""
from __future__ import annotations

import asyncio
import math
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

os.environ["ASSISTANT_TEST"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import db, migrations  # noqa: E402
from core.brain import agent  # noqa: E402
from core.services import memory  # noqa: E402


# ------------------------------------------------------------------ инфраструктура
def _offline(monkeypatch, embeds=None):
    """Ни Ollama, ни облака; эмбеддинги — по словарю `embeds` (подстрока → вектор), иначе выключены."""
    from core.brain import llm

    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)

    async def no_ollama(force=False):
        return False
    monkeypatch.setattr(llm, "ollama_available", no_ollama)

    async def emb_avail():
        return embeds is not None
    monkeypatch.setattr(llm, "embed_available", emb_avail)

    async def emb(texts):
        out = []
        for t in texts:
            v = [0.0, 0.0, 0.0]
            for k, vec in (embeds or {}).items():
                if k in t.lower():
                    v = [a + b for a, b in zip(v, vec)]
            out.append(v if any(v) else [0.0, 0.0, 1.0])
        return out
    monkeypatch.setattr(llm, "embed", emb)


def _facts():
    with db.session() as s:
        return list(s.exec(db.select(db.Fact)))


def _meta(fid: int) -> dict:
    """Мета одного факта: fact_meta возвращает dict, ключ — id."""
    return memory.fact_meta({fid})[fid]


def _age(text: str, days: int, confirmed: bool = False, uses: int = 0) -> None:
    """Состарить факт: created_at/last_seen_at назад на `days` (raw SQL: колонок v5 в модели Fact нет)."""
    from sqlalchemy import text as _t
    ts = datetime.now() - timedelta(days=days)
    with db.session() as s:
        s.exec(_t("UPDATE fact SET created_at = :c, last_seen_at = :l, confirmed_at = :cf, uses = :u WHERE text = :t"),
               params={"c": ts, "l": ts, "cf": ts if confirmed else None, "u": uses, "t": text})
        s.commit()


# ------------------------------------------------------------------ 1. миграции v5/v6
def test_migrations_v5_v6_columns(fresh_db):
    """Свежая БД: колонки затухания фактов, applied/last_applied_at у уроков, индекс, версия = максимуму."""
    from sqlalchemy import text as _t
    with db.engine.connect() as conn:
        fact_cols = migrations.column_names(conn, "fact")
        lesson_cols = migrations.column_names(conn, "lesson")
        idx = {r[1] for r in conn.execute(_t("PRAGMA index_list('fact')")).all()}
    assert {"last_seen_at", "confirmed_at", "archived_at"} <= fact_cols
    assert {"applied", "last_applied_at"} <= lesson_cols
    assert "ix_fact_confirmed_at" in idx
    versions = [v for v, _, _ in migrations.MIGRATIONS]
    assert versions == list(range(1, versions[-1] + 1)) and versions[-1] >= 6
    assert migrations.current_version(db.engine) == versions[-1]
    # повторный запуск ничего не применяет — миграции идемпотентны
    assert migrations.apply(db.engine, had_db=False)["applied"] == []


# ------------------------------------------------------------------ 2. decay()
def test_decay_levels(monkeypatch):
    """Ядро и подтверждённые не гаснут; остальные — exp(-Δt/half_life), референс — последнее упоминание."""
    monkeypatch.setattr(memory, "decay_half_life", lambda: 90.0)
    now = datetime.now()
    assert memory.decay(True, None, now - timedelta(days=400)) == 1.0                       # core
    assert memory.decay(False, now - timedelta(days=400), now - timedelta(days=400)) == 1.0  # confirmed
    assert memory.decay(False, None, None) == 1.0                                            # нет данных — не гасим
    fresh = memory.decay(False, None, now - timedelta(days=10))
    half = memory.decay(False, None, now - timedelta(days=90))
    old = memory.decay(False, None, now - timedelta(days=400))
    assert 0.85 < fresh < 1.0
    assert abs(half - math.exp(-1)) < 1e-6          # ровно один полупериод
    assert old < 0.05
    # «давно не вспоминали» важнее даты: чем старше референс, тем сильнее гаснет
    assert memory.decay(False, None, now - timedelta(days=200)) < memory.decay(False, None, now - timedelta(days=30))
    # затухание ниже FADE_SUMMARY — факт уходит из сводок
    assert memory._faded(False, None, now - timedelta(days=400)) is True
    assert memory._faded(False, None, now - timedelta(days=5)) is False


# ------------------------------------------------------------------ 3. recall()
def test_recall_drops_faded_fact(fresh_db, monkeypatch):
    """Старый неподтверждённый факт больше не тащится в каждый ответ, а свежий — всплывает."""
    _offline(monkeypatch, embeds={"пельмени": [1, 0, 0], "мясом": [0, 0, 1], "ужин": [0, 1, 0]})
    asyncio.run(memory.add_fact("пельмени люблю", category="предпочтение"))
    _age("пельмени люблю", 400)                    # давно не упоминали → почти затух
    asyncio.run(memory.add_fact("ужин готовлю в семь", category="быт"))

    texts = [f.text for f in asyncio.run(memory.recall("пельмени ужин", limit=5))]
    assert any("ужин" in t for t in texts), texts
    assert not any("пельмени" in t for t in texts), texts   # затухший фоном не всплывает

    # свежий «пельмени» по той же формуле проходит — дело именно в затухании, а не в тексте
    asyncio.run(memory.add_fact("пельмени с мясом любим", category="предпочтение"))
    texts2 = [f.text for f in asyncio.run(memory.recall("пельмени ужин", limit=5))]
    assert any("пельмени с мясом" in t for t in texts2), texts2
    assert not any("пельмени люблю" == t for t in texts2), texts2


def test_recall_archived_only_with_flag(fresh_db, monkeypatch):
    """Архивный факт обычный recall не видит, но видит с include_archived=True (восстановление)."""
    _offline(monkeypatch, embeds={"пельмени": [1, 0, 0]})
    f = asyncio.run(memory.add_fact("пельмени люблю", category="предпочтение"))
    memory.forget(f.id, reason="тест")
    assert asyncio.run(memory.recall("пельмени", limit=5)) == []
    got = asyncio.run(memory.recall("пельмени", limit=5, include_archived=True))
    assert any("пельмени" in x.text for x in got)
    # свежий архивный по-прежнему вне обычного поиска
    assert memory.find_fact("пельмени люблю") is None
    assert memory.find_fact("пельмени люблю", include_archived=True) is not None


# ------------------------------------------------------------------ 4. ночная архивация (decay)
def test_nightly_archives_faded(fresh_db, monkeypatch):
    """Ночью уходят в архив только затухшие неподтверждённые и почти не упоминавшиеся."""
    _offline(monkeypatch)
    monkeypatch.setattr(memory, "decay_days", lambda: 30)
    monkeypatch.setattr(memory, "decay_max_mentions", lambda: 2)
    asyncio.run(memory.add_fact("пельмени в холодильнике", category="быт"))
    asyncio.run(memory.add_fact("клавиатура новая", category="быт"))
    asyncio.run(memory.add_fact("кофе пью много", category="привычка"))
    asyncio.run(memory.add_fact("сок апельсиновый", category="быт"))
    _age("пельмени в холодильнике", 40)                        # затухло → архив
    _age("клавиатура новая", 40, confirmed=True)               # подтверждено → живёт
    _age("кофе пью много", 40, uses=5)                         # часто вспоминали → живёт
    _age("сок апельсиновый", 5)                                # свежий → живёт

    out = asyncio.run(memory.nightly())
    assert set(out) == {"promoted", "archived"}                # формат возврата не расширяем
    assert out["archived"] >= 1

    state = {f.text: f for f in _facts()}
    faded = state["пельмени в холодильнике"]
    assert faded.layer == "archive" and faded.archive_reason == "затухло"
    assert _meta(faded.id)["archived"] is not None   # archived_at проставлен
    assert state["клавиатура новая"].layer != "archive"
    assert state["кофе пью много"].layer != "archive"
    assert state["сок апельсиновый"].layer != "archive"


def test_mention_refreshes_last_seen(fresh_db, monkeypatch):
    """Повтор в реплике хозяина обновляет last_seen_at — иначе факт затухнет навсегда."""
    _offline(monkeypatch)
    asyncio.run(memory.add_fact("пельмени люблю", category="предпочтение"))
    _age("пельмени люблю", 400)
    fid = next(f.id for f in _facts() if "пельмени" in f.text)
    old_seen = _meta(fid)["last_seen"]
    assert old_seen is not None and old_seen < datetime.now() - timedelta(days=300)
    # ту же фразу сказали снова — дата упоминания обновляется (дедуп add_fact, а не инжект в промпт)
    asyncio.run(memory.add_fact("пельмени люблю", category="предпочтение"))
    new_seen = _meta(fid)["last_seen"]
    assert new_seen > datetime.now() - timedelta(minutes=1)
    assert len(_facts()) == 1                                    # дубль не создался


# ------------------------------------------------------------------ 5. confirm / dismiss
def test_confirm_sets_confirmed_at(fresh_db):
    f = memory.add_fact_sync("люблю чай без сахара", category="предпочтение")
    assert f is not None
    assert _meta(f.id)["confirmed"] is None
    got = memory.confirm(f.id)
    assert got is not None and got.id == f.id
    meta = _meta(f.id)
    assert meta["confirmed"] is not None and meta["last_seen"] is not None
    # подтверждённый факт не гаснет никогда
    assert memory.decay(False, meta["confirmed"], datetime.now() - timedelta(days=400)) == 1.0


def test_confirm_by_text_creates_confirmed(fresh_db):
    """«Да, запомни» по тексту, когда факта ещё нет: создаётся сразу подтверждённым."""
    f = memory.confirm(None, "пельмени с мясом любим", "предпочтение")
    assert f is not None
    assert _meta(f.id)["confirmed"] is not None
    assert memory.confirm(None, "") is None


def test_dismiss_archives_and_blocks_extract(fresh_db, monkeypatch):
    """«нет» в тосте: факт в архив, фраза в отклонённые — extract её больше не сохранит."""
    _offline(monkeypatch)
    f = memory.add_fact_sync("пиво по пятницам", category="привычка")
    assert memory.dismiss(f.id, f.text) is True
    assert memory.find_fact("пиво по пятницам") is None
    assert memory.find_fact("пиво по пятницам", include_archived=True) is not None

    async def fake_ask(system, user):
        return {"add": [{"text": "пиво по пятницам", "layer": "short", "category": "привычка"}],
                "update": []}, "cloud"
    monkeypatch.setattr(memory, "_ask", fake_ask)
    res = asyncio.run(memory.extract("а пиво по пятницам я люблю каждую пятницу"))
    assert res["added"] == []
    assert not any(x.text == "пиво по пятницам" and x.layer != "archive" for x in _facts())


# ------------------------------------------------------------------ 6. сводки и контекст
def test_about_me_skips_archived_faded_and_dupes(fresh_db, monkeypatch):
    """«Что ты обо мне знаешь?»: без архивных, без затухших, без вложенных дублей."""
    _offline(monkeypatch)
    asyncio.run(memory.add_fact("пельмени люблю", category="предпочтение"))
    asyncio.run(memory.add_fact("пельмени люблю с мясом", category="предпочтение"))  # вложенный дубль
    asyncio.run(memory.add_fact("кофе пью каждый день", category="привычка"))
    asyncio.run(memory.add_fact("тарелки синие", category="быт"))
    _age("тарелки синие", 400)
    memory.forget(next(f.id for f in _facts() if "кофе" in f.text), reason="тест")

    txt = memory.about_me_text()
    assert "пельмени" in txt
    assert txt.count("пельмени") == 1, txt      # дубль схлопнут
    assert "тарелки" not in txt, txt            # затухший не попадает
    assert "кофе" not in txt, txt               # архивный не попадает


def test_context_dedupes_nested_facts(fresh_db, monkeypatch):
    """context() не выдаёт вложенный дубль дважды."""
    _offline(monkeypatch)
    asyncio.run(memory.add_fact("кофе пью каждый день", category="привычка"))
    asyncio.run(memory.add_fact("кофе пью каждый день с утра", category="привычка"))
    ctx = asyncio.run(memory.context("кофе люблю пить"))
    assert "кофе" in ctx
    assert ctx.count("кофе пью каждый день") == 1, ctx


# ------------------------------------------------------------------ 7. восстановление
def test_restore_rule_from_archive(fresh_db, monkeypatch):
    """«восстанови …» возвращает затухший/забытый факт — даже без эмбеддингов."""
    _offline(monkeypatch)
    asyncio.run(memory.add_fact("тарелки синие", category="быт"))
    fid = asyncio.run(memory.recall("тарелки", limit=1))[0].id
    memory.forget(fid, reason="тест")
    assert memory.find_fact("тарелки синие") is None

    r = agent._memory_rules("восстанови тарелки", "test")
    assert r is not None and "restore_fact" in r.actions
    assert memory.find_fact("тарелки синие") is not None        # снова живой
    assert _meta(fid)["confirmed"] is not None       # восстановление = подтверждение
    # неизвестное слово — молча ничего не делаем
    assert agent._memory_rules("восстанови космодесант", "test") is None
