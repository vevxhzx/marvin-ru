# -*- coding: utf-8 -*-
"""Локальный провайдер: LM Studio или Ollama — кто угодно, лишь бы отвечал.

Раньше код спрашивал только Ollama, и при основном на LM Studio думал, что
«локально никого нет»: старт ругался, запасные пути врали, память шла в облако.
Теперь везде local_available(). Плюс тишина в логах от опросов.
"""
from __future__ import annotations

import pytest

from tests.test_core import fresh_db  # noqa: E402,F401  (autouse-изоляция БД)


@pytest.mark.parametrize("raw, want", [
    ("http://127.0.0.1:1234/api/v1", "http://127.0.0.1:1234/v1"),  # хвост /api/v1 чистим
    ("http://127.0.0.1:1234/api", "http://127.0.0.1:1234/v1"),      # и голый /api
    ("http://127.0.0.1:1234", "http://127.0.0.1:1234/v1"),
])
def test_api_suffix_normalized(raw, want):
    from core.brain import llm

    assert llm._norm_lms_base(raw) == want


async def _run(coro):
    import asyncio
    return await coro


def test_local_available_either_engine(monkeypatch):
    """Хоть один движок отвечает — локально есть кому ответить."""
    import asyncio

    from core.brain import llm

    async def up(*a, **k):
        return True

    async def down(*a, **k):
        return False

    # только LM Studio (Ollama лежит) — было False, стало True
    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", True)
    monkeypatch.setattr(llm, "lmstudio_available", up)
    monkeypatch.setattr(llm, "ollama_available", down)
    assert asyncio.run(llm.local_available()) is True
    # только Ollama — как раньше
    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", False)
    monkeypatch.setattr(llm, "ollama_available", up)
    assert asyncio.run(llm.local_available()) is True
    # оба лежат — честно False
    monkeypatch.setattr(llm, "ollama_available", down)
    assert asyncio.run(llm.local_available()) is False


def test_last_error_tracks_failures(monkeypatch):
    """Причина сбоя запоминается и стирается успехом — лог говорит правду."""
    from core.brain import llm

    assert llm.lms_last_error() == ""
    llm._lms_fail("нет соединения")
    assert llm.lms_last_error() == "нет соединения"
    llm._lms_ok()
    assert llm.lms_last_error() == ""


def test_why_distinguishes_refused_and_timeout():
    from core.brain import llm

    refused = llm._lms_why(ConnectionError("refused"), "http://127.0.0.1:1234/v1")
    assert "перезапускается" in refused or "закрыт" in refused
    slow = llm._lms_why(TimeoutError("timed out"), "http://127.0.0.1:1234/v1")
    assert "таймаут" in slow


def test_noise_filter_quiets_polling_but_keeps_errors():
    import logging

    import run as _runmod

    f = _runmod._NoiseFilter()

    def rec(msg):
        return logging.LogRecord("uvicorn.access", logging.INFO, __file__, 1, msg, (), None)

    assert f.filter(rec('127.0.0.1:1 - "GET /api/health HTTP/1.1" 200')) is False
    assert f.filter(rec('127.0.0.1:1 - "GET /api/pc/state HTTP/1.1" 200')) is False
    assert f.filter(rec('127.0.0.1:1 - "GET /api/orders/timer HTTP/1.1" 200')) is False
    assert f.filter(rec('127.0.0.1:1 - "POST /api/pc/ping HTTP/1.1" 200')) is False
    assert f.filter(rec('127.0.0.1:1 - "GET /api/events/stream?client=pc HTTP/1.1" 200')) is False
    assert f.filter(rec('127.0.0.1:1 - "GET /api/diagnose HTTP/1.1" 200')) is False
    assert f.filter(rec('127.0.0.1:1 - "GET /api/health HTTP/1.1" 500')) is True
    assert f.filter(rec('127.0.0.1:1 - "GET /api/finance/summary HTTP/1.1" 200')) is True
    assert f.filter(rec("обычная строка лога")) is True
