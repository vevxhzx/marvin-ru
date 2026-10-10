"""Голос: словарь-подсказка STT, порог уверенности («расслышал так себе»), кэш озвучки, запрет облака в local."""
import asyncio
import os

import pytest

os.environ.setdefault("JARVIS_TEST", "1")


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
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cache" / ".cache_v2").write_text("v2", encoding="utf-8")  # кэш уже версии v2
    text = "готово, сэр"
    spoken = tts.prepare(text)
    cp = tts._cache_path(spoken, ".ogg")
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_bytes(b"OGGDATA")
    out = tmp_path / "out.ogg"
    r = asyncio.run(tts.speak_to_file(text, out))
    assert r == out and out.read_bytes() == b"OGGDATA"


def test_tts_cache_v1_purged_once(monkeypatch, tmp_path):
    """Отравленный v1-кэш (чужой звук под чужим ключом) чистится один раз по маркеру."""
    import asyncio

    from core.voice import tts
    monkeypatch.setattr(tts, "ENGINE", "silero")
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path / "cache")
    (tmp_path / "cache").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cache" / "deadbeef1234567890ab.ogg").write_bytes(b"POISON")
    out = tmp_path / "out.ogg"
    asyncio.run(tts.speak_to_file("готово, сэр", out))
    leftovers = [p.name for p in (tmp_path / "cache").glob("*") if p.is_file() and not p.name.startswith(".")]
    assert not any(n.startswith("deadbeef") for n in leftovers)
    assert (tmp_path / "cache" / ".cache_v2").exists()


def test_tts_cache_key_depends_on_voice(monkeypatch, tmp_path):
    from core.voice import tts
    monkeypatch.setattr(tts, "CACHE_DIR", tmp_path)
    a = tts._cache_path("привет", ".ogg")
    monkeypatch.setattr(tts, "SPEAKER", "aidar")
    b = tts._cache_path("привет", ".ogg")
    assert a != b   # другой голос — другой кэш


def test_voice_demo_uses_requested_speaker(tmp_path, monkeypatch):
    """Демо silero идёт запрошенным голосом, даже если настроен edge: раньше общий
    speak_to_file молча озвучивал демо текущим движком — все карточки звучали одинаково."""
    from pathlib import Path

    from core import config
    from core.voice import tts
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tts, "ENGINE", "edge")   # настроен edge — демо silero всё равно Байей
    monkeypatch.setattr(tts, "EDGE_VOICE", "ru-RU-DmitryNeural")
    monkeypatch.setattr(tts, "silero_available", lambda: True)
    before = tts.SPEAKER
    seen = {}

    def fake_synth(text, path):
        seen["speaker"] = tts.SPEAKER
        Path(path).write_bytes(b"RIFFfake")
        return Path(path)
    monkeypatch.setattr(tts, "_silero_to_file", fake_synth)
    # наследие бага: старый кривой файл удаляется, вместо него — свежий
    demo_dir = tmp_path / "voice_demo"
    demo_dir.mkdir(parents=True, exist_ok=True)
    (demo_dir / "silero_baya.wav").write_bytes(b"OLD")
    from fastapi.testclient import TestClient
    from core.api.app import app
    r = TestClient(app, client=("127.0.0.1", 5555), base_url="http://testserver").get(
        "/api/voice/demo", params={"engine": "silero", "voice": "baya"})
    assert r.status_code == 200, r.text
    assert seen.get("speaker") == "baya", "демо озвучилось не тем голосом"
    assert tts.SPEAKER == before, "глобальный голос после демо не вернулся"
    assert not (demo_dir / "silero_baya.wav").exists(), "старый кривой файл остался"
    assert (demo_dir / "silero_baya_v2.wav").exists()


def test_voice_demo_silero_missing_errors_honestly(tmp_path, monkeypatch):
    """Без Silero — честная 500, а не тихое демо чужим движком."""
    from core import config
    from core.voice import tts
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(tts, "silero_available", lambda: False)
    from fastapi.testclient import TestClient
    from core.api.app import app
    r = TestClient(app, client=("127.0.0.1", 5555), base_url="http://testserver").get(
        "/api/voice/demo", params={"engine": "silero", "voice": "baya"})
    assert r.status_code == 500
