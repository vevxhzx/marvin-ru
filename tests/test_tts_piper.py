"""Piper TTS — третий движок озвучки (офлайн, CPU)."""
import asyncio
import os

import pytest

os.environ.setdefault("JARVIS_TEST", "1")

piper = pytest.importorskip("piper")


def test_resolve_engine_piper_stays_in_local(monkeypatch):
    from core.voice import tts

    monkeypatch.setattr(tts, "ENGINE", "piper", raising=False)
    monkeypatch.setattr(tts.cfg.brain, "mode", "local", raising=False)
    assert tts.resolve_engine() == "piper"
    assert tts.resolve_engine("piper") == "piper"


def test_cache_path_differs_by_engine(monkeypatch, tmp_path):
    from core.voice import tts

    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(tts, "ENGINE", "silero", raising=False)
    a = tts._cache_path("привет", ".ogg")
    monkeypatch.setattr(tts, "ENGINE", "piper", raising=False)
    b = tts._cache_path("привет", ".ogg")
    assert a != b


def test_speak_to_file_piper_calls_backend(monkeypatch, tmp_path):
    from core.voice import tts

    monkeypatch.setattr(tts, "ENGINE", "piper", raising=False)
    monkeypatch.setattr(tts.cfg.brain, "mode", "local", raising=False)
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "cache")
    seen = {}

    def fake_piper(text, path):
        from pathlib import Path
        seen["text"] = text
        # prepare() переиспользуется: числа словами, без эмодзи
        assert "рублей" in text or "₽" not in text
        Path(path).write_bytes(b"RIFFfake-wav")
        return Path(path)

    monkeypatch.setattr(tts, "_piper_available", lambda: True)
    monkeypatch.setattr(tts, "_piper_to_file", fake_piper)
    out = tmp_path / "out.wav"
    r = asyncio.run(tts.speak_to_file("готово 700 ₽ 🎉", out))
    assert r == out and out.read_bytes() == b"RIFFfake-wav"
    assert seen.get("text") == tts.prepare("готово 700 ₽ 🎉")


def test_piper_wave_uses_python_api_not_cli(monkeypatch, tmp_path):
    import subprocess
    import wave as wavmod

    import numpy as np

    from core.voice import tts

    def _no_subprocess(*a, **k):
        raise AssertionError("CLI больше не используется")

    monkeypatch.setattr(subprocess, "run", _no_subprocess)

    class _FakeVoice:
        class config:
            sample_rate = 22050

        def synthesize_wav(self, text, w):
            assert "Привет" in text
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(22050)
            w.writeframes((np.zeros(2205, dtype=np.int16)).tobytes())

    class _FakePiperVoice:
        @staticmethod
        def load(path):
            assert str(path).endswith(".onnx")
            return _FakeVoice()

    import piper.voice

    monkeypatch.setattr(piper.voice, "PiperVoice", _FakePiperVoice)
    monkeypatch.setattr(tts, "_download_piper_model", lambda: None)
    monkeypatch.setattr(tts, "_piper_model_paths", lambda: (tmp_path / "v.onnx", tmp_path / "v.onnx.json"))
    wave = tts._piper_wave("Привет")
    assert wave.dtype == np.float32 and len(wave) > 0


def test_fallback_caches_under_producing_engine(monkeypatch, tmp_path):
    """Упавший piper + живой silero: мужской звук не должен оседать под piper-ключом."""
    import asyncio

    from core.voice import tts

    monkeypatch.setattr(tts, "ENGINE", "piper", raising=False)
    monkeypatch.setattr(tts.cfg.brain, "mode", "local", raising=False)
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "cache")

    def _boom(text, path):
        raise RuntimeError("piper лёг")

    def _male(text, path):
        from pathlib import Path
        Path(path).write_bytes(b"RIFFmale")
        return Path(path)

    monkeypatch.setattr(tts, "_piper_available", lambda: True)
    monkeypatch.setattr(tts, "_piper_to_file", _boom)
    monkeypatch.setattr(tts, "silero_available", lambda: True)
    monkeypatch.setattr(tts, "_silero_to_file", _male)
    out = tmp_path / "out.ogg"
    assert asyncio.run(tts.speak_to_file("привет", out)) == out
    keys = {p.name for p in (tmp_path / "cache").glob("*") if p.is_file() and not p.name.startswith(".")}
    piper_key = tts._cache_path("привет", ".ogg", "piper").name
    silero_key = tts._cache_path("привет", ".ogg", "silero").name
    assert piper_key != silero_key
    assert silero_key in keys
    assert piper_key not in keys


def test_piper_has_four_russian_voices():
    from core.api.routers.pc import VOICES

    ids = sorted(v["id"] for v in VOICES if v["engine"] == "piper")
    assert ids == ["ru_RU-denis-medium", "ru_RU-dmitri-medium", "ru_RU-irina-medium", "ru_RU-ruslan-medium"]
