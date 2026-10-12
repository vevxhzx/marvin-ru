# -*- coding: utf-8 -*-
"""«итоги дня» — это дайджест, а не заметка в мозг (живой баг из мини-приложения)."""
import asyncio
import os

os.environ.setdefault("ASSISTANT_TEST", "1")


def _offline(monkeypatch):
    from core.brain import llm

    async def _no_false(*a, **k):
        return False

    async def _no_none(*a, **k):
        return None

    async def _no_empty(*a, **k):
        return ""

    monkeypatch.setattr(llm, "ollama_available", _no_false)
    monkeypatch.setattr(llm, "embed_available", _no_false)
    monkeypatch.setattr(llm, "cloud_enabled", lambda: False)
    monkeypatch.setattr(llm, "ollama_chat", _no_none)
    monkeypatch.setattr(llm, "cloud_chat", _no_none)
    monkeypatch.setattr(llm, "small_chat", _no_empty)


def _h(text, ch="tg"):
    from core.brain import agent
    return asyncio.run(agent.handle(text, ch))


def test_itogi_dnya_is_briefing(fresh_db, monkeypatch):
    _offline(monkeypatch)
    for phrase in ("итоги дня", "итоги", "подведи итоги дня"):
        r = _h(phrase, "tg")
        assert "briefing" in r.actions, (phrase, r.actions, r.text[:120])
        assert "add_note" not in r.actions
