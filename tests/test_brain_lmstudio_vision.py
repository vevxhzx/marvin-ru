# -*- coding: utf-8 -*-
"""Зрение через LM Studio: картинка уходит загруженной модели, а не только в Ollama.

Поле «модель зрения» смотрит в Ollama — у кого основная на LM Studio, чеки падали
с «Ollama не отвечает». Теперь LM Studio пробуется первым (когда включён),
дальше — Ollama и облако, как раньше.
"""
from __future__ import annotations

import asyncio
import base64

import pytest

from tests.test_core import fresh_db  # noqa: E402,F401  (autouse-изоляция БД)

# минимальный валидный PNG (1x1) в base64
PNG_1PX = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)
JPEG_HEAD = base64.b64encode(b"\xff\xd8\xff\xe0" + b"\x00" * 20).decode()


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._p = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"http {self.status_code}")

    def json(self):
        return self._p


class _FakeClient:
    def __init__(self, seen, models=None, vision_text="Чек на 749 ₽.", vision_empty=False):
        self._seen = seen
        self._models = [{"id": m} for m in (models if models is not None else ["qwen/qwen3.5-9b"])]
        self._vision_text = vision_text
        self._vision_empty = vision_empty

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, **kw):
        self._seen.append(("GET", url))
        if url.endswith("/models"):
            return _Resp(200, {"data": self._models})
        return _Resp(200, {"models": []})

    async def post(self, url, json=None, **kw):
        self._seen.append(("POST", url, json))
        if url.endswith("/chat/completions"):
            text = "" if self._vision_empty else self._vision_text
            return _Resp(200, {"choices": [{"message": {"content": text}}]})
        return _Resp(200, {"message": {"content": "Ollama видит: чек."}})


def _lms_on(monkeypatch, seen, **kw):
    from core.brain import llm

    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", True)
    monkeypatch.setattr(llm, "LMSTUDIO_BASE", "http://127.0.0.1:1234/v1")
    monkeypatch.setattr(llm, "LMSTUDIO_MODEL", "google/gemma-4-e4b")
    monkeypatch.setattr(llm, "LMSTUDIO_USE", "main")
    monkeypatch.setattr(llm, "VISION_WHERE", "auto")
    monkeypatch.setattr(llm, "GAME_MODE", False)
    monkeypatch.setattr(llm, "_LMS_MODELS_CACHE", (0.0, []))
    monkeypatch.setattr(llm, "_local_client", lambda timeout: _FakeClient(seen, **kw))
    return llm


def test_vision_goes_to_lmstudio_first(monkeypatch):
    from core.brain import llm

    seen: list = []
    _lms_on(monkeypatch, seen)
    out = asyncio.run(llm.describe_image(PNG_1PX, "что на чеке?"))
    assert "749" in out
    posts = [s for s in seen if s[0] == "POST" and s[1].endswith("/chat/completions")]
    assert len(posts) == 1
    parts = posts[0][2]["messages"][0]["content"]
    kinds = sorted(p["type"] for p in parts)
    assert kinds == ["image_url", "text"]
    img = next(p for p in parts if p["type"] == "image_url")
    assert img["image_url"]["url"].startswith("data:image/png;base64,")
    assert posts[0][2].get("reasoning_effort") == "none"


def test_empty_vision_falls_back_to_ollama(monkeypatch):
    from core.brain import llm

    seen: list = []
    _lms_on(monkeypatch, seen, vision_empty=True)
    monkeypatch.setattr(llm, "_local_vision_available", lambda: asyncio.sleep(0, result=True))
    out = asyncio.run(llm.describe_image(PNG_1PX, "что на чеке?"))
    assert out == "Ollama видит: чек."
    assert any(s[0] == "POST" and s[1].endswith("/api/chat") for s in seen)


def test_game_mode_skips_lmstudio_vision(monkeypatch):
    from core.brain import llm

    seen: list = []
    _lms_on(monkeypatch, seen)
    monkeypatch.setattr(llm, "GAME_MODE", True)
    monkeypatch.setattr(llm, "_local_vision_available", lambda: asyncio.sleep(0, result=False))
    monkeypatch.setattr(llm, "VISION_WHERE", "local")
    assert asyncio.run(llm.describe_image(PNG_1PX, "что на чеке?")) is None
    assert not [s for s in seen if s[0] == "POST" and s[1].endswith("/chat/completions")]


def test_img_mime_sniff():
    from core.brain import llm

    assert llm._img_mime(PNG_1PX) == "image/png"
    assert llm._img_mime(JPEG_HEAD) == "image/jpeg"
    assert llm._img_mime("мусор") == "image/jpeg"


def test_hint_mentions_lmstudio_when_enabled(monkeypatch):
    from core.brain import llm

    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", True)
    monkeypatch.setattr(llm, "_LMS_MODELS_CACHE", (0.0, []))
    assert "LM Studio" in llm.vision_hint()


def test_status_shows_lmstudio(monkeypatch):
    import time

    from core.brain import llm

    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", True)
    monkeypatch.setattr(llm, "VISION_WHERE", "auto")
    monkeypatch.setattr(llm, "_LMS_MODELS_CACHE", (time.monotonic(), ["qwen/qwen3.5-9b"]))
    assert "LM Studio" in llm.vision_status()
