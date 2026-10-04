"""TTS engine resolution: в local-режиме edge принудительно становится silero."""
import os

os.environ.setdefault("JARVIS_TEST", "1")


def test_resolve_engine_forces_silero_in_local(monkeypatch):
    from core.voice import tts

    monkeypatch.setattr(tts, "ENGINE", "edge", raising=False)
    monkeypatch.setattr(tts.cfg.brain, "mode", "local", raising=False)
    monkeypatch.setattr(tts, "_LOCAL_EDGE_NOTICE_DONE", False, raising=False)
    assert tts.resolve_engine() == "silero"
    assert tts.resolve_engine("edge") == "silero"
    # hybrid/cloud не трогаем, off остаётся off
    monkeypatch.setattr(tts.cfg.brain, "mode", "hybrid", raising=False)
    assert tts.resolve_engine() == "edge"
    monkeypatch.setattr(tts.cfg.brain, "mode", "cloud", raising=False)
    assert tts.resolve_engine("edge") == "edge"
    assert tts.resolve_engine("off") == "off"
    monkeypatch.setattr(tts.cfg.brain, "mode", "local", raising=False)
    assert tts.resolve_engine("off") == "off"
    assert tts.resolve_engine("silero") == "silero"
