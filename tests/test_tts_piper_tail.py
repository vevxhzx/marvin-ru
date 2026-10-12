# -*- coding: utf-8 -*-
"""Хвост фразы: Piper отдаёт звук встык (0 мс тишины, последний сэмпл не в нуле) —
кодек/плеер подъедают последний слог. Добиваем паузу."""
import os

os.environ.setdefault("ASSISTANT_TEST", "1")


def test_piper_wave_ends_with_silence(monkeypatch):
    import numpy as np
    from core.voice import tts
    sr = 22050
    body = (np.ones(sr, dtype=np.int16) * 1000).tobytes()

    class FakeVoice:
        def synthesize_wav(self, text, w, syn_config=None):
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(sr)
            w.writeframes(body)

    monkeypatch.setattr(tts, "_piper_voice", lambda: FakeVoice())
    wave = tts._piper_wave("тест хвоста")
    tail = wave[-int(tts.SAMPLE_RATE * tts.PIPER_TAIL_SEC):]
    assert len(tail) == int(tts.SAMPLE_RATE * tts.PIPER_TAIL_SEC)
    assert (tail == 0).all(), "хвост должен быть тишиной"
    assert abs(wave[-len(tail) - 1]) > 0, "пауза должна идти после звука, а не вместо него"
