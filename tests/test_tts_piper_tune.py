# -*- coding: utf-8 -*-
"""Ручка темпа Piper: length_scale едет в SynthesisConfig (медленнее = чётче ударения)."""
import os

os.environ.setdefault("ASSISTANT_TEST", "1")


def test_syn_config_default_none():
    from core.voice import tts
    monkey = None
    old = (tts.PIPER_LENGTH, tts.PIPER_NOISE, tts.PIPER_NOISE_W)
    tts.PIPER_LENGTH, tts.PIPER_NOISE, tts.PIPER_NOISE_W = 1.0, None, None
    try:
        assert tts._piper_syn_config() is None
    finally:
        tts.PIPER_LENGTH, tts.PIPER_NOISE, tts.PIPER_NOISE_W = old


def test_syn_config_slow_tempo():
    from core.voice import tts
    old = (tts.PIPER_LENGTH, tts.PIPER_NOISE, tts.PIPER_NOISE_W)
    tts.PIPER_LENGTH, tts.PIPER_NOISE, tts.PIPER_NOISE_W = 1.25, None, None
    try:
        cfg = tts._piper_syn_config()
        assert cfg is not None and cfg.length_scale == 1.25
    finally:
        tts.PIPER_LENGTH, tts.PIPER_NOISE, tts.PIPER_NOISE_W = old


def test_length_clamped():
    from core.voice import tts
    assert tts._clamp_length(0.1) == 0.5
    assert tts._clamp_length(5.0) == 2.0
    assert tts._clamp_length(1.2) == 1.2


def test_cache_key_differs_by_tempo():
    from core.voice import tts
    old = tts.PIPER_LENGTH
    tts.PIPER_LENGTH = 1.0
    try:
        a = tts._cache_path("привет", ".ogg", "piper")
        tts.PIPER_LENGTH = 1.25
        b = tts._cache_path("привет", ".ogg", "piper")
        assert a != b
    finally:
        tts.PIPER_LENGTH = old


def test_wave_passes_config(monkeypatch):
    import numpy as np
    from core.voice import tts
    seen = {}

    class FakeVoice:
        def synthesize_wav(self, text, wav_file, syn_config=None):
            seen["cfg"] = syn_config
            import wave
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(22050)
            wav_file.writeframes(np.zeros(2205, dtype=np.int16).tobytes())

    monkeypatch.setattr(tts, "_piper_voice", lambda: FakeVoice())
    old = (tts.PIPER_LENGTH, tts.PIPER_NOISE, tts.PIPER_NOISE_W)
    tts.PIPER_LENGTH, tts.PIPER_NOISE, tts.PIPER_NOISE_W = 1.2, 0.8, None
    try:
        tts._piper_wave("привет")
    finally:
        tts.PIPER_LENGTH, tts.PIPER_NOISE, tts.PIPER_NOISE_W = old
    assert seen["cfg"] is not None
    assert seen["cfg"].length_scale == 1.2
    assert seen["cfg"].noise_scale == 0.8
    assert seen["cfg"].noise_w_scale is None
