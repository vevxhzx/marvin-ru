# -*- coding: utf-8 -*-
"""F3: reload_cloud_settings() применяет brain.gemini.* без перезапуска.

Раньше смена ключа/модели Gemini с сайта не вступала в силу: модуль держал
GEMINI_KEY/GEMINI_MODEL в globals, а reload перечитывал только brain.cloud.*.
"""
from __future__ import annotations

import os

os.environ.setdefault("ASSISTANT_TEST", "1")

import importlib  # noqa: E402


def test_reload_applies_gemini_key_and_model(monkeypatch):
    from core import config as _c
    from core.brain import llm

    monkeypatch.setattr(importlib, "reload", lambda m: m)  # config уже в памяти — не перечитывать файл
    monkeypatch.setattr(_c.cfg.brain.gemini, "api_key", "NEW-KEY-123", raising=False)
    monkeypatch.setattr(_c.cfg.brain.gemini, "model", "models/gemini-2.5-flash", raising=False)
    monkeypatch.setattr(llm, "_RESOLVED_MODEL", "stale-model", raising=False)
    monkeypatch.setattr(llm, "LAST_GEMINI_ERROR", "старая ошибка", raising=False)

    llm.reload_cloud_settings()

    assert llm.GEMINI_KEY == "NEW-KEY-123"
    assert llm.GEMINI_MODEL == "gemini-2.5-flash"  # префикс models/ срезается как при импорте
    assert llm._RESOLVED_MODEL is None  # кэш резолва сброшен — новый ключ резолвится заново
    assert llm.LAST_GEMINI_ERROR is None


def test_reload_normalizes_garbage_model_to_auto(monkeypatch):
    from core import config as _c
    from core.brain import llm

    monkeypatch.setattr(importlib, "reload", lambda m: m)
    monkeypatch.setattr(_c.cfg.brain.gemini, "model", "авто", raising=False)

    llm.reload_cloud_settings()

    assert llm.GEMINI_MODEL == "auto"
