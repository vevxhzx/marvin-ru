# -*- coding: utf-8 -*-
"""Игровой режим выгружает всё тяжёлое: Ollama + Whisper + LM Studio (а не только Ollama)."""
import asyncio
import os

os.environ.setdefault("ASSISTANT_TEST", "1")


def test_unload_stt_frees_model():
    from core.voice import stt
    stt._model = object()
    assert stt.unload_stt() is True
    assert stt._model is None


def test_unload_stt_empty_is_false():
    from core.voice import stt
    stt._model = None
    assert stt.unload_stt() is False


def test_game_mode_unloads_ollama_and_whisper(monkeypatch):
    from core.brain import llm
    from core.voice import stt
    calls = []

    async def fake_unload():
        calls.append("ollama")
        return True

    def fake_stt():
        calls.append("whisper")
        return True

    async def fake_warm():
        calls.append("warm")
        return True

    async def fake_reload():
        calls.append("lmstudio")
        return True

    monkeypatch.setattr(llm, "unload_ollama", fake_unload)
    monkeypatch.setattr(stt, "unload_stt", fake_stt)
    monkeypatch.setattr(llm, "warm_ollama", fake_warm)
    monkeypatch.setattr(llm, "reload_lmstudio", fake_reload)

    async def run():
        msg = await llm.set_game_mode(True)
        assert llm.GAME_MODE and calls == ["ollama", "whisper"], calls
        assert "whisper" in msg.lower() or "распознавани" in msg.lower(), msg
        msg = await llm.set_game_mode(False)
        await asyncio.sleep(0.05)
        await asyncio.sleep(0)
        assert not llm.GAME_MODE and "warm" in calls and "lmstudio" in calls, calls
    asyncio.run(run())


def _fake_http(monkeypatch, state, posted):
    from core.brain import llm

    class FakeResp:
        status_code = 200

        def json(self):
            return {"data": [{"id": llm.LMSTUDIO_MODEL, "state": state}]}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return FakeResp()

        async def post(self, url, json=None):
            posted.append((url, json))
            return FakeResp()

    monkeypatch.setattr("httpx.AsyncClient", FakeClient)


def test_reload_lmstudio_skips_when_loaded(monkeypatch):
    from core.brain import llm
    posted = []
    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", True)
    _fake_http(monkeypatch, "loaded", posted)
    assert asyncio.run(llm.reload_lmstudio()) is True
    assert posted == [], "загруженную модель грузить повторно нельзя (плодит дубли)"


def test_reload_lmstudio_loads_when_evicted(monkeypatch):
    from core.brain import llm
    posted = []
    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", True)
    _fake_http(monkeypatch, "not-loaded", posted)
    assert asyncio.run(llm.reload_lmstudio()) is True
    assert len(posted) == 1 and posted[0][0].endswith("/api/v1/models/load"), posted
