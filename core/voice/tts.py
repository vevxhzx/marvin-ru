"""Синтез речи. Основной — Silero v4 (офлайн, русский, голос «eugene»), запасной — Edge TTS (Microsoft, онлайн).

Silero: одна модель ~40 МБ (data/models/v4_ru.pt), качается сама при первом запуске. Работает на CPU,
10 секунд речи ≈ 2–3 с. Текст подготавливается: числа → слова, ₽ → рублей, эмодзи/markdown вырезаются.
Выход — ogg/opus (то, что Telegram показывает как голосовое) или wav.
"""
from __future__ import annotations

import asyncio
import logging
import re
import threading
from pathlib import Path

from ..config import DATA_DIR, cfg

log = logging.getLogger("assistant.voice")

_VOICE = getattr(cfg, "voice", None)
_TTS = getattr(_VOICE, "tts", None)
ENGINE = str(getattr(_TTS, "engine", "silero") or "silero")          # silero / edge / off
SPEAKER = str(getattr(_TTS, "speaker", "eugene") or "eugene")        # silero: aidar, baya, kseniya, xenia, eugene
EDGE_VOICE = str(getattr(_TTS, "edge_voice", "ru-RU-DmitryNeural") or "ru-RU-DmitryNeural")
REPLY_VOICE = str(getattr(_TTS, "reply_in_telegram", "never") or "never")  # never — только текст (по умолчанию); voice — голосом на голосовые; always

MODEL_URL = "https://models.silero.ai/models/tts/ru/v4_ru.pt"
MODEL_PATH = DATA_DIR / "models" / "v4_ru.pt"
SAMPLE_RATE = int(getattr(_TTS, "sample_rate", 24000) or 24000)   # 24000 — вдвое быстрее 48000, на слух то же

_model = None
_lock = threading.Lock()
LAST_ERROR: str | None = None


# ------------------------------------------------------------------ подготовка текста
_EMOJI_RX = re.compile("[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U0001F900-\U0001F9FF\u2B50\u2B06\u2934\u2935\u3030\u303D\u3297\u3299\uFE0F\u200D]+")
_MD_RX = re.compile(r"[*_`#>|]+")
_URL_RX = re.compile(r"https?://\S+")
_NUM_RX = re.compile(r"(?<![\w.,])(-?)(\d{1,3}(?:[ \u00a0]\d{3})+|\d+)(?:[.,](\d+))?")

_REPL = [
    (re.compile(r"₽"), " рублей"), (re.compile(r"\bруб(?![а-яё])\.?"), " рублей"), (re.compile(r"\bтыс(?![а-яё])\.?"), " тысяч"),
    (re.compile(r"\bмлн(?![а-яё])\.?"), " миллионов"), (re.compile(r"[−](?=\s*\d)"), "минус "), (re.compile(r"(?<=\s)-(?=\d)"), "минус "), (re.compile(r"[()\[\]\"«»]"), " "), (re.compile(r"\bт\.к\."), "так как"), (re.compile(r"\bт\.е\."), "то есть"),
    (re.compile(r"\bнапр\."), "например"), (re.compile(r"(\d)%"), r"\1 процентов"), (re.compile(r"\+"), " плюс "),
    (re.compile(r"[—–]"), ","), (re.compile(r"·"), ","), (re.compile(r"\bТ-Банк\w*"), "Ти-Банк"),
    (re.compile(r"\bOllama\b", re.I), "Оллама"),
    (re.compile(r"\bGroq\b", re.I), "Грок"), (re.compile(r"\bTelegram\b", re.I), "Телеграм"), (re.compile(r"\bOK\b", re.I), "окей"),
]


def _num_words(m: re.Match) -> str:
    try:
        from num2words import num2words
    except ImportError:
        return m.group(0)
    sign, whole, frac = m.group(1), m.group(2).replace(" ", "").replace("\u00a0", ""), m.group(3)
    try:
        n = int(whole)
        if len(whole) > 12:
            return m.group(0)
        s = num2words(n, lang="ru")
        if frac and frac.strip("0"):
            s += " и " + num2words(int(frac[:2]), lang="ru")
        return ("минус " if sign else "") + s
    except Exception:
        return m.group(0)


