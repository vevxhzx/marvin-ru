"""Голос: словарь-подсказка STT, порог уверенности («расслышал так себе»), кэш озвучки, запрет облака в local."""
import asyncio
import os

import pytest

os.environ.setdefault("ASSISTANT_TEST", "1")


@pytest.fixture(autouse=True)
def fresh_db(tmp_path, monkeypatch):
    from core import db
    from sqlmodel import create_engine
    from sqlalchemy import event
    eng = create_engine(f"sqlite:///{tmp_path / 't.db'}", connect_args={"check_same_thread": False})
    event.listen(eng, "connect", db._pragmas)
    monkeypatch.setattr(db, "engine", eng)
    db.init_db()
    yield


def test_looks_unsure_thresholds():
    from core.voice import stt
    assert stt.looks_unsure(0.9, 0.0) is False
    assert stt.looks_unsure(0.3, 0.0) is True      # низкая уверенность → переспросить
    assert stt.looks_unsure(0.9, 0.9) is True      # похоже на шум → переспросить


def test_hotwords_includes_own_data(monkeypatch):
    """initial_prompt Whisper подсказывает имена и названия из своих же данных (локально)."""
    from core.voice import stt
    from core.db import session, Client
    monkeypatch.setattr(stt, "_HINT_CACHE", None)
    with session() as s:
        s.add(Client(name="Пятёрочка"))
        s.commit()
    hint = stt._hotwords()
    assert "Пятёрочка" in hint and "Марвин" in hint


def test_cloud_stt_only_outside_local(monkeypatch):
    """В режиме local голос в облако не уходит никогда, даже если voice.stt.cloud включён."""
    from core.voice import stt
    from core.brain import llm
    monkeypatch.setattr(stt, "STT_CLOUD", True)
    monkeypatch.setattr(llm, "MODE", "local")
    assert stt._cloud_ok() is False
    monkeypatch.setattr(llm, "MODE", "hybrid")
    assert stt._cloud_ok() is True
    monkeypatch.setattr(stt, "STT_CLOUD", False)
    assert stt._cloud_ok() is False


def test_tts_cache_returns_copy(monkeypatch, tmp_path):
    """Кэш озвучки: одинаковая фраза отдаётся из data/voice_cache, синтез не запускается повторно."""
    from core.voice import tts
    monkeypatch.setattr(tts, "ENGINE", "silero")
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "cache")
    text = "готово, сэр"
    spoken = tts.prepare(text)
    cp = tts._cache_path(spoken, ".ogg")
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_bytes(b"OGGDATA")
    out = tmp_path / "out.ogg"
    r = asyncio.run(tts.speak_to_file(text, out))
    assert r == out and out.read_bytes() == b"OGGDATA"


def test_tts_cache_key_depends_on_voice(monkeypatch, tmp_path):
    from core.voice import tts
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path)
    a = tts._cache_path("привет", ".ogg")
    monkeypatch.setattr(tts, "SPEAKER", "aidar")
    b = tts._cache_path("привет", ".ogg")
    assert a != b   # другой голос — другой кэш
