"""Голосовые модели: verify-if-known (совпал/не совпал/неизвестен) + zip-sanitize на tmp-файлах."""
import hashlib
import os
import zipfile

os.environ.setdefault("JARVIS_TEST", "1")

URL = "https://example.invalid/models/v4_ru.pt"
DATA = b"fake-model-bytes"


def _hashes(monkeypatch, mapping):
    from core.voice import fetch
    monkeypatch.delenv("VOICE_EXPECTED_SHA256", raising=False)
    monkeypatch.setattr(fetch, "expected_hashes", lambda: dict(mapping))


def test_verify_match_and_mismatch(tmp_path, monkeypatch):
    from core.voice import fetch

    good = hashlib.sha256(DATA).hexdigest()
    _hashes(monkeypatch, {URL: good})
    fetch.verify_bytes(DATA, URL)  # совпал — тихо
    f = tmp_path / "m.pt"
    f.write_bytes(DATA)
    fetch.verify_file(f, URL)
    import pytest
    _hashes(monkeypatch, {URL: "0" * 64})
    with pytest.raises(ValueError):
        fetch.verify_bytes(DATA, URL)
    with pytest.raises(ValueError):
        fetch.verify_file(f, URL)


def test_verify_unknown_warns_once_and_passes(tmp_path, monkeypatch, caplog):
    import logging

    from core.voice import fetch

    _hashes(monkeypatch, {})
    monkeypatch.setattr(fetch, "_WARNED_UNKNOWN", set(), raising=False)
    with caplog.at_level(logging.WARNING, logger="jarvis.voice"):
        fetch.verify_bytes(DATA, URL)
        fetch.verify_bytes(DATA, URL)
    msgs = [r.message for r in caplog.records if "hash unknown" in r.message]
    assert len(msgs) == 1, "предупреждение — один раз за процесс"
    f = tmp_path / "m.pt"
    f.write_bytes(DATA)
    fetch.verify_file(f, URL)  # неизвестен — пропускаем, не падаем


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name in members:
            z.writestr(name, b"x")


def test_safe_extract_ok_and_refusals(tmp_path):
    import pytest

    from core.voice.fetch import safe_extract_zip

    good = tmp_path / "good.zip"
    _zip(good, ["model/am/file.dat", "readme.txt"])
    out = tmp_path / "out"
    safe_extract_zip(good, out)
    assert (out / "model" / "am" / "file.dat").exists()

    for evil in ("../evil.dat", "/abs.dat", "a/../../evil.dat"):
        bad = tmp_path / "bad.zip"
        _zip(bad, [evil])
        with pytest.raises(ValueError):
            safe_extract_zip(bad, tmp_path / "out2")
