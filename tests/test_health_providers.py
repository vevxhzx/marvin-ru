# -*- coding: utf-8 -*-
"""Самодиагностика знает про оба движка: при основном на LM Studio лежащая
Ollama — не «проблема», о которой надо кричать каждый час.
"""
from __future__ import annotations

import asyncio

from tests.test_core import fresh_db  # noqa: E402,F401  (autouse-изоляция БД)


def _llm(monkeypatch, **kw):
    from core.brain import llm

    for k, v in kw.items():
        if callable(v):
            monkeypatch.setattr(llm, k, v)
        else:
            monkeypatch.setattr(llm, k, v, raising=False)
    return llm


async def _up(*a, **k):
    return True


async def _down(*a, **k):
    return False


def test_diagnose_ok_when_lmstudio_serves(monkeypatch):
    """LM Studio отвечает — Ollama не проверяем и не ругаемся (evict by design)."""
    from core.services import health

    llm = _llm(monkeypatch, LMSTUDIO_ENABLED=True, LMSTUDIO_USE="main",
               LMSTUDIO_MODEL="qwen3.5-4b", _LMS_MODELS_CACHE=(0.0, []))
    calls: list = []
    orig_models = llm.lmstudio_models

    async def fake_models(force=False):
        calls.append("models")
        return ["qwen3.5-4b"]

    async def fake_ollama(*a, **k):
        calls.append("ollama")
        return False

    monkeypatch.setattr(llm, "lmstudio_models", fake_models)
    monkeypatch.setattr(llm, "ollama_available", fake_ollama)
    res = asyncio.run(health.diagnose())
    assert "ollama" not in calls, "при живом LM Studio Ollama дёргать незачем"
    brain = [i for i in res["items"] if "LM Studio" in i["what"] or "Ollama" in i["what"]]
    assert any(i["level"] == "ok" for i in brain), res["items"]
    assert not any(i["level"] == "bad" for i in brain), res["items"]


def test_diagnose_warns_lmstudio_but_keeps_ollama_ok(monkeypatch):
    """LM Studio лёг, Ollama держит запасной путь: warn, а не bad — крика «Есть проблемы» нет."""
    from core.services import health

    llm = _llm(monkeypatch, LMSTUDIO_ENABLED=True, LMSTUDIO_USE="main",
               LMSTUDIO_MODEL="qwen3.5-4b", _LMS_MODELS_CACHE=(0.0, []))

    async def no_models(force=False):
        return []

    async def ollama_up(*a, **k):
        return True

    monkeypatch.setattr(llm, "lmstudio_models", no_models)
    monkeypatch.setattr(llm, "ollama_available", ollama_up)
    res = asyncio.run(health.diagnose())
    levels = {i["level"] for i in res["items"] if "LM Studio" in i["what"] or "Ollama" in i["what"]}
    assert "bad" not in levels, res["items"]
    assert "warn" in levels or "ok" in levels