_TIME_RX = re.compile(r"\b(\d{1,2}):(\d{2})\b")
_DATE_RX = re.compile(r"\b(\d{1,2})\.(\d{2})(?:\.(\d{4}))?\b")
_MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]


def _time_words(m: re.Match) -> str:
    h, mi = int(m.group(1)), int(m.group(2))
    try:
        from num2words import num2words
        s = num2words(h, lang="ru")
        return s + (f" {num2words(mi, lang='ru')}" if mi else " ноль ноль")
    except Exception:
        return m.group(0)


def _date_words(m: re.Match) -> str:
    d, mo = int(m.group(1)), int(m.group(2))
    if not 1 <= mo <= 12 or not 1 <= d <= 31:
        return m.group(0)
    try:
        from num2words import num2words
        day = num2words(d, lang="ru", to="ordinal")
        # «пятое» → средний род
        day = re.sub(r"(ый|ий|ой)$", "ое", day)
        return f"{day} {_MONTHS[mo - 1]}"
    except Exception:
        return m.group(0)


def prepare(text: str) -> str:
    """Текст ответа → то, что можно озвучить: без эмодзи/markdown/ссылок, числа словами."""
    t = _URL_RX.sub(" ссылка ", text)
    t = _EMOJI_RX.sub(" ", t)
    t = _MD_RX.sub(" ", t)
    for rx, rep in _REPL:
        t = rx.sub(rep, t)
    t = _TIME_RX.sub(_time_words, t)
    t = _DATE_RX.sub(_date_words, t)
    t = _NUM_RX.sub(_num_words, t)
    t = re.sub(r"\s+", " ", t).strip()
    t = re.sub(r"\s+([,.!?;:])", r"\1", t)
    return t[:1500]


# ------------------------------------------------------------------ Silero
def _download_model() -> None:
    import httpx
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MODEL_PATH.with_suffix(".part")
    log.info("Скачиваю голос Silero v4 (40 МБ) → %s", MODEL_PATH)
    with httpx.Client(timeout=120, follow_redirects=True) as c, c.stream("GET", MODEL_URL) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                f.write(chunk)
    tmp.replace(MODEL_PATH)


def _load_silero():
    global _model, LAST_ERROR
    if _model is not None:
        return _model
    with _lock:
        if _model is not None:
            return _model
        try:
            import torch
        except ImportError:
            LAST_ERROR = "Пакет torch не установлен — запустите install_voice.bat (пункт Silero)."
            raise RuntimeError(LAST_ERROR)
        if not MODEL_PATH.exists():
            _download_model()
        import os as _os
        torch.set_num_threads(max(1, min(6, (_os.cpu_count() or 4))))
        imp = torch.package.PackageImporter(str(MODEL_PATH))
        m = imp.load_pickle("tts_models", "model")
        m.to(torch.device("cpu"))
        _model = m
        LAST_ERROR = None
        log.info("Голос Silero готов (%s)", SPEAKER)
        return _model


def silero_available() -> bool:
    try:
        import torch  # noqa: F401
        return True
    except ImportError:
        return False


def _silero_wave(text: str):
    import numpy as np
    model = _load_silero()
    speaker = SPEAKER if SPEAKER in getattr(model, "speakers", [SPEAKER]) else "eugene"
    # Silero держит ~1000 символов за раз — режем по предложениям
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if len(cur) + len(sent) > 800 and cur:
            parts.append(cur); cur = sent
        else:
            cur = (cur + " " + sent).strip()
    if cur:
        parts.append(cur)
    def _say(t: str):
        """Одна попытка озвучить кусок; None — не вышло. Silero кидает IndexError('tuple index out of range')
        на тексте, где после его внутренней очистки не остаётся ни одного читаемого слова (тире, эмодзи, латиница)."""
        t = t.replace("—", ",").replace("–", ",").replace("«", "").replace("»", "").replace("…", ".")
        t = re.sub(r"\s+", " ", t).strip(" ,;:")
        if not re.search(r"[а-яА-ЯёЁ0-9]", t):
            return None
        for attempt, txt in enumerate((t, re.sub(r"[^а-яА-ЯёЁ0-9 ,.!?\-]", " ", t))):
            txt = re.sub(r"\s+", " ", txt).strip()
            if not txt or not re.search(r"[а-яА-ЯёЁ0-9]", txt):
                continue
            if not re.search(r"[.!?]$", txt):
                txt += "."
            try:
                return model.apply_tts(text=txt, speaker=speaker, sample_rate=SAMPLE_RATE, put_accent=attempt == 0, put_yo=attempt == 0).numpy()
            except Exception as e:
                log.debug("silero: %r не озвучилось (%s)", txt[:40], e)
        return None

    chunks = []
    for p in parts:
        w = _say(p)
        if w is None:
            # кусок целиком не пошёл — по предложениям, битые пропускаем
            for sent in re.split(r"(?<=[.!?])\s+", p):
                w2 = _say(sent)
                if w2 is not None:
                    chunks.append(w2)
        else:
            chunks.append(w)
    if not chunks:
        raise RuntimeError("Silero не смог озвучить текст")
    pause = np.zeros(int(SAMPLE_RATE * 0.25), dtype=np.float32)
    out = chunks[0]
    for c in chunks[1:]:
        out = np.concatenate([out, pause, c])
    return out.astype(np.float32)


