# -*- coding: utf-8 -*-
"""ПК-клиент должен говорить выбранным движком: при ENGINE=piper — Piper,
а не молча Microsoft Edge (баг: _synth знал только silero/edge)."""
import os

os.environ.setdefault("ASSISTANT_TEST", "1")

import numpy as np


def _tts(monkeypatch, engine="piper", piper_ok=True, silero_ok=False):
    import voice_client
    from core.voice import tts
    monkeypatch.setattr(tts, "resolve_engine", lambda configured=None: engine)
    monkeypatch.setattr(tts, "ENGINE", engine)
    if piper_ok:
        monkeypatch.setattr(tts, "_piper_wave", lambda text: np.zeros(16000, dtype=np.float32))
    else:
        def _boom(text):
            raise RuntimeError("piper сломан")
        monkeypatch.setattr(tts, "_piper_wave", _boom)
    monkeypatch.setattr(tts, "silero_available", lambda: silero_ok)
    return voice_client


def test_synth_uses_piper_when_configured(monkeypatch):
    vc = _tts(monkeypatch, engine="piper", piper_ok=True, silero_ok=True)
    from core.voice import tts
    w, sr = vc._synth("привет")
    assert w is not None and len(w) == 16000
    assert sr == tts.SAMPLE_RATE


def test_synth_falls_back_to_silero_when_piper_broken(monkeypatch):
    vc = _tts(monkeypatch, engine="piper", piper_ok=False, silero_ok=True)
    from core.voice import tts
    monkeypatch.setattr(tts, "_silero_wave", lambda text: np.zeros(8000, dtype=np.float32))
    w, sr = vc._synth("привет")
    assert w is not None and len(w) == 8000


def test_synth_silero_path_unchanged(monkeypatch):
    vc = _tts(monkeypatch, engine="silero", piper_ok=True, silero_ok=True)
    from core.voice import tts
    called = []
    monkeypatch.setattr(tts, "_silero_wave", lambda text: called.append(text) or np.zeros(8000, dtype=np.float32))
    w, sr = vc._synth("привет")
    assert called == ["привет"] and w is not None
