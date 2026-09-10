"""Wake word «ассистент» — Vosk small-ru (офлайн, ~45 МБ, потоковое распознавание на CPU без нагрузки).

Vosk постоянно слушает микрофон и переводит речь в текст. Как только в тексте встречается имя ассистента
(с вариациями — джервис, джарвиз, жарвис…), запускается запись команды для Whisper.
"""
from __future__ import annotations

import json
import logging
import zipfile

from ..config import DATA_DIR

log = logging.getLogger("assistant.voice")

MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip"
MODEL_DIR = DATA_DIR / "models" / "vosk-model-small-ru-0.22"
SAMPLE_RATE = 16000

# как Vosk может расслышать имя (строится из assistant.name)
from .. import identity
WAKE_RX = identity.VOSK_WAKE_RX


def _download() -> None:
    import httpx
    MODEL_DIR.parent.mkdir(parents=True, exist_ok=True)
    zpath = MODEL_DIR.parent / "vosk-small-ru.zip"
    log.info("Скачиваю модель wake word Vosk (45 МБ) → %s", MODEL_DIR)
    with httpx.Client(timeout=300, follow_redirects=True) as c, c.stream("GET", MODEL_URL) as r:
        r.raise_for_status()
        with open(zpath, "wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                f.write(chunk)
    with zipfile.ZipFile(zpath) as z:
        z.extractall(MODEL_DIR.parent)
    zpath.unlink(missing_ok=True)


class WakeDetector:
    """Потоковый детектор: скармливаем 16 кГц int16 кусками, .feed() возвращает текст, если услышал «ассистент»."""

    def __init__(self):
        import vosk
        vosk.SetLogLevel(-1)
        if not (MODEL_DIR / "am").exists():
            _download()
        self._model = vosk.Model(str(MODEL_DIR))
        self._rec = vosk.KaldiRecognizer(self._model, SAMPLE_RATE)
        self._rec.SetWords(False)
        self.last_partial = ""

    def feed(self, pcm_bytes: bytes) -> str | None:
        """Возвращает распознанный хвост фразы после «ассистент» (может быть пустым ''), либо None если слова не было."""
        if self._rec.AcceptWaveform(pcm_bytes):
            text = json.loads(self._rec.Result()).get("text", "")
            self.last_partial = ""
        else:
            text = json.loads(self._rec.PartialResult()).get("partial", "")
            if text == self.last_partial:
                return None
            self.last_partial = text
        if not text:
            return None
        m = WAKE_RX.search(text)
        if not m:
            return None
        tail = text[m.end():].strip()
        self.reset()
        return tail

    def reset(self) -> None:
        import vosk
        self._rec = vosk.KaldiRecognizer(self._model, SAMPLE_RATE)
        self.last_partial = ""


def available() -> bool:
    try:
        import vosk  # noqa: F401
        return True
    except ImportError:
        return False
