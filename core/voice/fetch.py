"""Скачивание голосовых моделей: проверка SHA256 (если хеш известен) + безопасная распаковка zip.

Честная позиция: настоящих хешей моделей мы офлайн не знаем и выдумывать их нельзя,
поэтому проверка — «verify-if-known». Карта «URL → sha256» задаётся в конфиге
(`brain.voice.expected_sha256`, по умолчанию пусто) или переменной окружения
`VOICE_EXPECTED_SHA256` (JSON-объект). Хеш неизвестен — один warning за процесс
«hash unknown, skipping verify», скачивание идёт как раньше. Хеш известен и не
сошёлся — ValueError, файл удаляется.

Распаковка zip — всегда строгая: члены с `..`, абсолютными путями и симлинками
отклоняются (zip-slip), иначе ValueError до извлечения чего-либо.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import zipfile
from pathlib import Path

log = logging.getLogger("jarvis.voice")

_WARNED_UNKNOWN: set[str] = set()


def expected_hashes() -> dict[str, str]:
    """Карта URL → sha256 hex из конфига и/или окружения. Пусто по умолчанию."""
    out: dict[str, str] = {}
    try:
        from ..config import cfg
        node = getattr(getattr(getattr(cfg, "brain", None), "voice", None), "expected_sha256", None)
        if isinstance(node, dict):
            out.update({str(k): str(v).lower() for k, v in node.items() if v})
        elif hasattr(node, "__dict__"):
            out.update({str(k): str(v).lower() for k, v in vars(node).items() if v})
    except Exception:
        pass
    raw = os.getenv("VOICE_EXPECTED_SHA256", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                out.update({str(k): str(v).lower() for k, v in data.items() if v})
        except ValueError:
            log.warning("VOICE_EXPECTED_SHA256 — не JSON, игнорирую")
    return out


def verify_bytes(data: bytes, url: str) -> None:
    """Сверить байты с известным хешем. Неизвестен — warn-once, mismatch — ValueError."""
    want = expected_hashes().get(url or "")
    if not want:
        if url not in _WARNED_UNKNOWN:
            _WARNED_UNKNOWN.add(url)
            log.warning("hash unknown for %s, skipping verify (задайте brain.voice.expected_sha256)", url)
        return
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise ValueError(f"sha256 mismatch for {url}: expected {want[:16]}…, got {got[:16]}…")


def verify_file(path: str | Path, url: str) -> None:
    """То же для файла на диске (читается кусками, модели — десятки МБ)."""
    want = expected_hashes().get(url or "")
    if not want:
        if url not in _WARNED_UNKNOWN:
            _WARNED_UNKNOWN.add(url)
            log.warning("hash unknown for %s, skipping verify (задайте brain.voice.expected_sha256)", url)
        return
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != want:
        raise ValueError(f"sha256 mismatch for {url}: файл {Path(path).name} не совпал с ожидаемым")


def safe_extract_zip(zpath: str | Path, dest: str | Path) -> None:
    """Распаковать zip, отказав членам с `..`, абсолютными путями и симлинками. Всегда строго."""
    dest = Path(dest).resolve()
    with zipfile.ZipFile(zpath) as z:
        for info in z.infolist():
            name = info.filename
            # отказ: абсолютные пути, выход наверх, windows-диски, симлинки
            if (name.startswith(("/", "\\")) or ".." in Path(name).parts
                    or (len(name) > 1 and name[1] == ":")
                    or ((info.external_attr >> 16) & 0o170000) == 0o120000):
                raise ValueError(f"zip member refused: {name!r}")
            target = (dest / name).resolve()
            if target != dest and dest not in target.parents:
                raise ValueError(f"zip member escapes dest: {name!r}")
        z.extractall(dest)
