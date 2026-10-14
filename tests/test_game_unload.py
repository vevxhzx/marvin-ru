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

    async def fake_eject(ids=None):
        calls.append("lms-unload")
        return ["qwen3.5-4b"]

    monkeypatch.setattr(llm, "unload_ollama", fake_unload)
    monkeypatch.setattr(llm, "lmstudio_unload", fake_eject)
    monkeypatch.setattr(stt, "unload_stt", fake_stt)
    monkeypatch.setattr(llm, "warm_ollama", fake_warm)
    monkeypatch.setattr(llm, "reload_lmstudio", fake_reload)

    async def run():
        msg = await llm.set_game_mode(True)
        assert llm.GAME_MODE and calls == ["ollama", "lms-unload", "whisper"], calls
        assert "whisper" in msg.lower() or "распознавани" in msg.lower(), msg
        msg = await llm.set_game_mode(False)
        await asyncio.sleep(0.05)
        await asyncio.sleep(0)
        assert not llm.GAME_MODE and "warm" in calls and "lmstudio" in calls, calls
    asyncio.run(run())


def test_game_mode_ejects_lmstudio_main_and_small(monkeypatch):
    """Старт игры выгружает модели LM Studio (а не только Ollama): иначе 4B+2B
    продолжают занимать ~6.7 ГБ и игра дерётся с ботом за видеопамять."""
    from core.brain import llm

    seen = []

    async def fake_eject(ids=None):
        seen.append(list(ids or []))
        return ["qwen3.5-4b"]

    async def fake_noop():
        return True

    def fake_stt():
        return False

    monkeypatch.setattr(llm, "lmstudio_unload", fake_eject)
    monkeypatch.setattr(llm, "unload_ollama", fake_noop)
    monkeypatch.setattr(llm, "warm_ollama", fake_noop)
    monkeypatch.setattr(llm, "reload_lmstudio", fake_noop)
    monkeypatch.setattr("core.voice.stt.unload_stt", fake_stt)

    async def run():
        await llm.set_game_mode(True)
        assert seen, "выгрузка LM Studio не вызвана"
    asyncio.run(run())


def test_game_mode_off_reloads_small_model_too(monkeypatch):
    """Выход из игры поднимает обратно и малую модель, а не только основную:
    иначе судья после катки молча падает в вопросы."""
    from core.brain import llm
    calls = []

    async def fake_unload():
        return True

    async def fake_warm():
        calls.append("warm")
        return True

    async def fake_reload():
        calls.append("lmstudio")
        return True

    async def fake_reload_small():
        calls.append("lmstudio-small")
        return True

    def fake_stt():
        return False

    monkeypatch.setattr(llm, "unload_ollama", fake_unload)
    monkeypatch.setattr(llm, "warm_ollama", fake_warm)
    monkeypatch.setattr(llm, "reload_lmstudio", fake_reload)
    monkeypatch.setattr(llm, "reload_lmstudio_small", fake_reload_small)
    monkeypatch.setattr("core.voice.stt.unload_stt", fake_stt)

    async def run():
        await llm.set_game_mode(True)
        await llm.set_game_mode(False)
        await asyncio.sleep(0.05)
        await asyncio.sleep(0)
        assert "lmstudio-small" in calls, calls
    asyncio.run(run())


def test_lms_unload_never_breaks_game_mode(monkeypatch):
    """Нет CLI / чужой адрес / таймаут — игровой режим всё равно включается,
    в лог уходит причина, наружу исключение не торчит."""
    import asyncio

    from core.brain.llm import lmstudio as L
    monkeypatch.setattr(L, "_lms_exe", lambda: None)
    assert asyncio.run(L.lmstudio_unload(["qwen3.5-4b"])) == []


def test_lms_unload_skips_remote_server(monkeypatch):
    """LM Studio на чужой машине: локальный `lms unload` выгрузил бы не то —
    поэтому при не-loopback адресе молча пропускаем."""
    import asyncio

    from core.brain import llm
    from core.brain.llm import lmstudio as L
    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", True)
    monkeypatch.setattr(llm, "LMSTUDIO_BASE", "http://192.168.1.50:1234/v1")
    assert asyncio.run(L.lmstudio_unload(["qwen3.5-4b"])) == []


def test_lms_unload_calls_cli_per_model(monkeypatch):
    """Каждой модели — свой вызов `lms unload <id>`, пустые имена пропускаем."""
    import asyncio
    import subprocess

    from core.brain import llm
    from core.brain.llm import lmstudio as L
    argv = []

    class Done:
        returncode = 0

    def fake_run(cmd, **kw):
        argv.append(cmd)
        return Done()

    monkeypatch.setattr(llm, "LMSTUDIO_ENABLED", True)
    monkeypatch.setattr(llm, "LMSTUDIO_BASE", "http://127.0.0.1:1234/v1")
    monkeypatch.setattr(L, "_lms_exe", lambda: "lms")
    monkeypatch.setattr(subprocess, "run", fake_run)
    got = asyncio.run(L.lmstudio_unload(["qwen3.5-4b", "", "qwen3.5-2b"]))
    assert got == ["qwen3.5-4b", "qwen3.5-2b"]
    assert [a[-2:] for a in argv] == [["unload", "qwen3.5-4b"], ["unload", "qwen3.5-2b"]]


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