def _write_audio(wave, path: Path) -> None:
    """float32 mono → ogg/opus (для Telegram) или wav."""
    import numpy as np
    if path.suffix.lower() == ".wav":
        import wave as wavmod
        pcm = (np.clip(wave, -1, 1) * 32767).astype(np.int16)
        with wavmod.open(str(path), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE); w.writeframes(pcm.tobytes())
        return
    import av
    out = av.open(str(path), "w", format="ogg")
    st = out.add_stream("libopus", rate=SAMPLE_RATE)
    st.bit_rate = 40000
    st.layout = "mono"
    frame = av.AudioFrame.from_ndarray(wave.reshape(1, -1), format="fltp", layout="mono")
    frame.sample_rate = SAMPLE_RATE
    for p in st.encode(frame):
        out.mux(p)
    for p in st.encode(None):
        out.mux(p)
    out.close()


def _silero_to_file(text: str, path: Path) -> Path:
    _write_audio(_silero_wave(text), path)
    return path


# ------------------------------------------------------------------ Edge TTS (запасной, онлайн)
async def _edge_to_file(text: str, path: Path) -> Path:
    import edge_tts
    tmp_mp3 = path.with_suffix(".mp3")
    await edge_tts.Communicate(text, EDGE_VOICE, rate="+5%").save(str(tmp_mp3))
    if path.suffix.lower() == ".mp3":
        return tmp_mp3
    # mp3 → ogg/opus через av (Telegram голосовые — только opus)
    import av
    inp = av.open(str(tmp_mp3))
    out = av.open(str(path), "w", format="ogg")
    st = out.add_stream("libopus", rate=48000); st.bit_rate = 40000; st.layout = "mono"
    resampler = av.AudioResampler(format="fltp", layout="mono", rate=48000)
    for frame in inp.decode(audio=0):
        for f in resampler.resample(frame):
            for p in st.encode(f):
                out.mux(p)
    for p in st.encode(None):
        out.mux(p)
    out.close(); inp.close()
    tmp_mp3.unlink(missing_ok=True)
    return path


# ------------------------------------------------------------------ публичное
def enabled() -> bool:
    return ENGINE != "off"


async def speak_to_file(text: str, path: str | Path) -> Path | None:
    """Озвучить текст в файл (.ogg для Telegram, .wav/.mp3 для ПК). None — не вышло (причина в LAST_ERROR)."""
    global LAST_ERROR
    if not enabled():
        return None
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    spoken = prepare(text)
    if not spoken:
        return None
    order = ["silero", "edge"] if ENGINE == "silero" else ["edge", "silero"]
    for eng in order:
        try:
            if eng == "silero":
                if not silero_available():
                    continue
                return await asyncio.to_thread(_silero_to_file, spoken, path)
            return await _edge_to_file(spoken, path)
        except Exception as e:
            LAST_ERROR = f"{eng}: {e}"
            log.warning("TTS %s не сработал: %s", eng, e)
    return None


def warmup() -> None:
    if ENGINE == "silero" and silero_available():
        threading.Thread(target=lambda: _safe(), daemon=True, name="silero-warmup").start()


def _safe():
    try:
        _load_silero()
    except Exception as e:  # pragma: no cover
        log.warning("Прогрев Silero не удался: %s", e)
